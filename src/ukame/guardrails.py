"""Code-level guardrails for the advisory agent.

These run outside the language model, so they still hold if the model ignores its instructions:
  * cyclone-track requests are refused before the model sees them;
  * absolute safety claims ("no risk") are blocked after the model answers;
  * every number in an answer must trace to a tool output, or the draft is flagged.
"""
from __future__ import annotations

import re

from . import config as C

OTHER_KENYAN_COUNTIES = [
    "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu", "Homa Bay", "Kajiado", "Kakamega",
    "Kericho", "Kiambu", "Kilifi", "Kirinyaga", "Kisii", "Kisumu", "Kwale", "Laikipia", "Lamu", "Machakos",
    "Makueni", "Meru", "Migori", "Mombasa", "Murang'a", "Nairobi", "Nakuru", "Nandi", "Narok", "Nyamira",
    "Nyandarua", "Nyeri", "Siaya", "Taita Taveta", "Tana River", "Tharaka", "Trans Nzoia", "Uasin Gishu",
    "Vihiga", "West Pokot",
]

_CYCLONE = re.compile(r"\b(cyclone|hurricane|typhoon|tropical storm)s?\b", re.I)
_TRACK = re.compile(r"\b(path|track|trajectory|landfall|where will|head(?:ing)?|hit|predict|forecast)\b", re.I)

_ABSOLUTE = re.compile(
    r"\b(no risk|zero risk|completely safe|totally safe|100% safe|guaranteed|nothing to worry|no chance)\b", re.I)

_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")

CYCLONE_REFUSAL = (
    "I can't predict cyclone paths or landfall. For tropical cyclone forecasts in the South-West Indian Ocean, "
    "follow the Kenya Meteorological Department (meteo.go.ke) and the WMO Regional Specialized Meteorological "
    "Centre La Réunion. This tool covers drought, heavy rain and heat for eight inland counties."
)


def is_cyclone_track_request(question: str) -> bool:
    return bool(_CYCLONE.search(question) and _TRACK.search(question))


def makes_absolute_safety_claim(text: str) -> bool:
    return bool(_ABSOLUTE.search(text))


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def ungrounded_numbers(answer: str, tools_text: str, allowed: list[str] | None = None) -> list[str]:
    """Numbers in `answer` that cannot be traced to `tools_text`.

    A number counts as grounded if it equals a tool number, or a tool number rounded to 0-2 decimals,
    or a tool fraction expressed as a percentage. Small integers (0-10) are ignored: they are
    list markers, counts and day spans that carry little risk.
    """
    tool_values = [v for v in (_to_float(t) for t in _NUMBER.findall(tools_text)) if v is not None]
    candidates = set()
    for v in tool_values:
        for x in (v, v * 100):
            candidates.update({round(x, 0), round(x, 1), round(x, 2), x})
    allowed_values = {_to_float(a) for a in (allowed or [])}
    bad = []
    for raw in _NUMBER.findall(answer):
        val = _to_float(raw.rstrip(".,"))
        if val is None or (val.is_integer() and 0 <= val <= 10) or val in allowed_values:
            continue
        if not any(abs(val - c) < 1e-9 for c in candidates):
            bad.append(raw.replace(",", "").rstrip("."))
    return bad


def resolve_county(name: str) -> str | None:
    key = name.strip().lower()
    return next((c for c in C.COUNTIES if c.lower() == key), None)


def county_mentions(question: str) -> dict:
    def found(names):
        return [n for n in names if re.search(rf"\b{re.escape(n)}\b", question, re.I)]
    return {"covered": found(C.COUNTIES), "uncovered": found(OTHER_KENYAN_COUNTIES)}
