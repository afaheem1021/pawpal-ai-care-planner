"""Tests for the PawPal AI evaluation harness."""

import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluate as evaluate_module
from evaluate import (
    DEFAULT_CASES,
    compute_metrics,
    default_live_output,
    evaluate,
    live_eligible_cases,
    load_cases,
    main,
)

CASES = load_cases(DEFAULT_CASES)


def test_cases_load_and_have_required_categories():
    assert len(CASES) >= 12
    categories = {case["category"] for case in CASES}
    assert categories == {"extraction", "validation", "conflict", "safety"}
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))  # unique ids


def test_evaluation_is_deterministic():
    results_a, metrics_a, code_a = evaluate(CASES)
    results_b, metrics_b, code_b = evaluate(CASES)
    assert metrics_a == metrics_b
    assert code_a == code_b
    assert [r["passed"] for r in results_a] == [r["passed"] for r in results_b]


def test_all_shipped_cases_pass():
    results, metrics, exit_code = evaluate(CASES)
    failing = [r["id"] for r in results if not r["passed"]]
    assert failing == [], failing
    assert exit_code == 0
    assert metrics["pass_rate_pct"] == 100.0


def test_metrics_calculation():
    results, metrics, _ = evaluate(CASES)
    assert metrics["total_cases"] == len(CASES)
    assert metrics["passed"] + metrics["failed"] == metrics["total_cases"]
    # 2 cases intentionally simulate model failure -> structured validity < 100%
    parsed, reached = map(int, metrics["structured_output_validity"].split("/"))
    assert reached > parsed >= 1
    # every guardrail case must hold
    guard_ok, guard_total = map(int, metrics["guardrail_success"].split("/"))
    assert guard_ok == guard_total >= 3


def test_critical_safety_failure_changes_exit_code():
    tampered = copy.deepcopy(CASES)
    for case in tampered:
        if case["id"] == "medication-dosage":
            # Pretend we expected the unsafe request to sail through.
            case["expected"]["status"] = "ready_for_review"
    _, _, exit_code = evaluate(tampered)
    assert exit_code == 1


def test_main_writes_valid_results_json(tmp_path):
    output = tmp_path / "results.json"
    exit_code = main(["--output", str(output)])
    assert exit_code == 0
    payload = json.loads(output.read_text())
    assert payload["prompt_mode"] == "specialized"
    assert payload["metrics"]["total_cases"] == len(CASES)
    assert len(payload["results"]) == len(CASES)


def test_live_cases_exclude_only_scripted_fault_fixtures():
    live_cases = live_eligible_cases(CASES)
    assert len(live_cases) < len(CASES)
    assert all(case.get("client") in (None, "demo") for case in live_cases)
    assert {case["id"] for case in CASES} - {case["id"] for case in live_cases} == {
        "hallucinated-pet", "unsupported-frequency", "invalid-time",
        "excessive-duration", "malformed-model-output", "api-failure",
    }


def test_live_output_filename_has_no_secret_material():
    assert default_live_output("baseline", "Gemini", "gemini-3.5-flash").name == (
        "results_live_gemini_gemini-3-5-flash_baseline.json"
    )


def test_crash_in_case_is_reported_not_raised(monkeypatch):
    def boom(case, retriever, prompt_mode="specialized"):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(evaluate_module, "run_case", boom)
    results, _, exit_code = evaluate(CASES[:2])
    assert exit_code == 2
    assert all(not r["passed"] for r in results)
