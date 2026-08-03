"""Structured data models for the PawPal AI pipeline.

Everything that crosses a boundary in the AI workflow (model output, retrieval
results, validation verdicts, workflow traces) is represented by one of these
dataclasses instead of an untyped dict. `from_dict()` constructors validate at
the boundary and raise `SchemaError` with a clear message, so malformed model
output is rejected before it can reach the scheduler.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


class SchemaError(ValueError):
    """Raised when data fails structural validation at a schema boundary."""


def _require(data: dict, key: str, expected: type, context: str) -> Any:
    """Return data[key], raising SchemaError if missing or the wrong type."""
    if key not in data:
        raise SchemaError(f"{context}: missing required field {key!r}")
    value = data[key]
    # bool is a subclass of int; a True duration should still be rejected.
    if expected is int and isinstance(value, bool):
        raise SchemaError(f"{context}: field {key!r} must be an integer, got bool")
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)  # accept ints where floats are expected (e.g. confidence 1)
    if not isinstance(value, expected):
        raise SchemaError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _require_str_list(data: dict, key: str, context: str) -> list:
    """Return data[key] as a list of strings, raising SchemaError otherwise."""
    value = _require(data, key, list, context)
    for item in value:
        if not isinstance(item, str):
            raise SchemaError(
                f"{context}: every item in {key!r} must be a string, "
                f"got {type(item).__name__}"
            )
    return value


@dataclass
class RetrievedChunk:
    """One section of the knowledge base returned by the retriever."""

    source_id: str
    source_file: str
    section: str
    text: str
    score: float

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return asdict(self)


@dataclass
class TaskProposal:
    """A single AI-proposed care task, prior to validation and approval."""

    pet_name: str
    description: str
    time: str  # 24-hour "HH:MM"
    duration_mins: int
    priority: str
    frequency: str
    explanation: str
    confidence: float
    source_ids: list = field(default_factory=list)

    def __post_init__(self):
        """Reject structurally impossible values at construction time."""
        if not self.description or not self.description.strip():
            raise SchemaError("TaskProposal: description must be a non-empty string")
        if not (0.0 <= self.confidence <= 1.0):
            raise SchemaError(
                f"TaskProposal: confidence must be between 0 and 1, got {self.confidence}"
            )

    @classmethod
    def from_dict(cls, data: dict) -> "TaskProposal":
        """Build a TaskProposal from parsed JSON, validating fields and types."""
        if not isinstance(data, dict):
            raise SchemaError(f"TaskProposal: expected an object, got {type(data).__name__}")
        context = "TaskProposal"
        return cls(
            pet_name=_require(data, "pet_name", str, context),
            description=_require(data, "description", str, context),
            time=_require(data, "time", str, context),
            duration_mins=_require(data, "duration_mins", int, context),
            priority=_require(data, "priority", str, context),
            frequency=_require(data, "frequency", str, context),
            explanation=_require(data, "explanation", str, context),
            confidence=_require(data, "confidence", float, context),
            source_ids=_require_str_list(data, "source_ids", context),
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return asdict(self)


@dataclass
class PlanProposal:
    """The complete structured plan returned by the extraction model."""

    tasks: list = field(default_factory=list)  # list[TaskProposal]
    missing_information: list = field(default_factory=list)  # list[str]
    warnings: list = field(default_factory=list)  # list[str]

    @classmethod
    def from_dict(cls, data: dict) -> "PlanProposal":
        """Build a PlanProposal from parsed JSON, validating every task."""
        if not isinstance(data, dict):
            raise SchemaError(f"PlanProposal: expected an object, got {type(data).__name__}")
        raw_tasks = _require(data, "tasks", list, "PlanProposal")
        tasks = [TaskProposal.from_dict(item) for item in raw_tasks]
        missing = _require_str_list(data, "missing_information", "PlanProposal") \
            if "missing_information" in data else []
        warnings = _require_str_list(data, "warnings", "PlanProposal") \
            if "warnings" in data else []
        return cls(tasks=tasks, missing_information=missing, warnings=warnings)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "tasks": [task.to_dict() for task in self.tasks],
            "missing_information": list(self.missing_information),
            "warnings": list(self.warnings),
        }


@dataclass
class ValidationIssue:
    """One problem the validator found with a proposed plan."""

    code: str
    message: str
    severity: str  # "error" (blocks the task) or "warning" (informational)
    task_index: Optional[int] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return asdict(self)


@dataclass
class ValidationResult:
    """Outcome of validating a PlanProposal against PawPal business rules."""

    is_valid: bool
    valid_tasks: list = field(default_factory=list)  # list[TaskProposal]
    issues: list = field(default_factory=list)  # list[ValidationIssue]

    def error_codes(self) -> list:
        """Return the codes of error-severity issues (ignoring warnings)."""
        return [issue.code for issue in self.issues if issue.severity == "error"]

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "is_valid": self.is_valid,
            "valid_tasks": [task.to_dict() for task in self.valid_tasks],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class WorkflowTraceEvent:
    """One structured operational trace entry emitted by the workflow.

    These record *what happened* (step, status, summary) — never private
    model reasoning.
    """

    step: str
    status: str
    summary: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return asdict(self)


@dataclass
class WorkflowResult:
    """Everything the UI needs after one run of the AI workflow.

    No tasks have been added to the schedule when this is returned; the
    proposal is pending explicit human approval.
    """

    status: str
    proposal: Optional[PlanProposal]
    validation: Optional[ValidationResult]
    retrieved_chunks: list = field(default_factory=list)  # list[RetrievedChunk]
    repair_attempted: bool = False
    trace: list = field(default_factory=list)  # list[WorkflowTraceEvent]
    user_message: str = ""

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return {
            "status": self.status,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "validation": self.validation.to_dict() if self.validation else None,
            "retrieved_chunks": [chunk.to_dict() for chunk in self.retrieved_chunks],
            "repair_attempted": self.repair_attempted,
            "trace": [event.to_dict() for event in self.trace],
            "user_message": self.user_message,
        }
