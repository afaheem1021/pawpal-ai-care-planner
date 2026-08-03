"""Tests for the PawPal AI proposal validator."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Owner, Pet, Scheduler, Task
from pawpal_ai.schemas import PlanProposal, RetrievedChunk, TaskProposal
from pawpal_ai.validator import ProposalValidator


def make_world():
    owner = Owner("Faheem")
    owner.add_pet(Pet("Biscuit", "dog"))
    owner.add_pet(Pet("Mochi", "cat"))
    return owner, Scheduler(owner)


def make_chunks():
    return [
        RetrievedChunk("pet_profiles.md#biscuit", "pet_profiles.md", "Biscuit", "...", 0.9),
        RetrievedChunk("task_templates.md#walk", "task_templates.md", "Walk", "...", 0.5),
    ]


def make_proposal_task(**overrides):
    data = {
        "pet_name": "Biscuit",
        "description": "Morning walk",
        "time": "08:00",
        "duration_mins": 30,
        "priority": "high",
        "frequency": "daily",
        "explanation": "Requested by the owner.",
        "confidence": 0.9,
        "source_ids": ["pet_profiles.md#biscuit"],
    }
    data.update(overrides)
    return TaskProposal(**data)


def validate(tasks, owner=None, scheduler=None):
    if owner is None:
        owner, scheduler = make_world()
    validator = ProposalValidator()
    return validator.validate(PlanProposal(tasks=tasks), owner, scheduler, make_chunks())


def test_valid_task_passes():
    result = validate([make_proposal_task()])
    assert result.is_valid is True
    assert len(result.valid_tasks) == 1
    assert result.error_codes() == []


def test_unknown_pet_is_rejected():
    result = validate([make_proposal_task(pet_name="Rex")])
    assert result.is_valid is False
    assert "unknown_pet" in result.error_codes()
    assert result.valid_tasks == []


def test_invalid_time_is_rejected():
    for bad_time in ["8 AM", "25:00", "08:60", "8:00"]:
        result = validate([make_proposal_task(time=bad_time)])
        assert "invalid_time" in result.error_codes(), bad_time


def test_invalid_duration_is_rejected():
    result = validate([make_proposal_task(duration_mins=0)])
    assert "duration_out_of_range" in result.error_codes()
    result = validate([make_proposal_task(duration_mins=500)])
    assert "duration_out_of_range" in result.error_codes()


def test_unsupported_priority_is_rejected():
    result = validate([make_proposal_task(priority="urgent")])
    assert "invalid_priority" in result.error_codes()


def test_unsupported_frequency_is_rejected():
    result = validate([make_proposal_task(frequency="hourly")])
    assert "invalid_frequency" in result.error_codes()


def test_invalid_confidence_is_rejected():
    task = make_proposal_task()
    task.confidence = 1.7  # mutate past the schema boundary
    result = validate([task])
    assert "invalid_confidence" in result.error_codes()


def test_missing_explanation_is_rejected():
    task = make_proposal_task()
    task.explanation = "   "
    result = validate([task])
    assert "missing_explanation" in result.error_codes()


def test_unknown_source_id_is_rejected():
    result = validate([make_proposal_task(source_ids=["made_up.md#nope"])])
    assert "unknown_source_id" in result.error_codes()


def test_prohibited_medical_content_is_rejected():
    result = validate([make_proposal_task(description="Give 50mg dose of painkiller")])
    assert "prohibited_medical_content" in result.error_codes()


def test_duplicate_proposals_are_rejected():
    result = validate([make_proposal_task(), make_proposal_task()])
    assert "duplicate_proposal" in result.error_codes()
    assert len(result.valid_tasks) == 1  # the first copy survives


def test_too_many_tasks_is_rejected():
    tasks = [make_proposal_task(time=f"0{i}:00", description=f"Task {i}")
             for i in range(6)]
    result = validate(tasks)
    assert "too_many_tasks" in result.error_codes()
    assert result.is_valid is False


def test_conflict_with_existing_schedule():
    owner, scheduler = make_world()
    biscuit = owner.get_all_pets()[0]
    biscuit.add_task(Task("Existing walk", "", "08:00", 30, "high", "daily"))

    result = validate([make_proposal_task(time="08:15")], owner, scheduler)
    assert "schedule_conflict" in result.error_codes()
    assert result.valid_tasks == []


def test_proposal_vs_proposal_conflict():
    result = validate([
        make_proposal_task(description="Walk", time="08:00"),
        make_proposal_task(description="Feeding", time="08:10", duration_mins=10),
    ])
    assert "proposal_conflict" in result.error_codes()


def test_back_to_back_tasks_are_valid():
    result = validate([
        make_proposal_task(description="Walk", time="08:00", duration_mins=30),
        make_proposal_task(description="Feeding", time="08:30", duration_mins=10),
    ])
    assert result.is_valid is True
    assert len(result.valid_tasks) == 2


def test_task_construction_failure_is_caught():
    # Safety net: even if field checks pass, the original Task validation
    # remains the final boundary.
    with mock.patch("pawpal_ai.validator.Task", side_effect=ValueError("boom")):
        result = validate([make_proposal_task()])
    assert "task_construction_failed" in result.error_codes()
    assert result.valid_tasks == []


def test_outside_availability_is_warning_not_error():
    result = validate([make_proposal_task(time="12:00")])
    assert result.is_valid is True  # warning only
    codes = [issue.code for issue in result.issues]
    assert "owner_unavailable" in codes


def test_empty_proposal_with_no_tasks_is_valid():
    result = validate([])
    assert result.is_valid is True
    assert result.valid_tasks == []
