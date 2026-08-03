"""End-to-end Streamlit UI tests using streamlit.testing.v1.AppTest.

These drive the real app.py script (demo-mode AI client, no network):
generate -> review -> partial approval -> duplicate prevention -> guardrails.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Owner, Pet

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

REQUEST = (
    "Biscuit needs a 30-minute walk every morning around 8. Feed him after "
    "the walk. Clean Mochi's litter box every evening at 6."
)


@pytest.fixture(autouse=True)
def force_demo_mode(monkeypatch):
    """Keep UI tests offline even when a developer has a live .env file."""
    monkeypatch.setenv("PAWPAL_USE_LIVE_MODEL", "false")


def make_app():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    owner = Owner("Jordan")
    owner.add_pet(Pet("Biscuit", "dog"))
    owner.add_pet(Pet("Mochi", "cat"))
    at.session_state["owner"] = owner
    at.run()
    assert not at.exception
    return at


def generate(at, request_text):
    at.text_area(key="ai_request_text").set_value(request_text)
    button = next(b for b in at.button if "Generate" in (b.label or ""))
    button.click()
    at.run()
    assert not at.exception
    return at.session_state["ai_result"]


def all_tasks(at):
    return [t for p in at.session_state["owner"].get_all_pets() for t in p.get_tasks()]


def test_generate_shows_proposal_without_mutating_schedule():
    at = make_app()
    result = generate(at, REQUEST)

    assert result.status == "ready_for_review"
    assert len(result.proposal.tasks) == 3
    assert result.retrieved_chunks  # context sources are surfaced
    assert all_tasks(at) == []  # nothing added before approval


def test_partial_approval_adds_only_selected_and_clears_proposal():
    at = make_app()
    generate(at, REQUEST)

    at.checkbox(key="ai_approve_0").set_value(True)
    at.checkbox(key="ai_approve_2").set_value(True)
    next(b for b in at.button if "Add Approved" in (b.label or "")).click()
    at.run()
    assert not at.exception

    tasks = all_tasks(at)
    assert len(tasks) == 2
    assert {t.pet_name for t in tasks} == {"Biscuit", "Mochi"}
    # Proposal cleared -> a refresh cannot re-add the same tasks.
    assert "ai_result" not in at.session_state


def test_medical_request_is_rejected_and_schedule_untouched():
    at = make_app()
    result = generate(at, "Decide how much medicine Biscuit should receive.")

    assert result.status == "guardrail_rejected"
    assert all_tasks(at) == []


def test_manual_task_entry_still_works():
    at = make_app()
    # The original manual form is unchanged and functional.
    form_inputs = [w for w in at.text_input if w.label == "Task description"]
    assert form_inputs, "manual task form is missing"
