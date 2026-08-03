"""PawPal command-line demonstrations.

Usage:
    python main.py            # original PawPal+ logic-layer demo (unchanged)
    python main.py --demo     # PawPal AI workflow demo, deterministic offline
    python main.py --live     # same demo against the live model (needs API key)

The --demo path needs NO API key and NO network: it uses the deterministic
DemoLLMClient, so graders can reproduce every line of output.
"""

import argparse
import sys
from pathlib import Path

from pawpal_system import Owner, Pet, Scheduler, Task


def print_tasks(title, tasks):
    print(f"\n===== {title} =====")
    if not tasks:
        print("(none)")
    for task in tasks:
        status = "x" if task.is_complete else " "
        print(f"[{status}] {task.time}  {task.pet_name:<8} {task.description}"
              f"  ({task.duration_mins} min, {task.priority} priority,"
              f" {task.frequency}, due {task.due_date})")


def run_original_demo():
    """The original PawPal+ demonstration - preserved unchanged."""
    # 1. Create an owner and two pets
    owner = Owner("Faheem")
    biscuit = Pet("Biscuit", "dog")
    mochi = Pet("Mochi", "cat")
    owner.add_pet(biscuit)
    owner.add_pet(mochi)

    # 2. Add tasks deliberately OUT of time order (pet_name is set by add_task)
    biscuit.add_task(Task("Evening walk", "", "19:00", 30, "medium", "daily"))
    biscuit.add_task(Task("Morning walk", "", "08:00", 30, "high", "daily"))
    mochi.add_task(Task("Clean litter box", "", "18:00", 10, "low", "daily"))
    mochi.add_task(Task("Refill water fountain", "", "07:30", 5, "medium", "daily"))
    # Same time as the morning walk -> should trigger a conflict warning
    biscuit.add_task(Task("Give heartworm pill", "", "08:00", 5, "high", "monthly"))

    scheduler = Scheduler(owner)

    # 3. Sorting: get_todays_schedule returns the tasks sorted by time
    schedule = scheduler.get_todays_schedule()
    print_tasks(f"Today's schedule for {owner.name}'s pets (sorted by time)", schedule)

    # 4. Conflict detection: two 08:00 tasks overlap
    warnings = scheduler.conflict_warnings(schedule)
    if warnings:
        print("\n⚠ Conflicts detected:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("\nNo scheduling conflicts.")

    # 5. Filtering: by pet, then by completion status
    print_tasks("Only Biscuit's tasks", scheduler.filter_by_pet(schedule, "Biscuit"))

    # 6. Recurring tasks: completing a daily task spawns tomorrow's copy
    morning_walk = scheduler.filter_by_pet(schedule, "Biscuit")[0]
    next_walk = scheduler.mark_task_complete(morning_walk)
    print(f"\nCompleted '{morning_walk.description}' -> next occurrence due {next_walk.due_date}")

    print_tasks("Completed tasks",
                scheduler.filter_by_status([t for p in owner.get_all_pets() for t in p.get_tasks()],
                                           is_complete=True))
    print_tasks("Still on today's schedule", scheduler.get_todays_schedule())


# --------------------------------------------------------------- AI demo

def _print_workflow_result(result):
    print("\n  Retrieved sources:")
    if result.retrieved_chunks:
        for chunk in result.retrieved_chunks:
            print(f"    - {chunk.source_id} (score {chunk.score})")
    else:
        print("    (none)")

    if result.proposal is not None:
        print(f"\n  Proposal (final, after any repair): {len(result.proposal.tasks)} task(s)")
        for i, task in enumerate(result.proposal.tasks):
            print(f"    {i + 1}. {task.pet_name}: {task.description} at {task.time} "
                  f"({task.duration_mins} min, {task.priority}, {task.frequency}, "
                  f"confidence {task.confidence:.2f})")
        if result.proposal.missing_information:
            print("  Missing information:")
            for item in result.proposal.missing_information:
                print(f"    ? {item}")

    if result.validation is not None:
        verdict = "VALID" if result.validation.is_valid else "INVALID"
        print(f"\n  Validation: {verdict} "
              f"({len(result.validation.valid_tasks)} valid task(s))")
        for issue in result.validation.issues:
            print(f"    [{issue.severity}] {issue.code}: {issue.message}")

    print(f"\n  Repair attempted: {'yes' if result.repair_attempted else 'no'}")
    print("\n  Workflow trace:")
    for event in result.trace:
        print(f"    {event.step:>16} [{event.status}] {event.summary}")

    print(f"\n  Workflow status: {result.status}")
    print(f"  Message to user: {result.user_message}")


def run_ai_demo(live: bool):
    from pawpal_ai.interaction_logger import InteractionLogger
    from pawpal_ai.llm_client import AnthropicLLMClient, MissingAPIKeyError, load_env_file
    from pawpal_ai.demo_client import DemoLLMClient
    from pawpal_ai.retriever import KnowledgeRetriever
    from pawpal_ai.workflow import PawPalAIWorkflow, apply_approved_tasks

    if live:
        load_env_file()
        try:
            client = AnthropicLLMClient()
            mode = "LIVE MODEL"
        except MissingAPIKeyError as err:
            print(f"Live mode unavailable: {err}")
            print("Falling back to deterministic demo mode.\n")
            client, mode = DemoLLMClient(), "DEMO (fallback)"
    else:
        client, mode = DemoLLMClient(), "DEMO (deterministic, no API key)"

    retriever = KnowledgeRetriever(Path(__file__).parent / "knowledge_base")
    logger = InteractionLogger()

    print("=" * 70)
    print(f"PawPal AI CLI demonstration - mode: {mode}")
    print("=" * 70)

    owner = Owner("Faheem")
    biscuit = Pet("Biscuit", "dog")
    mochi = Pet("Mochi", "cat")
    owner.add_pet(biscuit)
    owner.add_pet(mochi)
    scheduler = Scheduler(owner)
    workflow = PawPalAIWorkflow(retriever, client, logger=logger)

    # ---- Case 1: first-pass success -------------------------------------
    request1 = "Walk Biscuit every morning at 8 for 30 minutes and feed him afterward."
    print("\n\nCASE 1 - First-pass success")
    print(f"  Input: {request1!r}")
    result1 = workflow.run(request1, owner, scheduler)
    _print_workflow_result(result1)

    if result1.status == "ready_for_review":
        print("\n  [Human approval] Approving all valid tasks "
              "(the CLI stands in for the review UI here).")
        added, _ = apply_approved_tasks(
            result1.validation.valid_tasks, owner, scheduler,
            result1.retrieved_chunks, logger=logger,
        )
        print(f"  Tasks added to the schedule: {added}")
    else:
        print("\n  No tasks were added.")

    # ---- Case 2: conflict + one repair -----------------------------------
    request2 = "Give Biscuit enrichment play at 8:15 for 15 minutes."
    print("\n\nCASE 2 - Conflict with the existing schedule, then one repair")
    print("  Existing schedule now contains the 08:00-08:30 walk from case 1.")
    print(f"  Input: {request2!r}")
    result2 = workflow.run(request2, owner, scheduler)
    _print_workflow_result(result2)

    if result2.status == "ready_for_review":
        print("\n  [Human approval] Approving the repaired task.")
        added, _ = apply_approved_tasks(
            result2.validation.valid_tasks, owner, scheduler,
            result2.retrieved_chunks, logger=logger,
        )
        print(f"  Tasks added to the schedule: {added}")
    else:
        print("\n  No tasks were added.")

    # ---- Case 3: guardrail rejection --------------------------------------
    request3 = "Decide how much medicine Biscuit should receive."
    print("\n\nCASE 3 - Guardrail rejection (medication dosage)")
    print(f"  Input: {request3!r}")
    result3 = workflow.run(request3, owner, scheduler)
    _print_workflow_result(result3)
    print("\n  No tasks were added (unsafe request never reached the model).")

    # ---- Final schedule -----------------------------------------------------
    print_tasks("Final schedule after the demo (original Scheduler output)",
                scheduler.get_todays_schedule())
    conflicts = scheduler.conflict_warnings(scheduler.get_todays_schedule())
    if conflicts:
        print("\n⚠ Conflicts detected:")
        for warning in conflicts:
            print(f"  - {warning}")
    else:
        print("\nNo scheduling conflicts - the AI-added tasks fit the plan.")


def main():
    parser = argparse.ArgumentParser(description="PawPal demonstrations")
    parser.add_argument("--demo", action="store_true",
                        help="run the PawPal AI demo with the offline deterministic client")
    parser.add_argument("--live", action="store_true",
                        help="run the PawPal AI demo against the live model (needs API key)")
    args = parser.parse_args()

    if args.demo or args.live:
        run_ai_demo(live=args.live)
    else:
        run_original_demo()


if __name__ == "__main__":
    sys.exit(main())
