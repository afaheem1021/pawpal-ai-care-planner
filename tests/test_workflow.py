"""Tests for the PawPal AI multi-step workflow (fake clients only, no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Owner, Pet, Scheduler, Task
from pawpal_ai.llm_client import FakeLLMClient, NetworkError
from pawpal_ai.schemas import RetrievedChunk, TaskProposal
from pawpal_ai.workflow import (
    MAX_REPAIR_ATTEMPTS,
    PawPalAIWorkflow,
    apply_approved_tasks,
)

CHUNKS = [
    RetrievedChunk("pet_profiles.md#biscuit", "pet_profiles.md", "Biscuit", "dog info", 0.9),
    RetrievedChunk("scheduling_rules.md#conflicts", "scheduling_rules.md", "Conflicts",
                   "overlap rules", 0.4),
]


class StubRetriever:
    """Returns a fixed chunk list; can be told to explode."""

    def __init__(self, chunks=None, raise_error=False):
        self.chunks = CHUNKS if chunks is None else chunks
        self.raise_error = raise_error

    def retrieve(self, query):
        if self.raise_error:
            raise RuntimeError("index unavailable")
        return self.chunks


def make_world(with_conflict_task=False):
    owner = Owner("Faheem")
    biscuit = Pet("Biscuit", "dog")
    owner.add_pet(biscuit)
    owner.add_pet(Pet("Mochi", "cat"))
    if with_conflict_task:
        biscuit.add_task(Task("Existing walk", "", "08:00", 30, "high", "daily"))
    return owner, Scheduler(owner)


def task_dict(**overrides):
    data = {
        "pet_name": "Biscuit",
        "description": "Morning walk",
        "time": "08:00",
        "duration_mins": 30,
        "priority": "high",
        "frequency": "daily",
        "explanation": "Owner requested a morning walk.",
        "confidence": 0.9,
        "source_ids": ["pet_profiles.md#biscuit"],
    }
    data.update(overrides)
    return data


def plan(tasks, missing=None, warnings=None):
    return {"tasks": tasks, "missing_information": missing or [],
            "warnings": warnings or []}


def run_workflow(client, request="Walk Biscuit at 8 for 30 minutes.",
                 retriever=None, world=None):
    owner, scheduler = world or make_world()
    workflow = PawPalAIWorkflow(retriever or StubRetriever(), client)
    return workflow.run(request, owner, scheduler), owner, scheduler


def total_task_count(owner):
    return sum(len(pet.get_tasks()) for pet in owner.get_all_pets())


def test_first_pass_success():
    client = FakeLLMClient([plan([task_dict()])])
    result, owner, _ = run_workflow(client)

    assert result.status == "ready_for_review"
    assert result.repair_attempted is False
    assert len(result.validation.valid_tasks) == 1
    assert len(client.calls) == 1
    assert total_task_count(owner) == 0  # nothing added without approval


def test_conflict_then_successful_repair():
    world = make_world(with_conflict_task=True)
    conflicting = plan([task_dict(time="08:15", description="Second walk")])
    repaired = plan([task_dict(time="08:30", description="Second walk")])
    client = FakeLLMClient([conflicting, repaired])

    result, owner, _ = run_workflow(client, world=world)

    assert result.status == "ready_for_review"
    assert result.repair_attempted is True
    assert result.validation.valid_tasks[0].time == "08:30"
    assert len(client.calls) == 2
    assert "REPAIR REQUEST" in client.calls[1][1]
    assert total_task_count(owner) == 1  # only the pre-existing task


def test_invalid_output_then_successful_repair():
    client = FakeLLMClient([
        {"tasks": "not a list"},  # fails schema parse
        plan([task_dict()]),
    ])
    result, _, _ = run_workflow(client)

    assert result.status == "ready_for_review"
    assert result.repair_attempted is True
    assert len(client.calls) == 2


def test_repair_still_invalid_fails_safely():
    world = make_world(with_conflict_task=True)
    conflicting = plan([task_dict(time="08:15")])
    client = FakeLLMClient([conflicting, conflicting])  # repair doesn't help

    result, owner, _ = run_workflow(client, world=world)

    assert result.status == "validation_failed"
    assert result.repair_attempted is True
    assert total_task_count(owner) == 1  # schedule unchanged


def test_only_one_repair_attempt_is_made():
    assert MAX_REPAIR_ATTEMPTS == 1
    world = make_world(with_conflict_task=True)
    conflicting = plan([task_dict(time="08:15")])
    client = FakeLLMClient([conflicting, conflicting, conflicting])

    result, _, _ = run_workflow(client, world=world)

    assert len(client.calls) == 2  # initial + exactly one repair
    assert result.status == "validation_failed"


def test_unrepairable_issue_skips_repair():
    client = FakeLLMClient([plan([task_dict(pet_name="Rex")])])
    result, _, _ = run_workflow(client)

    assert result.status == "validation_failed"
    assert result.repair_attempted is False
    assert len(client.calls) == 1  # no repair for unknown pets


def test_empty_input_is_guardrail_rejected():
    client = FakeLLMClient([plan([task_dict()])])
    result, owner, _ = run_workflow(client, request="   ")

    assert result.status == "guardrail_rejected"
    assert len(client.calls) == 0  # never reached the model
    assert total_task_count(owner) == 0


def test_unknown_pet_request_is_guardrail_rejected():
    client = FakeLLMClient([plan([task_dict()])])
    result, _, _ = run_workflow(client, request="Walk Rex at 8 every morning.")

    assert result.status == "guardrail_rejected"
    assert len(client.calls) == 0


def test_medical_request_is_guardrail_rejected():
    client = FakeLLMClient([plan([task_dict()])])
    result, owner, _ = run_workflow(
        client, request="Decide how much medicine Biscuit should receive."
    )

    assert result.status == "guardrail_rejected"
    assert "veterinar" in result.user_message.lower() or \
        "vet" in result.user_message.lower()
    assert len(client.calls) == 0
    assert total_task_count(owner) == 0


def test_model_exception_fails_safely():
    client = FakeLLMClient([NetworkError("connection refused")])
    result, owner, _ = run_workflow(client)

    assert result.status == "model_error"
    assert "manual" in result.user_message.lower()
    assert "connection refused" in result.user_message.lower()
    assert total_task_count(owner) == 0


def test_retriever_exception_continues_without_context():
    client = FakeLLMClient([plan([task_dict(source_ids=[])])])
    result, _, _ = run_workflow(client, retriever=StubRetriever(raise_error=True))

    assert result.status == "ready_for_review"
    assert result.retrieved_chunks == []


def test_no_retrieved_context_still_works():
    client = FakeLLMClient([plan([task_dict(source_ids=[])])])
    result, _, _ = run_workflow(client, retriever=StubRetriever(chunks=[]))

    assert result.status == "ready_for_review"


def test_missing_information_status():
    client = FakeLLMClient([plan([], missing=["What time should grooming happen?"])])
    result, _, _ = run_workflow(client, request="Schedule grooming for Biscuit.")

    assert result.status == "needs_user_information"
    assert "grooming" in result.user_message.lower()


def test_trace_records_workflow_steps():
    client = FakeLLMClient([plan([task_dict()])])
    result, _, _ = run_workflow(client)

    steps = [event.step for event in result.trace]
    assert "guardrails" in steps
    assert "retrieval" in steps
    assert "validation" in steps


# ------------------------------------------------------------- approval

def approved_proposal(**overrides):
    return TaskProposal(**task_dict(**overrides))


def test_apply_approved_tasks_adds_real_tasks():
    owner, scheduler = make_world()
    added, result = apply_approved_tasks(
        [approved_proposal()], owner, scheduler, CHUNKS
    )

    assert added == 1
    assert result.is_valid is True
    biscuit = owner.get_all_pets()[0]
    tasks = biscuit.get_tasks()
    assert len(tasks) == 1
    assert isinstance(tasks[0], Task)
    assert tasks[0].time == "08:00"
    # the new task participates in the ORIGINAL scheduler
    assert tasks[0] in scheduler.get_todays_schedule()


def test_partial_approval_adds_only_selected():
    owner, scheduler = make_world()
    added, _ = apply_approved_tasks(
        [approved_proposal(description="Walk only")], owner, scheduler, CHUNKS
    )
    assert added == 1
    assert total_task_count(owner) == 1


def test_approval_revalidates_conflicts_and_adds_nothing():
    owner, scheduler = make_world(with_conflict_task=True)
    added, result = apply_approved_tasks(
        [approved_proposal(time="08:10")], owner, scheduler, CHUNKS
    )

    assert added == 0
    assert result.is_valid is False
    assert "schedule_conflict" in result.error_codes()
    assert total_task_count(owner) == 1  # unchanged


def test_approval_rejects_edited_invalid_task():
    owner, scheduler = make_world()
    bad = approved_proposal()
    bad.time = "26:00"  # user edited the field to something invalid
    added, result = apply_approved_tasks([bad], owner, scheduler, CHUNKS)

    assert added == 0
    assert total_task_count(owner) == 0
