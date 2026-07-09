"""Temporary testing ground for the PawPal+ logic layer."""

from pawpal_system import Owner, Pet, Scheduler, Task


def print_tasks(title, tasks):
    print(f"\n===== {title} =====")
    if not tasks:
        print("(none)")
    for task in tasks:
        status = "x" if task.is_complete else " "
        print(f"[{status}] {task.time}  {task.pet_name:<8} {task.description}"
              f"  ({task.duration_mins} min, {task.priority} priority,"
              f" {task.frequency}, due {task.due_date})")


def main():
    # 1. Create an owner and two pets
    owner = Owner("Faheem")
    biscuit = Pet("Biscuit", "dog")
    mochi = Pet("Mochi", "cat")
    owner.add_pet(biscuit)
    owner.add_pet(mochi)

    # 2. Add tasks deliberately OUT of time order (pet_name is set by add_task)
    biscuit.add_task(Task("Evening walk", "", "19:00", 30, "medium", "daily"))
    biscuit.add_task(Task("Morning walk", "", "08:00", 30, "high", "daily"))
    mochi.add_task(Task("Clean litter box", "", "18:00", 10, "low", "daily"))
    mochi.add_task(Task("Refill water fountain", "", "07:30", 5, "medium", "daily"))
    # Same time as the morning walk -> should trigger a conflict warning
    biscuit.add_task(Task("Give heartworm pill", "", "08:00", 5, "high", "monthly"))

    scheduler = Scheduler(owner)

    # 3. Sorting: get_todays_schedule returns the tasks sorted by time
    schedule = scheduler.get_todays_schedule()
    print_tasks(f"Today's schedule for {owner.name}'s pets (sorted by time)", schedule)

    # 4. Conflict detection: two 08:00 tasks overlap
    warnings = scheduler.conflict_warnings(schedule)
    if warnings:
        print("\n⚠ Conflicts detected:")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("\nNo scheduling conflicts.")

    # 5. Filtering: by pet, then by completion status
    print_tasks("Only Biscuit's tasks", scheduler.filter_by_pet(schedule, "Biscuit"))

    # 6. Recurring tasks: completing a daily task spawns tomorrow's copy
    morning_walk = scheduler.filter_by_pet(schedule, "Biscuit")[0]
    next_walk = scheduler.mark_task_complete(morning_walk)
    print(f"\nCompleted '{morning_walk.description}' -> next occurrence due {next_walk.due_date}")

    print_tasks("Completed tasks",
                scheduler.filter_by_status([t for p in owner.get_all_pets() for t in p.get_tasks()],
                                           is_complete=True))
    print_tasks("Still on today's schedule", scheduler.get_todays_schedule())


if __name__ == "__main__":
    main()
