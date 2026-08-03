# AI Interactions Log

Operational traces from real runs of the PawPal AI workflow
(`python main.py --demo`, deterministic offline client — every trace below is
reproducible by running that command). The JSONL records are copied verbatim
from `logs/pawpal_ai.jsonl`. No private model reasoning is logged anywhere —
only structured operational events.

---

## Interaction 1: First-pass success

### User input

> Walk Biscuit every morning at 8 for 30 minutes and feed him afterward.

### Retrieved sources

- `pet_profiles.md#biscuit` (score 0.3242)
- `task_templates.md#feeding` (score 0.1989)
- `pet_profiles.md#mochi` (score 0.1638)
- `task_templates.md#walk` (score 0.1251)

### Initial proposal summary

Two tasks: `Walk` for Biscuit at 08:00 (30 min, high, daily, confidence 0.95)
and `Feeding` for Biscuit at 08:30 (10 min, high, confidence 0.80). The
feeding time was derived from "afterward" — walk end (08:00 + 30 min).

### Validator result

VALID — 2 valid tasks, 0 errors. No conflicts against the (empty) schedule.

### Repair action

None needed (`repair_attempted: false`).

### Final result

Status `ready_for_review`; message: *"2 task(s) are ready for your review.
Nothing is added until you approve."*

### Human action

Both tasks approved. `apply_approved_tasks` revalidated them and added 2 real
`Task` objects through `Pet.add_task`; they appear in
`Scheduler.get_todays_schedule()`.

---

## Interaction 2: Conflict and repair

### User input

> Give Biscuit enrichment play at 8:15 for 15 minutes.

(The schedule already contained the approved 08:00–08:30 walk and the
08:30–08:40 feeding from Interaction 1.)

### Retrieved sources

- `pet_profiles.md#mochi` (0.2623), `pet_profiles.md#biscuit` (0.2547),
  `task_templates.md#enrichment` (0.2281), `task_templates.md#feeding` (0.1833)

### Initial proposal summary

One task: `Enrichment play` for Biscuit at **08:15** (15 min, medium).

### Validator result

INVALID — `schedule_conflict`: the 08:15–08:30 window overlaps the existing
08:00–08:30 walk (detected by the original `Scheduler.check_conflicts`).

### Repair action

One repair attempt (the maximum). The repair prompt carried the issue code,
the busy windows (08:00–08:30, 08:30–08:40), and the allowed values. The
repaired proposal moved the task to **08:40** — the first free slot,
back-to-back with the feeding, which the scheduler correctly allows.

Verbatim log records:

```json
{"timestamp": "2026-08-02T21:52:01", "event": "repair_requested", "reason": "validation_failure"}
{"timestamp": "2026-08-02T21:52:01", "event": "repair_result", "succeeded": true}
{"timestamp": "2026-08-02T21:52:01", "event": "workflow_complete", "status": "ready_for_review", "retrieved_source_ids": ["pet_profiles.md#mochi", "pet_profiles.md#biscuit", "task_templates.md#enrichment", "task_templates.md#feeding"], "retrieval_scores": [0.2623, 0.2547, 0.2281, 0.1833], "proposed_task_count": 1, "validation_issue_codes": [], "repair_attempted": true, "trace_steps": ["receive_request:ok", "guardrails:passed", "retrieval:ok", "parse:ok", "validation:failed", "repair:requested", "repair:succeeded"]}
```

### Final result

Status `ready_for_review` with the repair disclosed: *"(One automatic repair
was applied - check the changes.)"*

### Human action

Repaired task approved and added. Final schedule (08:00 walk, 08:30 feeding,
08:40 enrichment) has **zero** conflict warnings.

---

## Interaction 3: Guardrail rejection (safe failure)

### User input

> Decide how much medicine Biscuit should receive.

### Retrieved sources

None — the guardrail fired before retrieval or any model call.

### Initial proposal summary

None. The request never reached the extraction model.

### Validator result

Not run (nothing to validate).

### Repair action

None — medical dosage requests are never repairable.

### Final result

Status `guardrail_rejected` (code `medical_dosage`); message: *"PawPal AI
cannot calculate or suggest medication dosages. It can only schedule a
medication routine your veterinarian has already prescribed. Please ask your
vet about dosing."*

Verbatim log records:

```json
{"timestamp": "2026-08-02T21:57:53", "event": "request_rejected", "guardrail_code": "medical_dosage"}
{"timestamp": "2026-08-02T21:57:53", "event": "workflow_complete", "status": "guardrail_rejected", "retrieved_source_ids": [], "retrieval_scores": [], "proposed_task_count": 0, "validation_issue_codes": [], "repair_attempted": false, "trace_steps": ["receive_request:ok", "guardrails:rejected"]}
```

### Human action

None possible — there was no proposal to approve, and the schedule was
untouched. Manual task entry remained fully usable.

---

## Agent workflow note (how this upgrade was built)

The Applied AI upgrade itself was implemented with an AI coding agent working
in phases (audit -> schemas -> retrieval -> guardrails -> clients -> prompts ->
validator -> workflow -> UI -> CLI -> evaluation -> docs), with the human
owner reviewing commits. Everything the agent produced was verified by
running the test suite (108 tests), the evaluation harness (19/19 cases), and
the Streamlit `AppTest` UI flows before each commit. See `model_card.md` for
a reflection including one accepted and one rejected AI suggestion.
