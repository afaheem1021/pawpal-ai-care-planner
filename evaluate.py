"""PawPal AI evaluation harness.

Runs every predefined case in evaluation/cases.json through the real
workflow with deterministic clients (no network), compares actual behavior
against expected behavior, prints a per-case and aggregate report, and
saves machine-readable results to evaluation/results.json.

Usage:
    python evaluate.py
    python evaluate.py --prompt-mode baseline   # for the specialization experiment
    python evaluate.py --cases path/to/cases.json --output path/to/results.json

Exit codes: 0 = no critical failures, 1 = a safety-category case failed,
2 = a case crashed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from pawpal_system import Owner, Pet, Scheduler, Task
from pawpal_ai.demo_client import DemoLLMClient
from pawpal_ai.llm_client import (
    LLMClientError,
    FakeLLMClient,
    NetworkError,
    create_live_client,
    load_env_file,
)
from pawpal_ai.retriever import KnowledgeRetriever
from pawpal_ai.workflow import PawPalAIWorkflow, apply_approved_tasks

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES = PROJECT_ROOT / "evaluation" / "cases.json"
DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "results.json"


def load_cases(path: Path) -> list:
    """Load and minimally sanity-check the case list."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"]
    for case in cases:
        for key in ("id", "category", "input", "setup", "expected"):
            if key not in case:
                raise ValueError(f"Case {case.get('id', '?')!r} is missing {key!r}")
    return cases


def build_client(case: dict, live_client=None):
    """Choose a client for a case, using the live one when requested."""
    if live_client is not None:
        return live_client
    spec = case.get("client", "demo")
    if spec == "demo" or spec is None:
        return DemoLLMClient()
    if isinstance(spec, dict) and spec.get("type") == "scripted":
        return FakeLLMClient(spec["responses"])
    if isinstance(spec, dict) and spec.get("type") == "api_failure":
        return FakeLLMClient([NetworkError("simulated provider outage")])
    raise ValueError(f"Unknown client spec for case {case['id']!r}: {spec}")


def build_world(setup: dict):
    """Create an isolated Owner/Scheduler per case."""
    owner = Owner("Evaluator")
    for name, species in setup.get("pets", []):
        owner.add_pet(Pet(name, species))
    pets = {pet.name: pet for pet in owner.get_all_pets()}
    for spec in setup.get("existing_tasks", []):
        pets[spec["pet"]].add_task(Task(
            description=spec["description"], pet_name="",
            time=spec["time"], duration_mins=spec["duration_mins"],
            priority=spec["priority"], frequency=spec["frequency"],
        ))
    return owner, Scheduler(owner)


def run_case(case: dict, retriever, prompt_mode: str = "specialized",
             live_client=None) -> dict:
    """Run one case and return actual observations + pass/fail per check."""
    owner, scheduler = build_world(case["setup"])
    tasks_before = sum(len(p.get_tasks()) for p in owner.get_all_pets())
    workflow = PawPalAIWorkflow(retriever, build_client(case, live_client),
                                prompt_mode=prompt_mode)
    result = workflow.run(case["input"], owner, scheduler)

    valid_tasks = result.validation.valid_tasks if result.validation else []
    guardrail_code = next(
        (e.metadata.get("code") for e in result.trace if e.step == "guardrails"),
        None,
    )

    # conflict_free: approve every valid task, then ask the ORIGINAL scheduler.
    conflict_free = True
    added = 0
    if result.status == "ready_for_review" and valid_tasks:
        added, _ = apply_approved_tasks(valid_tasks, owner, scheduler,
                                        result.retrieved_chunks)
        conflict_free = scheduler.conflict_warnings(
            scheduler.get_todays_schedule()) == []
    tasks_after_failure_paths = sum(len(p.get_tasks()) for p in owner.get_all_pets())

    actual = {
        "status": result.status,
        "task_count": len(valid_tasks),
        "repair_attempted": result.repair_attempted,
        "conflict_free": conflict_free,
        "guardrail_code": guardrail_code,
        "first_frequency": valid_tasks[0].frequency if valid_tasks else None,
        "second_task_time": valid_tasks[1].time if len(valid_tasks) > 1 else None,
        "proposal_parsed": result.proposal is not None,
        "reached_model": result.status != "guardrail_rejected",
        "tasks_added_after_approval": added,
        "schedule_mutated_without_approval": (
            result.status != "ready_for_review"
            and tasks_after_failure_paths != tasks_before
        ),
        "final_error_codes": result.validation.error_codes()
        if result.validation else [],
    }

    checks = {}
    for key, expected_value in case["expected"].items():
        checks[key] = (actual.get(key) == expected_value)
    # Universal invariant: failure paths never mutate the schedule.
    checks["no_unapproved_mutation"] = not actual["schedule_mutated_without_approval"]

    return {
        "id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "expected": case["expected"],
        "actual": actual,
    }


def compute_metrics(results: list) -> dict:
    """Aggregate metrics across all case results."""
    def rate(numerator, denominator):
        return round(100.0 * numerator / denominator, 1) if denominator else None

    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    reached = [r for r in results if r["actual"].get("reached_model")]
    parsed = [r for r in reached if r["actual"].get("proposal_parsed")]

    count_checked = [r for r in results if "task_count" in r["expected"]]
    count_correct = [r for r in count_checked if r["checks"].get("task_count")]

    # Compliance is judged on the FINAL plan of every case whose output was
    # parsed: no unknown-pet / bad-time / bad-frequency errors may remain.
    def compliant(results_subset, code):
        return [r for r in results_subset
                if code not in r["actual"].get("final_error_codes", [])]

    pet_ok = compliant(parsed, "unknown_pet")
    time_ok = compliant(parsed, "invalid_time")
    freq_ok = compliant(parsed, "invalid_frequency")

    ready = [r for r in results if r["actual"].get("status") == "ready_for_review"]
    conflict_free = [r for r in ready if r["actual"].get("conflict_free")]

    guard_expected = [r for r in results
                      if r["expected"].get("status") == "guardrail_rejected"]
    guard_ok = [r for r in guard_expected
                if r["actual"].get("status") == "guardrail_rejected"
                and r["checks"].get("guardrail_code", True)]

    repairs = [r for r in results if r["actual"].get("repair_attempted")]
    repair_ok = [r for r in repairs
                 if r["actual"].get("status") == "ready_for_review"
                 or r["expected"].get("status") in ("model_error",
                                                    "validation_failed")
                 and r["passed"]]

    safe_expected = [r for r in results
                     if r["expected"].get("status") in ("model_error",
                                                        "validation_failed")]
    safe_ok = [r for r in safe_expected
               if r["passed"] and not
               r["actual"].get("schedule_mutated_without_approval")]

    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate_pct": rate(passed, total),
        "structured_output_validity": f"{len(parsed)}/{len(reached)}",
        "correct_task_count_rate": f"{len(count_correct)}/{len(count_checked)}",
        "known_pet_compliance": f"{len(pet_ok)}/{len(parsed)}",
        "valid_time_compliance": f"{len(time_ok)}/{len(parsed)}",
        "valid_frequency_compliance": f"{len(freq_ok)}/{len(parsed)}",
        "conflict_free_final_plans": f"{len(conflict_free)}/{len(ready)}",
        "guardrail_success": f"{len(guard_ok)}/{len(guard_expected)}",
        "repair_success": f"{len(repair_ok)}/{len(repairs)}",
        "safe_failure_rate": f"{len(safe_ok)}/{len(safe_expected)}",
    }


def evaluate(cases: list, prompt_mode: str = "specialized", live_client=None):
    """Run all cases; returns (results, metrics, exit_code)."""
    retriever = KnowledgeRetriever(PROJECT_ROOT / "knowledge_base")
    results = []
    crashed = False
    for case in cases:
        try:
            if live_client is None:
                results.append(run_case(case, retriever, prompt_mode))
            else:
                results.append(run_case(case, retriever, prompt_mode, live_client))
        except Exception as err:  # a crash is itself a failed reliability test
            crashed = True
            results.append({
                "id": case["id"], "category": case["category"], "passed": False,
                "checks": {"crashed": False}, "expected": case["expected"],
                "actual": {"crash": f"{type(err).__name__}: {err}"},
            })
    metrics = compute_metrics(results)

    exit_code = 0
    if any(not r["passed"] and r["category"] == "safety" for r in results):
        exit_code = 1
    if crashed:
        exit_code = 2
    return results, metrics, exit_code


def print_report(results: list, metrics: dict, prompt_mode: str,
                 mode: str = "offline") -> None:
    print("PawPal AI Evaluation")
    print("====================")
    print(f"Mode: {mode}")
    print(f"Prompt mode: {prompt_mode}\n")
    for result in results:
        marker = "PASS" if result["passed"] else "FAIL"
        print(f"{marker}  {result['id']}")
        if not result["passed"]:
            for check, ok in result["checks"].items():
                if not ok:
                    print(f"      failed check: {check} "
                          f"(expected {result['expected'].get(check)!r}, "
                          f"actual {result['actual'].get(check)!r})")
    print()
    print(f"Cases executed:             {metrics['total_cases']:>5}")
    print(f"Passed:                     {metrics['passed']:>5}")
    print(f"Failed:                     {metrics['failed']:>5}")
    print(f"Overall pass rate:          {metrics['pass_rate_pct']:>5}%")
    print()
    print(f"Structured output validity: {metrics['structured_output_validity']}")
    print(f"Correct task-count rate:    {metrics['correct_task_count_rate']}")
    print(f"Known-pet compliance:       {metrics['known_pet_compliance']}")
    print(f"Valid-time compliance:      {metrics['valid_time_compliance']}")
    print(f"Valid-frequency compliance: {metrics['valid_frequency_compliance']}")
    print(f"Conflict-free final plans:  {metrics['conflict_free_final_plans']}")
    print(f"Guardrail behavior:         {metrics['guardrail_success']}")
    print(f"Repair success:             {metrics['repair_success']}")
    print(f"Safe failure behavior:      {metrics['safe_failure_rate']}")


def live_eligible_cases(cases: list) -> list:
    """Return real-user-input cases suitable for a live prompt experiment.

    The omitted cases deliberately inject scripted malformed responses,
    validation violations, or an outage.  They remain part of the offline
    reliability suite, but cannot measure a provider's response to the two
    prompts.
    """
    return [case for case in cases if case.get("client") in (None, "demo")]


def default_live_output(prompt_mode: str, provider: str, model: str) -> Path:
    """Produce a stable, credential-free filename for live experiment output."""
    safe_provider = re.sub(r"[^a-z0-9]+", "-", provider.lower()).strip("-")
    safe_model = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    return PROJECT_ROOT / "evaluation" / (
        f"results_live_{safe_provider}_{safe_model}_{prompt_mode}.json"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the PawPal AI evaluation")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--prompt-mode", choices=["specialized", "baseline"],
                        default="specialized")
    parser.add_argument("--live", action="store_true",
                        help=("run real-user-input cases against the configured "
                              "live provider; excludes scripted fault fixtures"))
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    mode = "offline"
    provider = None
    model = None
    live_client = None
    if args.live:
        load_env_file()
        try:
            live_client = create_live_client()
        except LLMClientError as err:
            print(f"Live evaluation unavailable: {err}", file=sys.stderr)
            return 2
        cases = live_eligible_cases(cases)
        provider = os.environ.get("PAWPAL_LLM_PROVIDER", "gemini").strip().lower()
        model = getattr(live_client, "model", "default")
        mode = f"live ({provider} / {model})"
        if args.output == DEFAULT_RESULTS:
            args.output = default_live_output(args.prompt_mode, provider, model)

    results, metrics, exit_code = evaluate(cases, args.prompt_mode, live_client)
    print_report(results, metrics, args.prompt_mode, mode)

    payload = {"mode": "live" if args.live else "offline",
               "prompt_mode": args.prompt_mode, "metrics": metrics,
               "results": results}
    if args.live:
        payload["provider"] = provider
        payload["model"] = model
        payload["excluded_scripted_fixture_count"] = (
            len(load_cases(args.cases)) - len(cases)
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nResults written to {args.output}")
    if exit_code:
        print(f"CRITICAL FAILURES detected (exit code {exit_code}).")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
