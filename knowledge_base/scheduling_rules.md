# Scheduling Rules

## Supported Values

- Supported priorities: `high`, `medium`, `low`
- Supported frequencies: `daily`, `weekly`, `monthly`, `once`
- Time format: 24-hour `HH:MM` (for example `08:00`, `18:30`)
- Duration: whole minutes, between 1 and 240
- Maximum AI-generated tasks per request: 5

## Conflicts

- Two tasks conflict when their time windows overlap.
  A task's window runs from its start time for `duration_mins` minutes.
- Back-to-back tasks are allowed: a task ending at 08:30 does not conflict
  with a task starting at 08:30.
- Exact same-time tasks always conflict.
- All tasks compete for the owner's time, even across different pets,
  because one person performs every task.

## Repair Policy

- When a proposal is invalid or conflicts with the schedule, the system may
  ask the model for at most ONE repair attempt.
- If the repaired proposal is still invalid, the system stops and reports
  the problem instead of retrying.

## Unknown Or Ambiguous Times

- If the owner does not give a time, the system must not invent one.
  The missing time goes into `missing_information` so the owner can decide.
- Vague times map to the owner's availability windows: "morning" means
  07:00-09:00 and "evening" means 17:00-21:00. Anything vaguer stays unresolved.

## Human Approval

- No AI-generated task is ever added to the schedule automatically.
- The owner reviews every proposal and approves tasks individually.
- Rejected or unapproved proposals are discarded without changing the schedule.

## Medical Limitation

- PawPal AI may schedule a routine the owner already knows
  (for example, a vet-prescribed pill the owner already gives daily).
- PawPal AI must NOT diagnose symptoms, select medication, or determine dosage.
- Emergencies are out of scope: the owner should contact a veterinarian or an
  emergency veterinary clinic immediately.
