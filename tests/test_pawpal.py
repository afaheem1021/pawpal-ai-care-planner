"""Unit tests for the PawPal+ logic layer."""

import os
import sys
from datetime import date, timedelta

# Make pawpal_system.py importable no matter where pytest is run from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_system import Owner, Pet, Scheduler, Task


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


def make_scheduler_with_pet():
    """Build an Owner with one pet wired to a Scheduler."""
    owner = Owner("Faheem")
    pet = Pet(name="Biscuit", species="dog")
    owner.add_pet(pet)
    return Scheduler(owner), pet


def test_schedule_is_sorted_by_time():
    scheduler, pet = make_scheduler_with_pet()
    pet.add_task(Task("Evening walk", "", "19:00", 30, "medium", "daily"))
    pet.add_task(Task("Breakfast", "", "07:00", 10, "high", "daily"))
    pet.add_task(Task("Midday play", "", "12:30", 15, "low", "daily"))

    times = [t.time for t in scheduler.get_todays_schedule()]

    assert times == ["07:00", "12:30", "19:00"]


def test_filter_by_pet_returns_only_that_pets_tasks():
    scheduler, biscuit = make_scheduler_with_pet()
    mochi = Pet(name="Mochi", species="cat")
    scheduler.owner.add_pet(mochi)
    biscuit.add_task(make_task("Walk"))
    mochi.add_task(make_task("Litter box"))

    tasks = scheduler.get_todays_schedule()
    biscuit_tasks = scheduler.filter_by_pet(tasks, "Biscuit")

    assert [t.description for t in biscuit_tasks] == ["Walk"]


def test_completing_daily_task_spawns_next_occurrence():
    scheduler, pet = make_scheduler_with_pet()
    task = make_task()
    pet.add_task(task)

    next_task = scheduler.mark_task_complete(task)

    assert task.is_complete is True
    assert next_task.is_complete is False
    assert next_task.due_date == date.today() + timedelta(days=1)
    assert len(pet.get_tasks()) == 2  # original + tomorrow's copy


def test_completing_once_task_does_not_recur():
    scheduler, pet = make_scheduler_with_pet()
    task = Task("Vet visit", "", "10:00", 60, "high", "once")
    pet.add_task(task)

    assert scheduler.mark_task_complete(task) is None
    assert len(pet.get_tasks()) == 1


def test_same_time_tasks_are_flagged_as_conflict():
    scheduler, pet = make_scheduler_with_pet()
    pet.add_task(Task("Morning walk", "", "08:00", 30, "high", "daily"))
    pet.add_task(Task("Give pill", "", "08:00", 5, "high", "daily"))

    warnings = scheduler.conflict_warnings(scheduler.get_todays_schedule())

    assert len(warnings) == 1
    assert "Morning walk" in warnings[0] and "Give pill" in warnings[0]
