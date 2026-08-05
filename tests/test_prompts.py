"""Regression tests for the production model instructions."""

from pawpal_ai.prompts import SPECIALIZED_SYSTEM_PROMPT, build_user_prompt


def test_specialized_prompt_defaults_duration_instead_of_blocking():
    normalized = " ".join(SPECIALIZED_SYSTEM_PROMPT.split())

    assert "A duration is NOT blocking information" in normalized
    assert "NEVER ask for a duration in missing_information" in normalized
    assert "general cleaning/grooming/brushing/bath 15" in normalized


def test_specialized_prompt_keeps_explicit_work_hour_times():
    assert "An explicit user-requested time always wins" in SPECIALIZED_SYSTEM_PROMPT
    assert "NEVER put availability in missing_information" in SPECIALIZED_SYSTEM_PROMPT


def test_user_prompt_repeats_duration_and_availability_rules():
    prompt = build_user_prompt("Walk Ron at noon.", [], [], [])
    normalized = " ".join(prompt.split())

    assert "Missing duration is not blocking" in normalized
    assert "availability is a warning" in normalized
    assert "never missing information" in normalized
