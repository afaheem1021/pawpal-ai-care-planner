"""Business-rule validation of AI proposals against the real PawPal system.

Nothing here trusts the model. Every proposed task is checked against the
owner's actual pets, the allowed value sets from `pawpal_system`, the
retrieved source ids, and finally the original deterministic boundaries:
`Task.__post_init__` construction and `Scheduler.check_conflicts`.
"""

from __future__ import annotations

import re
from typing import Optional

from pawpal_system import PRIORITY_ORDER, VALID_FREQUENCIES, Owner, Scheduler, Task

from .prompts import MAX_GENERATED_TASKS
from .schemas import (
    PlanProposal,
    TaskProposal,
    ValidationIssue,
    ValidationResult,
)

DURATION_MIN = 1
DURATION_MAX = 240

# Owner availability windows (minutes since midnight) from
# knowledge_base/owner_preferences.md. Tasks outside these produce a
# WARNING (flag for review), never a hard rejection.
AVAILABILITY_WINDOWS = [(7 * 60, 9 * 60), (17 * 60, 21 * 60)]

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Content the AI must never schedule: dosing decisions or diagnoses.
_PROHIBITED_MEDICAL_RE = re.compile(
    r"\bdosage\b|\bdose\b|\bmg\b|\bmilligrams?\b|\bdiagnos\w*\b|\bprescribe\b",
    re.IGNORECASE,
)


def _minutes(time_str: str) -> int:
    hours, mins = time_str.split(":")
    return int(hours) * 60 + int(mins)


class ProposalValidator:
    """Validates a PlanProposal against PawPal's deterministic rules."""

    def validate(
        self,
        proposal: PlanProposal,
        owner: Owner,
        scheduler: Scheduler,
        retrieved_chunks: list,
    ) -> ValidationResult:
        """Check every task; return valid tasks plus every issue found.

        Error-severity issues exclude a task from `valid_tasks`; warnings
        (like owner availability) are informational only.
        """
        issues: list = []
        known_pets = {pet.name for pet in owner.get_all_pets()}
        known_sources = {chunk.source_id for chunk in retrieved_chunks}

        if len(proposal.tasks) > MAX_GENERATED_TASKS:
            issues.append(ValidationIssue(
                "too_many_tasks",
                f"{len(proposal.tasks)} tasks proposed; the limit is {MAX_GENERATED_TASKS}.",
                "error",
            ))

        candidates = {}  # index -> (TaskProposal, constructed Task)
        seen_signatures = set()
        for index, task in enumerate(proposal.tasks[:MAX_GENERATED_TASKS]):
            task_issues = self._validate_fields(task, index, known_pets, known_sources)
            issues.extend(task_issues)

            signature = (task.pet_name.lower(), task.description.strip().lower(),
                         task.time, task.frequency)
            if signature in seen_signatures:
                issues.append(ValidationIssue(
                    "duplicate_proposal",
                    f"Task {index} duplicates an earlier proposed task "
                    f"({task.description!r} for {task.pet_name} at {task.time}).",
                    "error", index,
                ))
                continue
            seen_signatures.add(signature)

            if any(i.severity == "error" for i in task_issues):
                continue

            # Final deterministic boundary: the ORIGINAL Task validation.
            try:
                real_task = Task(
                    description=task.description.strip(),
                    pet_name=task.pet_name,
                    time=task.time,
                    duration_mins=task.duration_mins,
                    priority=task.priority,
                    frequency=task.frequency,
                )
            except (ValueError, TypeError) as err:
                issues.append(ValidationIssue(
                    "task_construction_failed",
                    f"Task {index} was rejected by PawPal's Task validation: {err}",
                    "error", index,
                ))
                continue
            candidates[index] = (task, real_task)

        issues.extend(self._check_conflicts(candidates, scheduler))

        error_indexes = {
            issue.task_index for issue in issues
            if issue.severity == "error" and issue.task_index is not None
        }
        plan_level_errors = [
            issue for issue in issues
            if issue.severity == "error" and issue.task_index is None
        ]
        valid_tasks = [
            task for index, (task, _) in sorted(candidates.items())
            if index not in error_indexes
        ]
        is_valid = not plan_level_errors and not error_indexes and bool(
            valid_tasks or not proposal.tasks
        )
        return ValidationResult(is_valid=is_valid, valid_tasks=valid_tasks, issues=issues)

    # ------------------------------------------------------------ field checks

    def _validate_fields(self, task: TaskProposal, index: int,
                         known_pets: set, known_sources: set) -> list:
        issues = []

        def error(code: str, message: str):
            issues.append(ValidationIssue(code, message, "error", index))

        if task.pet_name not in known_pets:
            error("unknown_pet",
                  f"Task {index}: no pet named {task.pet_name!r} exists "
                  f"(known: {', '.join(sorted(known_pets)) or 'none'}).")
        if not task.description.strip():
            error("empty_description", f"Task {index}: description is empty.")
        if not _TIME_RE.match(task.time):
            error("invalid_time",
                  f"Task {index}: time {task.time!r} is not 24-hour HH:MM.")
        if not isinstance(task.duration_mins, int) or isinstance(task.duration_mins, bool):
            error("invalid_duration",
                  f"Task {index}: duration must be an integer, got "
                  f"{task.duration_mins!r}.")
        elif not (DURATION_MIN <= task.duration_mins <= DURATION_MAX):
            error("duration_out_of_range",
                  f"Task {index}: duration {task.duration_mins} min is outside "
                  f"{DURATION_MIN}-{DURATION_MAX}.")
        if task.priority not in PRIORITY_ORDER:
            error("invalid_priority",
                  f"Task {index}: priority {task.priority!r} is not one of "
                  f"{sorted(PRIORITY_ORDER)}.")
        if task.frequency not in VALID_FREQUENCIES:
            error("invalid_frequency",
                  f"Task {index}: frequency {task.frequency!r} is not one of "
                  f"{sorted(VALID_FREQUENCIES)}.")
        if not (0.0 <= task.confidence <= 1.0):
            error("invalid_confidence",
                  f"Task {index}: confidence {task.confidence} is outside 0-1.")
        if not task.explanation.strip():
            error("missing_explanation", f"Task {index}: explanation is empty.")
        unknown_sources = [s for s in task.source_ids if s not in known_sources]
        if unknown_sources:
            error("unknown_source_id",
                  f"Task {index}: cites source id(s) not retrieved: "
                  f"{', '.join(unknown_sources)}.")
        if _PROHIBITED_MEDICAL_RE.search(f"{task.description} {task.explanation}"):
            error("prohibited_medical_content",
                  f"Task {index}: contains medical content PawPal AI must not "
                  "schedule (dosage/diagnosis/prescription).")

        # Owner availability: warning-severity, flags for review only.
        if _TIME_RE.match(task.time):
            start = _minutes(task.time)
            in_window = any(
                window_start <= start < window_end
                for window_start, window_end in AVAILABILITY_WINDOWS
            )
            if not in_window:
                issues.append(ValidationIssue(
                    "owner_unavailable",
                    f"Task {index}: {task.time} is outside the owner's usual "
                    "availability (07:00-09:00, 17:00-21:00) - review carefully.",
                    "warning", index,
                ))
        return issues

    # --------------------------------------------------------------- conflicts

    def _check_conflicts(self, candidates: dict, scheduler: Scheduler) -> list:
        """Run the ORIGINAL Scheduler.check_conflicts over existing + proposed.

        Proposal-vs-existing pairs get code `schedule_conflict`; proposal-vs-
        proposal pairs get `proposal_conflict`. Back-to-back tasks pass, and
        exact-time overlaps fail, exactly as in the original system.
        """
        if not candidates:
            return []
        existing = scheduler.get_todays_schedule()
        proposed_by_id = {id(real): index for index, (_, real) in candidates.items()}
        combined = existing + [real for _, real in candidates.values()]

        issues = []
        reported = set()
        for first, second in scheduler.check_conflicts(combined):
            first_index = proposed_by_id.get(id(first))
            second_index = proposed_by_id.get(id(second))
            if first_index is None and second_index is None:
                continue  # existing-vs-existing conflict: not the proposal's fault
            if first_index is not None and second_index is not None:
                # Proposal vs proposal: flag only the LATER task (`second` is
                # later after sort_by_time) so a repair moves one, not both.
                code = "proposal_conflict"
                detail = "another proposed task"
                flagged = [(second_index, first)]
            else:
                code = "schedule_conflict"
                detail = "an existing scheduled task"
                proposed_index = first_index if first_index is not None else second_index
                other = second if first_index is not None else first
                flagged = [(proposed_index, other)]
            for index, other in flagged:
                if (code, index) in reported:
                    continue
                reported.add((code, index))
                issues.append(ValidationIssue(
                    code,
                    f"Task {index} ({candidates[index][0].description!r} at "
                    f"{candidates[index][0].time}) overlaps {detail} "
                    f"({other.description!r}, {other.pet_name}, {other.time}, "
                    f"{other.duration_mins} min).",
                    "error", index,
                ))
        return issues

    # ------------------------------------------------------------ busy windows

    @staticmethod
    def busy_windows(scheduler: Scheduler, extra_tasks: Optional[list] = None) -> list:
        """Occupied [start, end) windows in minutes - fed to the repair prompt."""
        windows = []
        tasks = scheduler.get_todays_schedule() + list(extra_tasks or [])
        for task in tasks:
            start = task.start_minutes()
            windows.append({
                "start": start,
                "end": start + task.duration_mins,
                "description": task.description,
            })
        return sorted(windows, key=lambda w: w["start"])
