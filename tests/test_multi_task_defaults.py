"""Regression coverage for omitted durations in multi-task requests."""

from pathlib import Path

from pawpal_ai.demo_client import DemoLLMClient
from pawpal_ai.retriever import KnowledgeRetriever
from pawpal_ai.workflow import PawPalAIWorkflow
from pawpal_system import Owner, Pet, Scheduler


REQUEST = (
    "Ron needs a walk at 8 am and kitty needs a walk at 12 PM, and then "
    "ron needs a cleaning at 10am and kitty needs her cleaning at 12:45 PM"
)


def test_omitted_durations_use_defaults_and_work_hours_are_warnings():
    owner = Owner("Jordan")
    owner.add_pet(Pet("Ron", "dog"))
    owner.add_pet(Pet("Kitty", "cat"))
    retriever = KnowledgeRetriever(Path(__file__).parent.parent / "knowledge_base")

    result = PawPalAIWorkflow(retriever, DemoLLMClient()).run(
        REQUEST, owner, Scheduler(owner)
    )

    assert result.status == "ready_for_review"
    assert result.proposal.missing_information == []
    assert [task.pet_name for task in result.proposal.tasks] == [
        "Ron", "Kitty", "Ron", "Kitty"
    ]
    assert [task.time for task in result.proposal.tasks] == [
        "08:00", "12:00", "10:00", "12:45"
    ]
    assert [task.duration_mins for task in result.proposal.tasks] == [30, 30, 15, 15]
    assert sum(
        issue.code == "owner_unavailable" for issue in result.validation.issues
    ) == 3
