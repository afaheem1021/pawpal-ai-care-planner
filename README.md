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
rootdir: .../ai110-module2show-pawpal-starter
collected 12 items

tests/test_pawpal.py ............                                        [100%]

============================== 12 passed in 0.01s ==============================
```

**Confidence Level: ★★★★☆ (4/5)** — Every implemented behavior is covered by at least one test, including boundary conditions (back-to-back tasks) and failure paths (invalid input). The missing star: the Streamlit UI layer isn't automatically tested (it's verified manually), and recurrence is only tested one cycle ahead — long-running scenarios like a month of daily completions or real calendar-month recurrence aren't exercised.

## 📐 Smarter Scheduling

| Feature | Method(s) | Notes |
|---------|-----------|-------|
| Task sorting | `Scheduler.sort_by_time()`, `Scheduler.sort_by_priority()` | Time sorting parses `"HH:MM"` into minutes-since-midnight (via `Task.start_minutes()`) so `9:00` sorts before `10:00`; priority uses the `PRIORITY_ORDER` ranking (high → medium → low) instead of alphabetical order. |
| Filtering | `Scheduler.filter_by_pet()`, `Scheduler.filter_by_status()` | Narrow any task list to one pet's tasks, or to complete/incomplete tasks. `get_todays_schedule()` also filters out completed tasks and tasks not yet due. |
| Conflict handling | `Scheduler.check_conflicts()`, `Scheduler.conflict_warnings()` | Two tasks conflict when their time windows (`start` to `start + duration_mins`) overlap — including exact same-time tasks. `conflict_warnings()` returns readable warning strings instead of crashing. |
| Recurring tasks | `Scheduler.mark_task_complete()` | Completing a `daily`/`weekly`/`monthly` task auto-creates its next occurrence with `due_date = today + FREQUENCY_INTERVAL[frequency]` (using `timedelta`); `once` tasks simply complete. |

## 📸 Demo Walkthrough

Describe your app in numbered steps so a reader can follow along without watching a video:

1. <!-- Describe this step -->
2. <!-- Describe this step -->
3. <!-- Describe this step -->
4. <!-- Describe this step -->
5. <!-- Add more steps as needed -->

**Screenshot or video** *(optional)*: <!-- Insert a screenshot or link to a demo video here -->
