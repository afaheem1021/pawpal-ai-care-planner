"""Tests for the PawPal AI structured schemas."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_ai.schemas import (
    PlanProposal,
    SchemaError,
    TaskProposal,
    ValidationIssue,
    ValidationResult,
    WorkflowResult,
    WorkflowTraceEvent,
)


def valid_task_dict(**overrides):
    """A fully valid task-proposal dict; override fields per test."""
    data = {
        "pet_name": "Biscuit",
        "description": "Morning walk",
        "time": "08:00",
        "duration_mins": 30,
        "priority": "high",
        "frequency": "daily",
        "explanation": "Biscuit's profile lists a 30-minute morning walk.",
        "confidence": 0.9,
        "source_ids": ["pet_profiles.md#biscuit"],
    }
    data.update(overrides)
    return data


def test_valid_task_proposal_parses():
    task = TaskProposal.from_dict(valid_task_dict())
    assert task.pet_name == "Biscuit"
    assert task.duration_mins == 30
    assert task.confidence == 0.9
    assert task.source_ids == ["pet_profiles.md#biscuit"]


def test_missing_field_is_rejected():
    data = valid_task_dict()
    del data["time"]
    with pytest.raises(SchemaError, match="time"):
        TaskProposal.from_dict(data)


def test_wrong_type_is_rejected():
    with pytest.raises(SchemaError, match="duration_mins"):
        TaskProposal.from_dict(valid_task_dict(duration_mins="thirty"))
    # bool must not sneak in as an int
    with pytest.raises(SchemaError, match="duration_mins"):
        TaskProposal.from_dict(valid_task_dict(duration_mins=True))


def test_invalid_confidence_is_rejected():
    with pytest.raises(SchemaError, match="confidence"):
        TaskProposal.from_dict(valid_task_dict(confidence=1.5))
    with pytest.raises(SchemaError, match="confidence"):
        TaskProposal.from_dict(valid_task_dict(confidence=-0.1))


def test_integer_confidence_is_coerced_to_float():
    task = TaskProposal.from_dict(valid_task_dict(confidence=1))
    assert task.confidence == 1.0


def test_empty_description_is_rejected():
    with pytest.raises(SchemaError, match="description"):
        TaskProposal.from_dict(valid_task_dict(description=""))
    with pytest.raises(SchemaError, match="description"):
        TaskProposal.from_dict(valid_task_dict(description="   "))


def test_non_string_source_ids_are_rejected():
    with pytest.raises(SchemaError, match="source_ids"):
        TaskProposal.from_dict(valid_task_dict(source_ids=[1, 2]))


def test_plan_proposal_parses_and_serializes():
    plan = PlanProposal.from_dict(
        {
            "tasks": [valid_task_dict()],
            "missing_information": ["No time given for grooming"],
            "warnings": [],
        }
    )
    assert len(plan.tasks) == 1
    round_trip = plan.to_dict()
    assert round_trip["tasks"][0]["pet_name"] == "Biscuit"
    assert round_trip["missing_information"] == ["No time given for grooming"]
    # Re-parsing the serialized form yields the same content.
    assert PlanProposal.from_dict(round_trip).to_dict() == round_trip


def test_plan_proposal_requires_tasks_list():
    with pytest.raises(SchemaError, match="tasks"):
        PlanProposal.from_dict({"missing_information": [], "warnings": []})
    with pytest.raises(SchemaError):
        PlanProposal.from_dict({"tasks": "walk the dog"})


def test_plan_proposal_rejects_bad_nested_task():
    with pytest.raises(SchemaError):
        PlanProposal.from_dict({"tasks": [{"pet_name": "Biscuit"}]})


def test_validation_issue_serializes():
    issue = ValidationIssue(
        code="unknown_pet", message="No pet named Rex", severity="error", task_index=0
    )
    assert issue.to_dict() == {
        "code": "unknown_pet",
        "message": "No pet named Rex",
        "severity": "error",
        "task_index": 0,
    }


def test_validation_result_error_codes_ignore_warnings():
    result = ValidationResult(
        is_valid=False,
        valid_tasks=[],
        issues=[
            ValidationIssue("schedule_conflict", "overlap", "error", 0),
            ValidationIssue("owner_unavailable", "outside windows", "warning", 1),
        ],
    )
    assert result.error_codes() == ["schedule_conflict"]


def test_workflow_result_serializes():
    result = WorkflowResult(
        status="ready_for_review",
        proposal=PlanProposal(tasks=[TaskProposal.from_dict(valid_task_dict())]),
        validation=ValidationResult(is_valid=True),
        retrieved_chunks=[],
        repair_attempted=False,
        trace=[WorkflowTraceEvent("guardrails", "passed", "input accepted")],
        user_message="Ready for review.",
    )
    data = result.to_dict()
    assert data["status"] == "ready_for_review"
    assert data["proposal"]["tasks"][0]["description"] == "Morning walk"
    assert data["trace"][0]["step"] == "guardrails"
