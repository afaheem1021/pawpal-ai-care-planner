"""The multi-step PawPal AI workflow: guardrails -> retrieval -> extraction
-> validation -> conflict detection -> one repair attempt -> human review.

The workflow NEVER mutates the schedule. It returns a `WorkflowResult` whose
proposal is pending explicit human approval; only `apply_approved_tasks()`
(called after the user approves) creates real PawPal `Task` objects, and it
revalidates first.
"""

from __future__ import annotations

from typing import Optional

from pawpal_system import Owner, Scheduler, Task

from . import guardrails
from .interaction_logger import InteractionLogger
from .llm_client import LLMClientError
from .prompts import (
    BASELINE_SYSTEM_PROMPT,
    SPECIALIZED_SYSTEM_PROMPT,
    build_repair_prompt,
    build_user_prompt,
    parse_plan_response,
)
from .schemas import (
    PlanProposal,
    SchemaError,
    ValidationResult,
    WorkflowResult,
    WorkflowTraceEvent,
)
from .validator import ProposalValidator

MAX_REPAIR_ATTEMPTS = 1

# Issue codes a single controlled repair attempt may try to fix. Anything
# else (unknown pets, medical content, structurally missing information)
# is NOT repairable - the workflow fails safely instead.
REPAIRABLE_CODES = {
    "schedule_conflict",
    "proposal_conflict",
    "invalid_time",
    "invalid_frequency",
    "invalid_priority",
    "invalid_duration",
    "duration_out_of_range",
    "invalid_confidence",
    "unknown_source_id",
    "duplicate_proposal",
}

STATUS_READY = "ready_for_review"
STATUS_NEEDS_INFO = "needs_user_information"
STATUS_GUARDRAIL = "guardrail_rejected"
STATUS_MODEL_ERROR = "model_error"
STATUS_VALIDATION_FAILED = "validation_failed"


class PawPalAIWorkflow:
    """Orchestrates one natural-language request end to end."""

    def __init__(self, retriever, client, validator: Optional[ProposalValidator] = None,
                 logger: Optional[InteractionLogger] = None,
                 prompt_mode: str = "specialized"):
        """Wire the workflow's collaborators.

        `prompt_mode` is "specialized" (production) or "baseline" (only for
        the prompt-comparison experiment).
        """
        self.retriever = retriever
        self.client = client
        self.validator = validator or ProposalValidator()
        self.logger = logger or InteractionLogger(enabled=False)
        self.prompt_mode = prompt_mode

    # ------------------------------------------------------------------ run

    def run(self, request: str, owner: Owner, scheduler: Scheduler) -> WorkflowResult:
        """Process one request; returns a result awaiting human review.

        Never raises for model/retrieval failures and never mutates the
        owner, pets, or schedule.
        """
        trace: list = []

        def step(name: str, status: str, summary: str, **metadata):
            trace.append(WorkflowTraceEvent(name, status, summary, metadata))

        step("receive_request", "ok", f"Request received ({len(request or '')} chars)")

        # 1. Input guardrails ------------------------------------------------
        pet_names = [pet.name for pet in owner.get_all_pets()]
        gate = guardrails.check_request(request, pet_names)
        if not gate.allowed:
            step("guardrails", "rejected", gate.message, code=gate.code)
            result = WorkflowResult(
                status=STATUS_GUARDRAIL, proposal=None, validation=None,
                retrieved_chunks=[], repair_attempted=False, trace=trace,
                user_message=gate.message,
            )
            self.logger.log_event("request_rejected", guardrail_code=gate.code)
            self.logger.log_workflow_result(result)
            return result
        step("guardrails", "passed", "Input accepted", code=gate.code)

        # 2. Retrieval --------------------------------------------------------
        chunks = []
        try:
            query = self._build_retrieval_query(request, owner, scheduler)
            chunks = self.retriever.retrieve(query)
            step("retrieval", "ok",
                 f"Retrieved {len(chunks)} context chunk(s)",
                 source_ids=[c.source_id for c in chunks])
        except Exception as err:  # retrieval must never sink the workflow
            step("retrieval", "failed",
                 f"Retrieval failed ({err}); continuing without context")
        self.logger.log_event(
            "context_retrieved",
            source_ids=[c.source_id for c in chunks],
            scores=[c.score for c in chunks],
        )

        # 3. Generation -------------------------------------------------------
        system_prompt = (SPECIALIZED_SYSTEM_PROMPT if self.prompt_mode == "specialized"
                         else BASELINE_SYSTEM_PROMPT)
        existing = scheduler.get_todays_schedule()
        user_prompt = build_user_prompt(request, owner.get_all_pets(), existing, chunks)

        repair_attempted = False
        proposal: Optional[PlanProposal] = None
        raw_failure: Optional[str] = None
        try:
            raw = self.client.generate_structured(system_prompt, user_prompt)
        except LLMClientError as err:
            return self._model_error(trace, chunks, step, err)

        try:
            proposal = parse_plan_response(raw)
            step("parse", "ok", f"Parsed proposal with {len(proposal.tasks)} task(s)")
        except SchemaError as err:
            step("parse", "failed", f"Model output failed schema validation: {err}")
            raw_failure = f"{raw!r} -> {err}"

        # 4. Validation + at most one repair ----------------------------------
        validation: Optional[ValidationResult] = None
        if proposal is not None:
            validation = self.validator.validate(proposal, owner, scheduler, chunks)
            step("validation",
                 "ok" if validation.is_valid else "failed",
                 f"{len(validation.valid_tasks)} valid task(s), "
                 f"{len(validation.error_codes())} error(s)",
                 issue_codes=[i.code for i in validation.issues])
            self.logger.log_event(
                "proposal_validated",
                proposed_task_count=len(proposal.tasks),
                valid_task_count=len(validation.valid_tasks),
                issue_codes=[i.code for i in validation.issues],
            )

        needs_repair = raw_failure is not None or (
            validation is not None and not validation.is_valid
        )
        if needs_repair and self._repair_allowed(validation, raw_failure):
            repair_attempted = True
            step("repair", "requested",
                 "One repair attempt requested",
                 reason="parse_failure" if raw_failure else "validation_failure")
            self.logger.log_event(
                "repair_requested",
                reason="parse_failure" if raw_failure else "validation_failure",
            )
            try:
                proposal, validation = self._attempt_repair(
                    request, owner, scheduler, chunks, proposal, validation,
                    raw_failure, system_prompt,
                )
                repaired_ok = validation is not None and validation.is_valid
                step("repair", "succeeded" if repaired_ok else "failed",
                     "Repaired proposal is valid" if repaired_ok
                     else "Repaired proposal is still invalid")
                self.logger.log_event("repair_result", succeeded=repaired_ok)
            except LLMClientError as err:
                return self._model_error(trace, chunks, step, err,
                                         repair_attempted=True)
            except SchemaError as err:
                step("repair", "failed", f"Repaired output still malformed: {err}")
                self.logger.log_event("repair_result", succeeded=False)
                result = WorkflowResult(
                    status=STATUS_MODEL_ERROR, proposal=None, validation=None,
                    retrieved_chunks=chunks, repair_attempted=True, trace=trace,
                    user_message=(
                        "The AI returned malformed output twice, so no proposal "
                        "could be built. Your schedule was not changed - you can "
                        "still add tasks manually."
                    ),
                )
                self.logger.log_workflow_result(result)
                return result

        # 5. Final status -------------------------------------------------------
        result = self._finalize(trace, chunks, proposal, validation,
                                repair_attempted, raw_failure)
        self.logger.log_workflow_result(result)
        return result

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _build_retrieval_query(request: str, owner: Owner,
                               scheduler: Scheduler) -> str:
        """Request text plus pet names/species and a few task descriptions."""
        parts = [request]
        for pet in owner.get_all_pets():
            parts.append(f"{pet.name} {pet.species}")
        parts.extend(t.description for t in scheduler.get_todays_schedule()[:5])
        return " ".join(parts)

    def _repair_allowed(self, validation: Optional[ValidationResult],
                        raw_failure: Optional[str]) -> bool:
        """Repair only parse failures or issues that are all repairable."""
        if MAX_REPAIR_ATTEMPTS < 1:
            return False
        if raw_failure is not None:
            return True
        if validation is None:
            return False
        codes = set(validation.error_codes())
        return bool(codes) and codes <= REPAIRABLE_CODES

    def _attempt_repair(self, request, owner, scheduler, chunks, proposal,
                        validation, raw_failure, system_prompt):
        """Run the single controlled repair round-trip and revalidate."""
        error_issues = [i for i in validation.issues if i.severity == "error"] \
            if validation else []
        # Busy windows = existing schedule + the proposal's still-valid tasks,
        # so a rescheduled task can't land on either.
        valid_real_tasks = []
        if validation:
            for task in validation.valid_tasks:
                try:
                    valid_real_tasks.append(Task(
                        description=task.description, pet_name=task.pet_name,
                        time=task.time, duration_mins=task.duration_mins,
                        priority=task.priority, frequency=task.frequency,
                    ))
                except (ValueError, TypeError):
                    continue
        windows = self.validator.busy_windows(scheduler, valid_real_tasks)

        prompt = build_repair_prompt(
            request, proposal, error_issues, windows,
            owner.get_all_pets(), chunks, raw_output=raw_failure,
        )
        raw = self.client.generate_structured(system_prompt, prompt)
        repaired = parse_plan_response(raw)
        revalidation = self.validator.validate(repaired, owner, scheduler, chunks)
        return repaired, revalidation

    def _model_error(self, trace, chunks, step, err, repair_attempted=False):
        step("model", "failed", f"Model call failed: {err}",
             error_type=type(err).__name__)
        result = WorkflowResult(
            status=STATUS_MODEL_ERROR, proposal=None, validation=None,
            retrieved_chunks=chunks, repair_attempted=repair_attempted,
            trace=trace,
            user_message=(
                "The live AI model could not generate a proposal. "
                f"Details: {err}. Your schedule was not changed - manual task "
                "entry still works."
            ),
        )
        self.logger.log_event("model_error", error_type=type(err).__name__)
        self.logger.log_workflow_result(result)
        return result

    def _finalize(self, trace, chunks, proposal, validation,
                  repair_attempted, raw_failure) -> WorkflowResult:
        if proposal is None:
            return WorkflowResult(
                status=STATUS_MODEL_ERROR, proposal=None, validation=None,
                retrieved_chunks=chunks, repair_attempted=repair_attempted,
                trace=trace,
                user_message=(
                    "The AI returned output PawPal could not understand, so no "
                    "proposal was built. Your schedule was not changed."
                ),
            )
        if validation is not None and not validation.is_valid:
            problems = ", ".join(sorted(set(validation.error_codes()))) or "unknown"
            return WorkflowResult(
                status=STATUS_VALIDATION_FAILED, proposal=proposal,
                validation=validation, retrieved_chunks=chunks,
                repair_attempted=repair_attempted, trace=trace,
                user_message=(
                    f"The proposal failed validation ({problems})"
                    + (" even after one repair attempt" if repair_attempted else "")
                    + ". No tasks were added; review the issues below or add "
                    "tasks manually."
                ),
            )
        if not validation or not validation.valid_tasks:
            details = "; ".join(proposal.missing_information + proposal.warnings) \
                or "The request did not yield any schedulable task."
            return WorkflowResult(
                status=STATUS_NEEDS_INFO, proposal=proposal, validation=validation,
                retrieved_chunks=chunks, repair_attempted=repair_attempted,
                trace=trace,
                user_message=f"PawPal AI needs more information: {details}",
            )
        message = (
            f"{len(validation.valid_tasks)} task(s) are ready for your review."
            " Nothing is added until you approve."
        )
        if repair_attempted:
            message += " (One automatic repair was applied - check the changes.)"
        if proposal.missing_information:
            message += " Open questions: " + "; ".join(proposal.missing_information)
        return WorkflowResult(
            status=STATUS_READY, proposal=proposal, validation=validation,
            retrieved_chunks=chunks, repair_attempted=repair_attempted,
            trace=trace, user_message=message,
        )


# -------------------------------------------------------------- approval

def apply_approved_tasks(approved_tasks: list, owner: Owner, scheduler: Scheduler,
                         retrieved_chunks: list,
                         validator: Optional[ProposalValidator] = None,
                         logger: Optional[InteractionLogger] = None):
    """Convert human-approved TaskProposals into real PawPal Tasks.

    Revalidates (including conflicts) before touching any state; if
    revalidation fails, NOTHING is added. Returns (added_count, result).
    """
    validator = validator or ProposalValidator()
    logger = logger or InteractionLogger(enabled=False)
    result = validator.validate(
        PlanProposal(tasks=list(approved_tasks)), owner, scheduler, retrieved_chunks
    )
    if not result.is_valid or not result.valid_tasks:
        logger.log_event("approval_rejected",
                         issue_codes=[i.code for i in result.issues])
        return 0, result

    pets_by_name = {pet.name: pet for pet in owner.get_all_pets()}
    added = 0
    for task in result.valid_tasks:
        pet = pets_by_name.get(task.pet_name)
        if pet is None:  # revalidation guarantees this, but stay safe
            continue
        pet.add_task(Task(
            description=task.description.strip(), pet_name=task.pet_name,
            time=task.time, duration_mins=task.duration_mins,
            priority=task.priority, frequency=task.frequency,
        ))
        added += 1
    logger.log_event("tasks_approved", approved_count=len(approved_tasks),
                     added_count=added)
    return added, result
