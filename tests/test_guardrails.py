"""Tests for the agent's code-level guardrails. These run before/after the LLM, so they hold even
if the model ignores its instructions."""
import pytest

from ukame import guardrails as G


@pytest.mark.parametrize("q", [
    "Where will the cyclone make landfall next week?",
    "Predict the track of the tropical cyclone near Lamu",
    "what path will the cyclone take",
])
def test_cyclone_track_requests_are_detected(q):
    assert G.is_cyclone_track_request(q)


@pytest.mark.parametrize("q", [
    "How many people live in Wajir?",
    "Is drought likely in Turkana?",
    "How has cyclone exposure changed over decades?",  # exposure history is allowed; track prediction is not
])
def test_ordinary_questions_are_not_flagged_as_cyclone_track(q):
    assert not G.is_cyclone_track_request(q)


@pytest.mark.parametrize("text", [
    "There is no risk of drought in Wajir.",
    "Garissa is completely safe this season",
    "Zero risk of flooding.",
    "Rainfall is guaranteed to be normal",
    "While there is no immediate risk of flooding, stay alert.",
])
def test_absolute_safety_claims_are_caught(text):
    assert G.makes_absolute_safety_claim(text)


def test_hedged_statements_are_allowed():
    assert not G.makes_absolute_safety_claim("Drought risk is low but not zero; monitor NDMA bulletins.")


def test_numbers_not_in_tool_outputs_are_flagged():
    tools_text = '{"pct_normal": 42.3, "population_2020": 1032456, "threshold_mm": 61.5}'
    answer = "Rainfall is 42.3% of normal, affecting 1,032,456 people; threshold 61.5 mm. Expect 80% failure."
    assert G.ungrounded_numbers(answer, tools_text) == ["80"]


def test_rounded_numbers_from_tool_outputs_are_accepted():
    tools_text = '{"pct_normal": 42.347, "probability_dry": 0.6213}'
    answer = "Rainfall is 42.3% of normal; probability of a dry season is 62%."
    assert G.ungrounded_numbers(answer, tools_text) == []


def test_years_and_list_markers_are_ignored():
    assert G.ungrounded_numbers("Since 1991 (step 1) we track 7-day forecasts.", "{}",
                                allowed=["1991", "7"]) == []


def test_resolve_county_is_case_insensitive():
    assert G.resolve_county("wajir") == "Wajir"
    assert G.resolve_county("  TURKANA ") == "Turkana"


def test_resolve_county_returns_none_for_unknown_place():
    assert G.resolve_county("Atlantis") is None


def test_county_mentions_distinguish_covered_uncovered_and_none():
    assert G.county_mentions("Is Mandera at risk?") == {"covered": ["Mandera"], "uncovered": []}
    assert G.county_mentions("What about Nairobi?") == {"covered": [], "uncovered": ["Nairobi"]}
    assert G.county_mentions("hello") == {"covered": [], "uncovered": []}


def test_ordinal_percentiles_are_methodology_not_data():
    assert G.ungrounded_numbers("Above the 99th percentile and the 95th percentile.", "{}") == []


def test_level_word_that_contradicts_the_tool_is_flagged():
    outputs = [{"county": "Samburu", "drought_level": "Alarm"}]
    assert G.level_mismatches("The drought situation in Samburu is at Alert level.", outputs) == ["Alert"]


def test_matching_level_and_playbook_verbs_are_not_flagged():
    outputs = [{"county": "Samburu", "drought_level": "Alarm"}]
    text = "Samburu is at Alarm level. Alert livestock officers to monitor pasture."
    assert G.level_mismatches(text, outputs) == []


def test_normal_matches_a_tool_level_of_none():
    assert G.level_mismatches("Drought level is Normal.", [{"drought_level": "None"}]) == []


def test_outlook_claim_without_outlook_tool_is_unsupported():
    assert G.unsupported_claims("The outlook shows a 50% probability of the driest third.", ["get_current_status"])
    assert not G.unsupported_claims("The outlook shows under 5%.", ["get_seasonal_outlook"])
    assert not G.unsupported_claims("Rainfall is 26% of normal.", ["get_current_status"])


def test_level_mismatch_is_caught_inside_markdown_formatting():
    outputs = [{"county": "Samburu", "drought_level": "Alarm"}]
    assert G.level_mismatches("- **Current Drought Level:** Alert", outputs) == ["Alert"]
    assert G.level_mismatches("Drought level: *Alarm*", outputs) == []
