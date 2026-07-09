# PawPal+ (Module 2 Project)

You are building **PawPal+**, a Streamlit app that helps a pet owner plan care tasks for their pet.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

## What you will build

Your final app should:

- Let a user enter basic owner + pet info
- Let a user add/edit tasks (duration + priority at minimum)
- Generate a daily schedule/plan based on constraints and priorities
- Display the plan clearly (and ideally explain the reasoning)
- Include tests for the most important scheduling behaviors

## ✨ Features

- **Time-sorted daily schedule** — tasks from every pet are merged into one plan, sorted chronologically by parsing `"HH:MM"` times into minutes (so 9:00 correctly comes before 10:00).
- **Priority ranking** — tasks can also be ordered high → medium → low using an explicit ranking instead of alphabetical order.
- **Filtering** — view the schedule for a single pet, or split tasks by complete/incomplete status.
- **Conflict warnings** — overlapping time windows (start + duration) are detected and reported as plain-English warnings, including exact same-time tasks; back-to-back tasks are correctly allowed.
- **Recurring tasks** — completing a `daily`, `weekly`, or `monthly` task automatically schedules its next occurrence (today + 1 day, + 7 days, or + 30 days); `once` tasks simply complete.
- **Due-date awareness** — completed and future-dated tasks stay off today's schedule, so the plan always shows exactly what's left to do today.
- **Input validation** — malformed times, unknown priorities, and unknown frequencies are rejected when a task is created, with clear error messages surfaced in the UI.

## Getting started

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Suggested workflow

1. Read the scenario carefully and identify requirements and edge cases.
2. Draft a UML diagram (classes, attributes, methods, relationships).
3. Convert UML into Python class stubs (no logic yet).
4. Implement scheduling logic in small increments.
5. Add tests to verify key behaviors.
6. Connect your logic to the Streamlit UI in `app.py`.
7. Refine UML so it matches what you actually built.

## 🖥️ Sample Output

Paste a sample of your app's CLI or Streamlit output here so a reader can see what a generated plan looks like:

===== Today's schedule for Faheem's pets (sorted by time) =====
[ ] 07:30  Mochi    Refill water fountain  (5 min, medium priority, daily, due 2026-07-09)
[ ] 08:00  Biscuit  Morning walk  (30 min, high priority, daily, due 2026-07-09)
[ ] 08:00  Biscuit  Give heartworm pill  (5 min, high priority, monthly, due 2026-07-09)
[ ] 18:00  Mochi    Clean litter box  (10 min, low priority, daily, due 2026-07-09)
[ ] 19:00  Biscuit  Evening walk  (30 min, medium priority, daily, due 2026-07-09)

⚠ Conflicts detected:
  - 'Morning walk' (Biscuit, 08:00, 30 min) overlaps 'Give heartworm pill' (Biscuit, 08:00)

Completed 'Morning walk' -> next occurrence due 2026-07-10

## 🧪 Testing PawPal+

```bash
# Run the full test suite:
python -m pytest

# Run with per-test detail:
python -m pytest -v
```

**What the tests cover** (12 tests in `tests/test_pawpal.py`):

- **Core behaviors** — marking a task complete flips its status; adding a task grows the pet's list.
- **Sorting correctness** — `get_todays_schedule()` returns tasks in chronological order, even when added out of order.
- **Filtering** — `filter_by_pet()` returns only the named pet's tasks.
- **Recurrence logic** — completing a daily task creates a copy due tomorrow, weekly recurs in exactly 7 days, and `"once"` tasks don't recur.
- **Conflict detection** — two same-time tasks are flagged with a warning; back-to-back tasks (one ending exactly when the next starts) are correctly *not* flagged.
- **Edge cases & validation** — an owner with no pets (or a pet with no tasks) yields an empty schedule without crashing; future-dated tasks stay off today's schedule; malformed times, priorities, and frequencies raise `ValueError` at creation.

Successful test run:

```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: faheem@Ahmeds-MacBook-Pro ai110-module2show-pawpal-starter
collected 12 items

tests/test_pawpal.py ............                                        [100%]

============================== 12 passed in 0.01s ==============================
```

**Confidence Level: 4/5 ** — all the behaviors that were implemented were tested, feeling confident, but not everthing can be perfect. 

## 📐 Smarter Scheduling

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | `Scheduler.sort_by_time()`, `Scheduler.sort_by_priority()` | Time sorting parses `"HH:MM"` into minutes-since-midnight (via `Task.start_minutes()`) so `9:00` sorts before `10:00`; priority uses the `PRIORITY_ORDER` ranking (high → medium → low) instead of alphabetical order. |
| Filtering | `Scheduler.filter_by_pet()`, `Scheduler.filter_by_status()` | Narrow any task list to one pet's tasks, or to complete/incomplete tasks. `get_todays_schedule()` also filters out completed tasks and tasks not yet due. |
| Conflict handling | `Scheduler.check_conflicts()`, `Scheduler.conflict_warnings()` | Two tasks conflict when their time windows (`start` to `start + duration_mins`) overlap — including exact same-time tasks. `conflict_warnings()` returns readable warning strings instead of crashing. |
| Recurring tasks | `Scheduler.mark_task_complete()` | Completing a `daily`/`weekly`/`monthly` task auto-creates its next occurrence with `due_date = today + FREQUENCY_INTERVAL[frequency]` (using `timedelta`); `once` tasks simply complete. |

## 📸 Demo Walkthrough

Launch the app with `streamlit run app.py` (with your virtual environment active).

**Main UI features:**

- **Owner section** — set the owner's name (stored once in `st.session_state`, so data survives page interactions).
- **Pets section** — a form to add pets by name and species; duplicate names are rejected.
- **Tasks section** — a form to add tasks (description, time picker, duration, priority, frequency) to a chosen pet, plus an "All tasks" table showing every task with its due date and completion status.
- **Today's Schedule** — a live, time-sorted view of what's left to do today, with a pet filter dropdown, automatic conflict banners, a **Done ✅** button on every row, and an expander listing completed tasks.

**Example workflow:**

1. Enter your name in **Owner name**.
2. Add a pet — e.g., *Biscuit (dog)* — then a second, *Mochi (cat)*.
3. Add a task for Biscuit: *Morning walk*, 08:00, 30 min, high priority, daily.
4. Add a second Biscuit task at the same time: *Give heartworm pill*, 08:00, 5 min — the **Today's Schedule** section immediately shows a yellow warning that the two tasks overlap, suggesting one be moved.
5. Add Mochi's tasks (e.g., *Refill water fountain* at 07:30) and watch the schedule interleave both pets' tasks in time order.
6. Use the **Show tasks for** dropdown to filter the schedule down to one pet.
7. Click **Done ✅** on the morning walk — a green message confirms completion and announces the next occurrence (tomorrow, since it's a daily task). The walk moves to the *Completed tasks* expander, and tomorrow's copy waits off-screen until its due date.

**Key Scheduler behaviors shown:** time sorting (`sort_by_time`), pet/status filtering (`filter_by_pet`, `filter_by_status`), overlap-based conflict warnings (`conflict_warnings`), and automatic recurrence (`mark_task_complete`).

The same logic can be exercised without the UI by running `python main.py`:

```
===== Today's schedule for Faheem's pets (sorted by time) =====
[ ] 07:30  Mochi    Refill water fountain  (5 min, medium priority, daily, due 2026-07-09)
[ ] 08:00  Biscuit  Morning walk  (30 min, high priority, daily, due 2026-07-09)
[ ] 08:00  Biscuit  Give heartworm pill  (5 min, high priority, monthly, due 2026-07-09)
[ ] 18:00  Mochi    Clean litter box  (10 min, low priority, daily, due 2026-07-09)
[ ] 19:00  Biscuit  Evening walk  (30 min, medium priority, daily, due 2026-07-09)

⚠ Conflicts detected:
  - 'Morning walk' (Biscuit, 08:00, 30 min) overlaps 'Give heartworm pill' (Biscuit, 08:00)

===== Only Biscuit's tasks =====
[ ] 08:00  Biscuit  Morning walk  (30 min, high priority, daily, due 2026-07-09)
[ ] 08:00  Biscuit  Give heartworm pill  (5 min, high priority, monthly, due 2026-07-09)
[ ] 19:00  Biscuit  Evening walk  (30 min, medium priority, daily, due 2026-07-09)

Completed 'Morning walk' -> next occurrence due 2026-07-10

===== Completed tasks =====
[x] 08:00  Biscuit  Morning walk  (30 min, high priority, daily, due 2026-07-09)

===== Still on today's schedule =====
[ ] 07:30  Mochi    Refill water fountain  (5 min, medium priority, daily, due 2026-07-09)
[ ] 08:00  Biscuit  Give heartworm pill  (5 min, high priority, monthly, due 2026-07-09)
[ ] 18:00  Mochi    Clean litter box  (10 min, low priority, daily, due 2026-07-09)
[ ] 19:00  Biscuit  Evening walk  (30 min, medium priority, daily, due 2026-07-09)
```

**Screenshot or video** *(optional)*: <!-- Insert a screenshot or link to a demo video here -->
