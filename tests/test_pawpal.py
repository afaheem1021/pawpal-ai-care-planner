"""Unit tests for the PawPal+ logic layer."""

import os
import sys

# Make pawpal_system.py importable no matter where pytest is run from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Pet, Task


def make_task(description="Morning walk"):
    """Build a valid Task so each test doesn't repeat the boilerplate."""
    return Task(
        description=description,
        pet_name="Biscuit",
        time="08:00",
        duration_mins=30,
        priority="high",
        frequency="daily",
    )


def test_mark_complete_changes_status():
    task = make_task()
    assert task.is_complete is False  # sanity: tasks start incomplete

    task.mark_complete()

    assert task.is_complete is True


def test_add_task_increases_task_count():
    pet = Pet(name="Biscuit", species="dog")
    assert len(pet.get_tasks()) == 0

    pet.add_task(make_task())

    assert len(pet.get_tasks()) == 1
