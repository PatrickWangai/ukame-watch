"""The advisory agent: a small local LLM (via Ollama) that drafts advisories using only tool outputs.

Flow for every question:
  1. Code guardrails first: cyclone-track requests are refused; uncovered counties get "I don't know".
  2. The LLM may call the six tools in agent_tools. Every call is logged to logs/tool_calls.jsonl.
  3. Code guardrails after: absolute safety claims are blocked, every number is checked against
     tool outputs, and an answer with no tool use is flagged.
  4. The result is a DRAFT. Nothing is final until a person approves it (record_decision).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import agent_tools as T
from . import config as C
from . import guardrails as G

SYSTEM_PROMPT = f"""You are Ukame Watch, a planning-support assistant for county disaster managers in eight
arid counties of northern Kenya: {", ".join(C.COUNTIES)}.

Rules you must follow:
1. Get every fact and number from a tool. Never calculate, estimate or invent numbers yourself.
   Copy numbers exactly as the tools return them.
2. If a tool returns an error or the data is missing, say "I don't know" and explain what is missing.
3. Never say there is "no risk" or that anywhere is "safe". Risk can change; describe the level the tools report.
4. You do not predict cyclone paths. You do not replace official warnings: the Kenya Meteorological
   Department and NDMA drought bulletins take priority.
5. When a hazard level is Alert, Alarm, Watch or Warning, call lookup_playbook and list its actions with sources.
6. Use the exact level word a tool returns (Normal, Alert, Alarm). Never change it.
7. Only describe the seasonal outlook if you called get_seasonal_outlook.
8. Keep advisories short, using these headings: Situation, Outlook (only with outlook data), Recommended actions, Limits.
"""

MAX_ROUNDS = 5
_I_DONT_KNOW = re.compile(r"\bI (?:don'?t|do not|can'?t|cannot) (?:know|have|predict)", re.I)
_ACTIVE = {"drought_level": ("drought", {"Alert", "Alarm"}), "heavy_rain_level": ("heavy_rain", {"Watch", "Warning"}),
           "heat_level": ("heat", {"Watch", "Warning"})}


def _active_levels(outputs: list) -> list:
    """(hazard, level) pairs that tool outputs report as active, in first-seen order."""
    found = []
    for o in outputs:
        for key, (hazard, levels) in _ACTIVE.items():
            if o.get(key) in levels and (hazard, o[key]) not in found:
                found.append((hazard, o[key]))
    return found


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def ollama_llm(messages: list, tools: list) -> dict:
    """Adapter: calls the local Ollama model and normalises the reply."""
    import ollama
    resp = ollama.chat(model=C.AGENT_MODEL, messages=messages, tools=tools, options={"temperature": 0})
    msg = resp.message
    calls = [{"name": tc.function.name, "arguments": dict(tc.function.arguments or {})}
             for tc in (msg.tool_calls or [])]
    return {"content": msg.content or "", "tool_calls": calls}


def _result(qid, question, text, status, tool_calls, checks, refused=False) -> dict:
    return {"id": qid, "question": question, "text": f"{text.strip()}\n\n_{C.DISCLAIMER}_",
            "status": status, "refused": refused, "tool_calls": tool_calls, "checks": checks,
            "created_at": _now(), "model": C.AGENT_MODEL}


def answer(question: str, store, llm=None, log_dir: Path = C.LOGS) -> dict:
    llm = llm or ollama_llm
    log_dir = Path(log_dir)
    qid = f"q-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    checks = {"used_tools": False, "ungrounded_numbers": [], "absolute_claim_blocked": False,
              "level_mismatch": [], "unsupported_claims": []}

    # 1. Pre-LLM guardrails ------------------------------------------------------------------
    if G.is_cyclone_track_request(question):
        out = _result(qid, question, G.CYCLONE_REFUSAL, "refusal", [], checks, refused=True)
        _append(log_dir / "answers.jsonl", out)
        return out
    mentions = G.county_mentions(question)
    if mentions["uncovered"] and not mentions["covered"]:
        text = (f"I don't know: {', '.join(mentions['uncovered'])} is not covered by this tool. "
                f"It covers {', '.join(C.COUNTIES)}. Please check NDMA bulletins for other counties.")
        out = _result(qid, question, text, "refusal", [], checks, refused=True)
        _append(log_dir / "answers.jsonl", out)
        return out

    # 2. Tool-using LLM loop -----------------------------------------------------------------
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    tool_log, tool_outputs, text = [], [], None
    for _ in range(MAX_ROUNDS):
        reply = llm(messages, T.TOOL_SPECS)
        if not reply["tool_calls"]:
            text = reply["content"]
            break
        messages.append({"role": "assistant", "content": reply["content"],
                         "tool_calls": [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                                        for c in reply["tool_calls"]]})
        for call in reply["tool_calls"]:
            result = T.dispatch(store, call["name"], call["arguments"])
            rec = {"question_id": qid, "time": _now(), "tool": call["name"], "arguments": call["arguments"],
                   "result": result}
            _append(log_dir / "tool_calls.jsonl", rec)
            tool_log.append(rec)
            tool_outputs.append(result)
            messages.append({"role": "tool", "content": json.dumps(result, default=str), "tool_name": call["name"]})
    if text is None:
        text = "I don't know: I could not complete this request within the allowed number of tool calls."

    # 3. Post-LLM guardrail on the model's own words -----------------------------------------------------------------
    checks["used_tools"] = bool(tool_log)
    if G.makes_absolute_safety_claim(text):
        checks["absolute_claim_blocked"] = True
        levels = [f"{o.get('county', '')}: {k} = {o[k]}" for o in tool_outputs for k in
                  ("drought_level", "heavy_rain_level", "heat_level") if k in o]
        text = ("I can't rule out risk, and I won't describe any county as risk-free. "
                + ("What the tools report: " + "; ".join(levels) + ". " if levels else "")
                + "Conditions can change quickly; follow Kenya Meteorological Department and NDMA updates.")
    # Claims the tools do not support: a wrong level word, or an outlook nobody looked up.
    checks["level_mismatch"] = G.level_mismatches(text, tool_outputs)
    checks["unsupported_claims"] = G.unsupported_claims(text, [tc["tool"] for tc in tool_log])
    # 4. Code-enforced playbook: small models often skip it, so active hazard levels always get cited actions.
    looked_up = {(tc["arguments"].get("hazard"), tc["arguments"].get("level"))
                 for tc in tool_log if tc["tool"] == "lookup_playbook"}
    for hazard, level in _active_levels(tool_outputs):
        if (hazard, level) in looked_up:
            continue
        looked_up.add((hazard, level))
        args = {"hazard": hazard, "level": level}
        result = T.dispatch(store, "lookup_playbook", args)
        rec = {"question_id": qid, "time": _now(), "tool": "lookup_playbook", "arguments": args,
               "result": result, "added_by": "code"}
        _append(log_dir / "tool_calls.jsonl", rec)
        tool_log.append(rec)
        tool_outputs.append(result)
        if "actions" in result:
            text += f"\n\n**Recommended actions: {hazard.replace('_', ' ')} {level}** (Ukame Watch playbook)\n"
            text += "\n".join(f"- {a['sector']}: {a['action']} (" +
                              ", ".join(f"[{c['id']}]({c['url']})" for c in a["citations"]) + ")"
                              for a in result["actions"])

    # 5. Cite the source of every number: one line per tool result that carries a source.
    cites = []
    for rec in tool_log:
        res = rec["result"]
        if isinstance(res, dict) and res.get("source"):
            who = f" ({res['county']})" if res.get("county") else ""
            when = f", data through {res['data_through']}" if res.get("data_through") else ""
            line = f"- {rec['tool']}{who}: {res['source']}{when}"
            if line not in cites:
                cites.append(line)
    if cites:
        text += "\n\n**Sources**\n" + "\n".join(cites)

    checks["used_tools"] = bool(tool_log)
    tools_text = json.dumps(tool_outputs, default=str)
    allowed = re.findall(r"\d[\d,]*(?:\.\d+)?", question + " " + C.DISCLAIMER)
    checks["ungrounded_numbers"] = G.ungrounded_numbers(text, tools_text, allowed=allowed)

    status = "draft"
    if (checks["ungrounded_numbers"] or not checks["used_tools"] or checks["level_mismatch"]
            or checks["unsupported_claims"]):
        status = "needs_review"
    if not checks["used_tools"] and not checks["ungrounded_numbers"] and _I_DONT_KNOW.search(text):
        status = "refusal"  # an honest "I don't know" without data needs no approval
    out = _result(qid, question, text, status, tool_log, checks)
    _append(log_dir / "answers.jsonl", out)
    return out


def record_decision(result: dict, approver: str, decision: str, note: str = "", log_dir: Path = C.LOGS) -> dict:
    """Human-in-the-loop: a named person approves or rejects a draft. Only approved drafts may be shared."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    rec = {"id": result["id"], "question": result["question"], "text": result["text"],
           "status_before": result["status"], "decision": decision, "approver": approver, "note": note,
           "decided_at": _now()}
    _append(Path(log_dir) / "advisories.jsonl", rec)
    return rec
