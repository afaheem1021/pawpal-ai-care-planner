"""PawPal+ pet care system.

Class skeletons generated from the UML diagram in diagrams/uml_draft.mmd.
"""

from dataclasses import dataclass, field


@dataclass
class Task:
    """A single care task for a pet (e.g., walk, feed, medicate)."""

    description: str
    pet_name: str
    time: str
    duration_mins: int
    priority: str
    frequency: str
    is_complete: bool = False

    def mark_complete(self):
        """Mark this task as completed."""
        pass


@dataclass
class Pet:
    """A pet with a list of care tasks."""

    name: str
    species: str
    tasks: list[Task] = field(default_factory=list)

    def add_task(self, task: Task):
        """Add a task to this pet's task list."""
        pass

    def get_tasks(self) -> list[Task]:
        """Return all tasks for this pet."""
        pass


@dataclass
class Owner:
    """A pet owner who can have many pets."""

    name: str
    pets: list[Pet] = field(default_factory=list)

    def add_pet(self, pet: Pet):
        """Add a pet to this owner's pet list."""
        pass

    def get_all_pets(self) -> list[Pet]:
        """Return all pets belonging to this owner."""
        pass


class Scheduler:
    """Manages an Owner's pets and builds daily care schedules."""

    def __init__(self, owner: Owner):
        self.owner = owner

    def get_todays_schedule(self) -> list[Task]:
        """Collect today's tasks across all of the owner's pets."""
        pass

    def sort_by_time(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by their scheduled time."""
        pass

    def sort_by_priority(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by priority (highest first)."""
        pass

    def check_conflicts(self, tasks: list[Task]) -> list[tuple[Task, Task]]:
        """Find pairs of tasks whose time windows overlap."""
        pass
