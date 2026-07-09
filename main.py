"""Temporary testing ground for the PawPal+ logic layer."""

from pawpal_system import Owner, Pet, Scheduler, Task


def main():
    # 1. Create an owner and two pets
    owner = Owner("Faheem")
    biscuit = Pet("Biscuit", "dog")
    mochi = Pet("Mochi", "cat")
    owner.add_pet(biscuit)
    owner.add_pet(mochi)

    # 2. Add tasks with different times (pet_name is auto-set by add_task)
    biscuit.add_task(Task("Morning walk", "", "08:00", 30, "high", "daily"))
    biscuit.add_task(Task("Give heartworm pill", "", "08:15", 5, "high", "monthly"))
    mochi.add_task(Task("Refill water fountain", "", "07:30", 5, "medium", "daily"))
    mochi.add_task(Task("Clean litter box", "", "18:00", 10, "low", "daily"))

    # 3. Print today's schedule
    scheduler = Scheduler(owner)
    schedule = scheduler.get_todays_schedule()

    print(f"===== Today's Schedule for {owner.name}'s pets =====")
    for task in schedule:
        status = "x" if task.is_complete else " "
        print(f"[{status}] {task.time}  {task.pet_name:<8} {task.description}"
              f"  ({task.duration_mins} min, {task.priority} priority)")

    # 4. Bonus: surface any scheduling conflicts
    conflicts = scheduler.check_conflicts(schedule)
    if conflicts:
        print("\n⚠ Conflicts detected:")
        for first, second in conflicts:
            print(f"  - '{first.description}' ({first.time}, {first.duration_mins} min)"
                  f" overlaps '{second.description}' ({second.time})")
    else:
        print("\nNo scheduling conflicts.")


if __name__ == "__main__":
    main()
