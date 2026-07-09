"""PawPal+ pet care system.

Class skeletons generated from the UML diagram in diagrams/uml_draft.mmd.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

# Priority ranking used for sorting: lower number = more urgent.
# Alphabetical sorting of the raw strings would give high < low < medium.
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

VALID_FREQUENCIES = {"daily", "weekly", "monthly", "once"}

# How far ahead a recurring task's next occurrence is due.
# "monthly" is approximated as 30 days; "once" never recurs.
FREQUENCY_INTERVAL = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}

TIME_FORMAT = "%H:%M"  # 24-hour "HH:MM", e.g. "08:00"


@dataclass
class Task:
    """A single care task for a pet (e.g., walk, feed, medicate)."""

    description: str
    pet_name: str
    time: str  # 24-hour "HH:MM", e.g. "08:00"
    duration_mins: int
    priority: str  # one of PRIORITY_ORDER's keys
    frequency: str  # one of VALID_FREQUENCIES; drives recurrence on completion
    is_complete: bool = False
    due_date: date = field(default_factory=date.today)

    def __post_init__(self):
        """Reject malformed times and unknown priority/frequency values at creation."""
        datetime.strptime(self.time, TIME_FORMAT)  # raises ValueError if malformed
        if self.priority not in PRIORITY_ORDER:
            raise ValueError(f"priority must be one of {set(PRIORITY_ORDER)}, got {self.priority!r}")
        if self.frequency not in VALID_FREQUENCIES:
            raise ValueError(f"frequency must be one of {VALID_FREQUENCIES}, got {self.frequency!r}")

    def start_minutes(self) -> int:
        """This task's start time as minutes since midnight (safe to sort/compare)."""
        parsed = datetime.strptime(self.time, TIME_FORMAT)
        return parsed.hour * 60 + parsed.minute

    def mark_complete(self):
        """Mark this task as completed."""
        self.is_complete = True


@dataclass
class Pet:
    """A pet with a list of care tasks."""

    name: str
    species: str
    tasks: list[Task] = field(default_factory=list)

    def add_task(self, task: Task):
        """Add a task to this pet's task list, syncing its pet_name to this pet."""
        task.pet_name = self.name
        self.tasks.append(task)

    def get_tasks(self) -> list[Task]:
        """Return all tasks for this pet (a copy, so callers can't mutate our list)."""
        return list(self.tasks)


@dataclass
class Owner:
    """A pet owner who can have many pets."""

    name: str
    pets: list[Pet] = field(default_factory=list)

    def add_pet(self, pet: Pet):
        """Add a pet to this owner's pet list."""
        self.pets.append(pet)

    def get_all_pets(self) -> list[Pet]:
        """Return all pets belonging to this owner (a copy)."""
        return list(self.pets)

class Scheduler:
    """Manages an Owner's pets and builds daily care schedules."""

    def __init__(self, owner: Owner):
        """Create a scheduler that manages the given owner's pets and tasks."""
        self.owner = owner

    def get_todays_schedule(self) -> list[Task]:
        """Return incomplete tasks due today (or overdue), sorted by time.

        Completed tasks drop off the schedule; recurring tasks reappear
        because mark_task_complete() creates their next occurrence with a
        future due_date, which shows up here once that date arrives.
        """
        today = date.today()
        schedule = []
        for pet in self.owner.get_all_pets():
            for task in pet.get_tasks():
                if not task.is_complete and task.due_date <= today:
                    schedule.append(task)
        return self.sort_by_time(schedule)

    def filter_by_pet(self, tasks: list[Task], pet_name: str) -> list[Task]:
        """Return only the tasks belonging to the named pet."""
        return [task for task in tasks if task.pet_name == pet_name]

    def filter_by_status(self, tasks: list[Task], is_complete: bool = False) -> list[Task]:
        """Return only the tasks matching the given completion status."""
        return [task for task in tasks if task.is_complete == is_complete]

    def mark_task_complete(self, task: Task) -> Task | None:
        """Complete a task; recurring tasks spawn their next occurrence.

        The follow-up copy is due FREQUENCY_INTERVAL[frequency] from today
        and is added to the same pet's list. Returns that new Task, or
        None for one-off ("once") tasks.
        """
        task.mark_complete()
        interval = FREQUENCY_INTERVAL.get(task.frequency)
        if interval is None:
            return None
        next_task = replace(task, is_complete=False, due_date=date.today() + interval)
        for pet in self.owner.get_all_pets():
            if pet.name == task.pet_name:
                pet.add_task(next_task)
                break
        return next_task

    def sort_by_time(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by their scheduled time.

        Sorts on parsed minutes-since-midnight, not the raw string —
        string comparison would put "9:00" after "10:00".
        """
        return sorted(tasks, key=lambda task: task.start_minutes())

    def sort_by_priority(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by priority (highest first)."""
        return sorted(tasks, key=lambda task: PRIORITY_ORDER[task.priority])

    def check_conflicts(self, tasks: list[Task]) -> list[tuple[Task, Task]]:
        """Find pairs of tasks whose time windows overlap.

        A task's window is [start, start + duration_mins). With the list
        sorted by start time, a later task conflicts with an earlier one
        exactly when it starts before the earlier one ends.
        """
        conflicts = []
        ordered = self.sort_by_time(tasks)
        for i, earlier in enumerate(ordered):
            earlier_end = earlier.start_minutes() + earlier.duration_mins
            for later in ordered[i + 1:]:
                if later.start_minutes() < earlier_end:
                    conflicts.append((earlier, later))
        return conflicts

    def conflict_warnings(self, tasks: list[Task]) -> list[str]:
        """Return a human-readable warning string for each overlapping pair."""
        return [
            f"'{first.description}' ({first.pet_name}, {first.time}, "
            f"{first.duration_mins} min) overlaps '{second.description}' "
            f"({second.pet_name}, {second.time})"
            for first, second in self.check_conflicts(tasks)
        ]
