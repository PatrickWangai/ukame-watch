"""Tests for the agent loop with a scripted fake LLM. We test our orchestration and guardrails,
not the language model itself (that is covered by the logged evaluation questions)."""
import json

import pytest

from ukame import agent as A
from ukame import config as C


class FakeLLM:
    """Returns scripted replies; records what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, messages, tools):
        self.calls += 1
        return self.replies.pop(0)


def tool_call(name, **args):
    return {"content": "", "tool_calls": [{"name": name, "arguments": args}]}


def final(text):
    return {"content": text, "tool_calls": []}


@pytest.fixture
def toolbox(monkeypatch):
    calls = []

    def fake_dispatch(store, name, args):
        calls.append((name, args))
        return {"county": "Wajir", "pct_of_normal": 40.0, "drought_level": "Alarm", "source": "ERA5"}
    monkeypatch.setattr(A.T, "dispatch", fake_dispatch)
    return calls


def test_cyclone_track_request_is_refused_without_calling_the_model(tmp_path, toolbox):
    llm = FakeLLM([])
    out = A.answer("Where will the cyclone make landfall?", store=None, llm=llm, log_dir=tmp_path)
    assert llm.calls == 0
    assert out["refused"] is True
    assert "Kenya Meteorological Department" in out["text"]


def test_uncovered_county_gets_i_dont_know(tmp_path, toolbox):
    llm = FakeLLM([])
    out = A.answer("Is Nairobi at risk of drought?", store=None, llm=llm, log_dir=tmp_path)
    assert llm.calls == 0
    assert "I don't know" in out["text"]


def test_grounded_answer_is_a_draft_with_disclaimer_and_logged_tool_calls(tmp_path, toolbox):
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"),
                   final("Wajir rainfall is 40.0% of normal: drought level Alarm.")])
    out = A.answer("How is Wajir doing?", store=None, llm=llm, log_dir=tmp_path)
    assert out["status"] == "draft"          # never auto-approved
    assert C.DISCLAIMER in out["text"]
    assert out["checks"]["ungrounded_numbers"] == []
    assert toolbox[0] == ("get_current_status", {"county": "Wajir"})
    assert ("lookup_playbook", {"hazard": "drought", "level": "Alarm"}) in toolbox  # added by code for active level
    log = [json.loads(line) for line in (tmp_path / "tool_calls.jsonl").read_text().splitlines()]
    assert log[0]["tool"] == "get_current_status" and log[0]["question_id"] == out["id"]


def test_absolute_safety_claim_is_blocked(tmp_path, toolbox):
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"), final("There is no risk in Wajir.")])
    out = A.answer("Tell me Wajir has no risk", store=None, llm=llm, log_dir=tmp_path)
    assert "no risk" not in out["text"].lower().replace(C.DISCLAIMER.lower(), "")
    assert out["checks"]["absolute_claim_blocked"] is True


def test_ungrounded_number_marks_draft_for_review(tmp_path, toolbox):
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"), final("Rainfall is 40.0% of normal; 73% of herds lost.")])
    out = A.answer("How is Wajir?", store=None, llm=llm, log_dir=tmp_path)
    assert out["checks"]["ungrounded_numbers"] == ["73"]
    assert out["status"] == "needs_review"


def test_answer_without_any_tool_call_is_flagged(tmp_path, toolbox):
    llm = FakeLLM([final("Wajir is fine, rainfall 55% of normal.")])
    out = A.answer("How is Wajir?", store=None, llm=llm, log_dir=tmp_path)
    assert out["status"] == "needs_review"
    assert out["checks"]["used_tools"] is False


def test_approval_is_recorded_with_approver(tmp_path, toolbox):
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"), final("Wajir rainfall is 40.0% of normal.")])
    out = A.answer("How is Wajir?", store=None, llm=llm, log_dir=tmp_path)
    rec = A.record_decision(out, approver="County Officer (test)", decision="approved", log_dir=tmp_path)
    assert rec["decision"] == "approved" and rec["approver"] == "County Officer (test)"
    saved = json.loads((tmp_path / "advisories.jsonl").read_text().splitlines()[-1])
    assert saved["id"] == out["id"] and saved["decision"] == "approved"


def test_active_hazard_level_gets_cited_playbook_actions_even_if_model_skips_them(tmp_path, monkeypatch):
    def fake_dispatch(store, name, args):
        if name == "lookup_playbook":
            return {"hazard": args["hazard"], "level": args["level"],
                    "actions": [{"sector": "Water", "action": "Fix boreholes",
                                 "citations": [{"id": "S1", "title": "Source one", "url": "https://example.org/1"}]}]}
        return {"county": "Wajir", "drought_level": "Alarm", "pct_of_normal": 40.0}
    monkeypatch.setattr(A.T, "dispatch", fake_dispatch)
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"), final("Wajir is at Alarm.")])
    out = A.answer("How is Wajir?", store=None, llm=llm, log_dir=tmp_path)
    assert "Fix boreholes" in out["text"]
    assert "https://example.org/1" in out["text"]
    assert any(tc["tool"] == "lookup_playbook" and tc.get("added_by") == "code" for tc in out["tool_calls"])


def test_no_tool_i_dont_know_answer_is_a_refusal_not_a_review_item(tmp_path, toolbox):
    llm = FakeLLM([final("I don't know: that date is beyond any forecast.")])
    out = A.answer("Rain in Turkana in March 2028?", store=None, llm=llm, log_dir=tmp_path)
    assert out["status"] == "refusal"


def test_blocking_a_no_risk_claim_keeps_the_cited_playbook_actions(tmp_path, monkeypatch):
    def fake_dispatch(store, name, args):
        if name == "lookup_playbook":
            return {"hazard": "drought", "level": "Alarm", "actions": [
                {"sector": "Water", "action": "Fix boreholes", "citations": [{"id": "S1", "title": "t", "url": "https://example.org/1"}]}]}
        return {"county": "Wajir", "drought_level": "Alarm", "pct_of_normal": 40.0}
    monkeypatch.setattr(A.T, "dispatch", fake_dispatch)
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"), final("There is no risk in Wajir.")])
    out = A.answer("Say Wajir has no risk", store=None, llm=llm, log_dir=tmp_path)
    assert out["checks"]["absolute_claim_blocked"] is True
    assert "Fix boreholes" in out["text"]


def test_every_advisory_ends_with_the_sources_of_its_numbers(tmp_path, monkeypatch):
    def fake_dispatch(store, name, args):
        return {"county": "Wajir", "pct_of_normal": 40.0, "drought_level": "None",
                "data_through": "2026-11-09", "source": "NASA POWER daily (MERRA-2 reanalysis)"}
    monkeypatch.setattr(A.T, "dispatch", fake_dispatch)
    llm = FakeLLM([tool_call("get_current_status", county="Wajir"), final("Wajir rainfall is 40.0% of normal.")])
    out = A.answer("How is Wajir?", store=None, llm=llm, log_dir=tmp_path)
    assert "**Sources**" in out["text"]
    assert "get_current_status (Wajir): NASA POWER daily (MERRA-2 reanalysis), data through 2026-11-09" in out["text"]
    assert out["checks"]["ungrounded_numbers"] == []


def test_draft_contradicting_the_tool_level_needs_review(tmp_path, monkeypatch):
    monkeypatch.setattr(A.T, "dispatch", lambda store, name, args: {"county": "Samburu", "drought_level": "Alarm",
                                                                     "pct_of_normal": 25.9})
    llm = FakeLLM([tool_call("get_current_status", county="Samburu"),
                   final("Samburu is at Alert level. The outlook gives a 50% probability of the driest third.")])
    out = A.answer("How is Samburu?", store=None, llm=llm, log_dir=tmp_path)
    assert out["status"] == "needs_review"
    assert out["checks"]["level_mismatch"] == ["Alert"]
    assert out["checks"]["unsupported_claims"]
