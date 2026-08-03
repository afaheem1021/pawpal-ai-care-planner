# PawPal AI

**A reliable natural-language pet-care scheduling agent** — the Applied AI
final-project upgrade of the completed **PawPal+** scheduler.

A pet owner types something like:

> Biscuit needs a 30-minute walk every morning around 8. Feed him after the
> walk. Clean Mochi's litter box every evening at 6.

PawPal AI validates the request, retrieves custom PawPal context, extracts
structured task proposals with a specialized model prompt, validates every
field against the original deterministic scheduler's rules, detects
conflicts, performs at most **one** controlled repair, and then waits for the
human to approve tasks **individually** before anything touches the schedule.

## Project Summary

- **Base:** PawPal+, a working OOP pet-care management and scheduling system
  (kept fully intact — the AI never bypasses it).
- **Upgrade:** an AI proposal pipeline (guardrails → retrieval → extraction →
  validation → repair → human approval) in the `pawpal_ai/` package, wired
  into the existing Streamlit app, CLI, tests, and docs.
- **Reproducible without an API key:** a deterministic offline demo client
  powers the CLI demo, the Streamlit demo mode, all 107 unit tests, and the
  19-case evaluation harness.

## Original Base Project

### Original Goal

PawPal+ (Module 2 project) is a Streamlit app that helps a busy pet owner
plan care tasks — track walks, feeding, meds, grooming; respect time,
priority, and owner constraints; and produce a clear daily plan.

### Original Capabilities

All of this existed **before** the AI upgrade and still works unchanged
(`pawpal_system.py`: `Owner`, `Pet`, `Task`, `Scheduler`):

- Time-sorted daily schedule (parses `"HH:MM"` into minutes, so 9:00 < 10:00)
- Priority ranking (high → medium → low) and pet/status filtering
- Conflict detection on overlapping time windows, with back-to-back tasks
  correctly allowed and same-time tasks flagged
- Recurring tasks (daily/weekly/monthly spawn their next occurrence on
  completion; `once` simply completes)
- Due-date awareness and validation of times/priorities/frequencies at task
  creation (`Task.__post_init__`)
- Streamlit UI (add pets/tasks, today's schedule, Done buttons) and a CLI
  demo (`python main.py`), covered by the original 12 unit tests

## What the Final Project Adds

- **Natural-language task extraction** into typed `TaskProposal` objects
- **Custom multi-source retrieval (RAG)** over a PawPal knowledge base
- **Specialized structured prompting** with few-shot examples + a baseline
  prompt for comparison
- **Schema validation** at every boundary (malformed model output is rejected)
- **Business-rule + conflict validation** that reuses the original
  `Task.__post_init__` and `Scheduler.check_conflicts` as the final authority
- **One controlled repair attempt** when a proposal is invalid or conflicting
- **Human-in-the-loop approval** — per-task checkboxes, editable fields,
  revalidation on apply
- **Input guardrails** (empty/too-long input, unknown pets, medical dosage /
  diagnosis / emergencies, rule-override attempts)
- **Structured operational tracing** to `logs/pawpal_ai.jsonl`
- **Automated evaluation harness** (`evaluate.py`, 19 cases)

## Key AI Features

| Feature | Where |
|---|---|
| Guardrails | `pawpal_ai/guardrails.py` |
| TF-IDF retrieval over 4 knowledge files | `pawpal_ai/retriever.py`, `knowledge_base/` |
| Specialized + baseline prompts, repair prompt | `pawpal_ai/prompts.py` |
| Provider-agnostic LLM client (Gemini REST adapter, Anthropic adapter, fake, offline demo) | `pawpal_ai/llm_client.py`, `pawpal_ai/demo_client.py` |
| Typed schemas with boundary validation | `pawpal_ai/schemas.py` |
| Business/conflict validator | `pawpal_ai/validator.py` |
| Multi-step workflow with 1-repair policy | `pawpal_ai/workflow.py` |
| JSONL operational tracing | `pawpal_ai/interaction_logger.py` |
| Evaluation harness | `evaluate.py`, `evaluation/cases.json` |

## How the Workflow Works

```text
Natural-language request
        ↓
Input guardrails            (reject unsafe/empty/unknown-pet requests, no model call)
        ↓
Custom context retrieval    (TF-IDF over knowledge_base/*.md, stable source ids)
        ↓
Specialized AI extraction   (live Gemini/Anthropic model OR deterministic demo client)
        ↓
Structured task proposal    (strict JSON → TaskProposal dataclasses)
        ↓
Schema & business validation (pets exist, HH:MM, 1–240 min, allowed values,
        ↓                     source ids retrieved, no medical content, ≤5 tasks)
Existing PawPal conflict detection (the ORIGINAL Scheduler.check_conflicts)
        ↓
≤ 1 repair attempt          (only for repairable issues; never for unknown
        ↓                     pets, medical content, or missing information)
Human review & approval     (editable fields, per-task checkboxes)
        ↓
Existing PawPal task creation (revalidate → Task(...) → Pet.add_task)
        ↓
Updated daily schedule      (Scheduler.get_todays_schedule, unchanged)
```

## System Architecture

Mermaid source: [`diagrams/architecture.mmd`](diagrams/architecture.mmd)
(drawn from the implemented code — every box names its module). The original
class design is in [`diagrams/uml_final.mmd`](diagrams/uml_final.mmd).

Key design decision: the LLM can only *propose*. The original deterministic
system remains the source of truth for task validation, sorting, recurrence,
conflict detection, and storage — approved proposals are converted into
ordinary `Task` objects through the same `Pet.add_task` path the manual form
uses.

## Repository Structure

```text
├── app.py                    # Streamlit UI: original features + AI assistant
├── main.py                   # original CLI demo + `--demo` / `--live` AI demo
├── pawpal_system.py          # ORIGINAL deterministic logic layer (unchanged)
├── evaluate.py               # evaluation harness
├── pawpal_ai/                # the AI upgrade package
│   ├── schemas.py  retriever.py  guardrails.py  llm_client.py
│   ├── demo_client.py  prompts.py  validator.py  workflow.py
│   └── interaction_logger.py
├── knowledge_base/           # pet_profiles / owner_preferences /
│                             # scheduling_rules / task_templates (.md)
├── evaluation/               # cases.json, results.json, results_baseline.json
├── tests/                    # 107 tests (original 12 preserved)
├── diagrams/                 # architecture.mmd, uml_final.mmd
├── logs/                     # runtime JSONL traces (gitignored)
├── .env.example              # config template (no secrets committed)
├── model_card.md             # model card + AI-collaboration reflection
└── ai_interactions.md        # committed operational traces
```

## Knowledge Base and Retrieval

Four Markdown sources are split at `##` headings into chunks with stable ids
(`pet_profiles.md#biscuit`, `scheduling_rules.md#conflicts`, …) and indexed
with a small pure-Python TF-IDF/cosine implementation — deterministic, zero
extra dependencies, appropriate for four local files (a hosted vector DB
would be overkill). The retriever handles empty queries, missing
directories, top-k limits, and optional per-file filtering; proposals may
only cite source ids that were actually retrieved (enforced by the
validator).

## Specialized Prompting

Two modes (`pawpal_ai/prompts.py`):

- **Baseline** (experiment only): `"Convert this request into pet-care tasks
  and return JSON."`
- **Specialized** (production): role, exact JSON schema, allowed
  priorities/frequencies, HH:MM format, 5-task limit, medical boundaries,
  missing-information behavior, source-id citation rules, relative-ordering
  rule, confidence calibration — plus **four few-shot examples** (single
  task, ordered tasks, missing information, medical refusal).

## Reliability and Guardrails

1. **Input guardrails** run before any model call: empty/whitespace, >1000
   chars, no schedulable action, unknown pet names, medical dosage /
   medication selection / diagnosis, emergencies (redirected to a vet), and
   rule-override attempts.
2. **Schema boundary**: model output must parse into the typed schema or it
   is rejected (`SchemaError`), never partially trusted.
3. **Deterministic validation**: every field re-checked; the original
   `Task.__post_init__` is the final constructor gate; the original
   `Scheduler.check_conflicts` decides conflicts.
4. **One repair attempt maximum** (`MAX_REPAIR_ATTEMPTS = 1`), only for
   repairable issue codes.
5. **Safe failure**: model/network errors, malformed output, and failed
   repairs produce a clear message, add nothing, and leave manual entry
   fully usable (verified by tests and evaluation cases).

## Human-in-the-Loop Approval

No AI-generated task is ever added automatically. The Streamlit review UI
shows each proposed task with editable fields (pet, description, time,
duration, priority, frequency), its explanation, confidence, cited sources,
and validation status, plus an **Approve this task** checkbox. "Add Approved
Tasks" revalidates the (possibly edited) subset — including conflicts —
before converting to real `Task` objects, and the pending proposal is
cleared afterward so a refresh cannot double-add.

## Installation

```bash
git clone https://github.com/afaheem1021/pawpal-ai-care-planner.git
cd pawpal-ai-care-planner
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # optional; only needed for live mode
```

Python 3.9+ is sufficient (developed and tested on 3.9.6).

## Environment Variables

See [.env.example](.env.example). Demo mode needs **nothing** configured.

| Variable | Purpose |
|---|---|
| `PAWPAL_USE_LIVE_MODEL` | `true` to call the real model (default `false`) |
| `PAWPAL_LLM_PROVIDER` | `gemini` (default) or `anthropic` |
| `PAWPAL_API_KEY` | provider API key (never committed; `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` also work) |
| `PAWPAL_LLM_MODEL` | provider model id (default Gemini model: `gemini-3.5-flash`) |
| `PAWPAL_LOGGING_ENABLED` | `false` disables JSONL tracing |

## Running in Demo Mode

Everything below runs offline with the deterministic demo client:

```bash
python main.py --demo        # three-case AI CLI demo
streamlit run app.py         # UI shows "Mode: demo"
python -m pytest -v          # 107 tests, no network
python evaluate.py           # 19-case evaluation
```

## Running With a Live Model

```bash
cp .env.example .env         # then set PAWPAL_API_KEY=<your key>
                             # and PAWPAL_USE_LIVE_MODEL=true
python main.py --live
streamlit run app.py         # UI shows "Mode: live model"
```

`main.py --live` creates the provider selected by `PAWPAL_LLM_PROVIDER`
directly. If it is misconfigured, the CLI falls back to demo mode with a
notice instead of crashing. Unit tests remain offline; the evaluation harness
also supports an explicit, opt-in live experiment (below).

## Running the Streamlit Application

```bash
streamlit run app.py
```

Add pets → (optionally add manual tasks) → describe tasks in the ✨ PawPal AI
Task Assistant → Generate → review retrieved sources, validation issues, and
any repair notice → tick the tasks you want → **Add Approved Tasks**.

## Running the CLI Demonstration

```bash
python main.py --demo
```

## Running Unit Tests

```bash
python -m pytest -v
```

Actual output (tail):

```text
tests/test_workflow.py::test_approval_revalidates_conflicts_and_adds_nothing PASSED [ 98%]
tests/test_workflow.py::test_approval_rejects_edited_invalid_task PASSED [100%]

============================= 107 passed in 0.62s =============================
```

All 12 original PawPal+ tests are preserved and passing.

## Running the Evaluation Harness

```bash
python evaluate.py
```

## End-to-End Examples

All three examples below are actual output from `python main.py --demo`
(deterministic — you will get the same lines).

### Example 1: First-Pass Success

```text
CASE 1 - First-pass success
  Input: 'Walk Biscuit every morning at 8 for 30 minutes and feed him afterward.'

  Retrieved sources:
    - pet_profiles.md#biscuit (score 0.3242)
    - task_templates.md#feeding (score 0.1989)
    - pet_profiles.md#mochi (score 0.1638)
    - task_templates.md#walk (score 0.1251)

  Proposal (final, after any repair): 2 task(s)
    1. Biscuit: Walk at 08:00 (30 min, high, daily, confidence 0.95)
    2. Biscuit: Feeding at 08:30 (10 min, high, once, confidence 0.80)

  Validation: VALID (2 valid task(s))

  Repair attempted: no
  ...
  Workflow status: ready_for_review
  Message to user: 2 task(s) are ready for your review. Nothing is added until you approve.

  [Human approval] Approving all valid tasks (the CLI stands in for the review UI here).
  Tasks added to the schedule: 2
```

### Example 2: Conflict Detection and Repair

```text
CASE 2 - Conflict with the existing schedule, then one repair
  Input: 'Give Biscuit enrichment play at 8:15 for 15 minutes.'

  Proposal (final, after any repair): 1 task(s)
    1. Biscuit: Enrichment play at 08:40 (15 min, medium, once, confidence 0.95)

  Validation: VALID (1 valid task(s))

  Repair attempted: yes

  Workflow trace:
     receive_request [ok] Request received (52 chars)
          guardrails [passed] Input accepted
           retrieval [ok] Retrieved 4 context chunk(s)
               parse [ok] Parsed proposal with 1 task(s)
          validation [failed] 0 valid task(s), 1 error(s)
              repair [requested] One repair attempt requested
              repair [succeeded] Repaired proposal is valid

  Workflow status: ready_for_review
  Message to user: 1 task(s) are ready for your review. Nothing is added until
  you approve. (One automatic repair was applied - check the changes.)
```

The 08:15 request conflicted with the existing 08:00–08:30 walk; the single
repair moved it to 08:40 — back-to-back after the 08:30–08:40 feeding, which
the original scheduler correctly allows.

### Example 3: Guardrail Rejection

```text
CASE 3 - Guardrail rejection (medication dosage)
  Input: 'Decide how much medicine Biscuit should receive.'

  Retrieved sources:
    (none)

  Workflow status: guardrail_rejected
  Message to user: PawPal AI cannot calculate or suggest medication dosages.
  It can only schedule a medication routine your veterinarian has already
  prescribed. Please ask your vet about dosing.

  No tasks were added (unsafe request never reached the model).
```

Final schedule after the demo — produced by the ORIGINAL scheduler:

```text
===== Final schedule after the demo (original Scheduler output) =====
[ ] 08:00  Biscuit  Walk  (30 min, high priority, daily, due 2026-08-02)
[ ] 08:30  Biscuit  Feeding  (10 min, high priority, once, due 2026-08-02)
[ ] 08:40  Biscuit  Enrichment play  (15 min, medium priority, once, due 2026-08-02)

No scheduling conflicts - the AI-added tasks fit the plan.
```

## Evaluation Results

Actual output of `python evaluate.py` (results also saved to
[`evaluation/results.json`](evaluation/results.json)):

```text
PawPal AI Evaluation
====================
Prompt mode: specialized

PASS  single-daily-task
PASS  multiple-tasks
PASS  ordered-tasks
PASS  weekly-task
PASS  monthly-task
PASS  ambiguous-time
PASS  unknown-pet-guardrail
PASS  hallucinated-pet
PASS  unsupported-frequency
PASS  invalid-time
PASS  excessive-duration
PASS  existing-conflict
PASS  proposal-conflict
PASS  back-to-back-valid
PASS  medication-dosage
PASS  medical-diagnosis
PASS  malformed-model-output
PASS  api-failure
PASS  empty-input

Cases executed:                19
Passed:                        19
Failed:                         0
Overall pass rate:          100.0%

Structured output validity: 13/15
Correct task-count rate:    19/19
Known-pet compliance:       12/13
Valid-time compliance:      13/13
Valid-frequency compliance: 13/13
Conflict-free final plans:  11/11
Guardrail behavior:         4/4
Repair success:             6/6
Safe failure behavior:      3/3
```

Reading the sub-100% rows honestly: `13/15` structured validity and `12/13`
known-pet compliance are **by design** — three cases script a misbehaving
model (malformed JSON twice, an API outage, a hallucinated pet name) to
prove the system rejects bad output; the pipeline caught all of them.

## Baseline Versus Specialized Prompting

Both prompt modes run through the same harness:

```bash
python evaluate.py --prompt-mode specialized   # evaluation/results.json
python evaluate.py --prompt-mode baseline      # evaluation/results_baseline.json
```

The reproducible offline harness uses a deterministic, prompt-agnostic demo
client, so both configurations intentionally match:

| Metric | Baseline | Specialized |
|---|---:|---:|
| Overall pass rate | 100.0% | 100.0% |
| Structured output validity | 13/15 | 13/15 |
| Guardrail behavior | 4/4 | 4/4 |
| Repair success | 6/6 | 6/6 |

For the live comparison, use the explicit `--live` flag; it loads the
gitignored `.env`, uses the configured provider, and writes separate,
credential-free files:

```bash
python evaluate.py --live --prompt-mode baseline
python evaluate.py --live --prompt-mode specialized
```

The live run evaluates the 13 genuine user-input cases. It excludes six
scripted fault fixtures (malformed output, network failure, and deliberately
invalid proposals), which remain in the offline reliability suite but cannot
measure a real provider's prompt behavior.

Real live results, collected on 2026-08-02 with `gemini-3.5-flash`:

| Metric | Baseline | Specialized |
|---|---:|---:|
| Overall pass rate | 30.8% (4/13) | 92.3% (12/13) |
| Structured output validity | 0/9 | 8/9 |
| Correct task-count rate | 5/13 | 12/13 |
| Conflict-free final plans | 0/0 | 7/7 |
| Guardrail behavior | 4/4 | 4/4 |
| Repair success | 0/0 | 2/2 |

The under-specified baseline produced no valid structured proposals; only
pre-model guardrails passed. The specialized prompt produced valid,
conflict-free proposals in seven review-ready cases, while one malformed
provider response was safely rejected without changing a schedule. These are
single-run, non-deterministic observations, not a model-wide benchmark. The
machine-readable snapshots are
[`results_live_gemini_gemini-3-5-flash_baseline.json`](evaluation/results_live_gemini_gemini-3-5-flash_baseline.json)
and
[`results_live_gemini_gemini-3-5-flash_specialized.json`](evaluation/results_live_gemini_gemini-3-5-flash_specialized.json).

## RAG Before and After

Reproducible comparison (same request, retrieval disabled vs enabled —
actual output):

```text
--- WITHOUT retrieval (empty context) ---
retrieved sources: (none)
  Walk at 08:00 | cites: (no grounding)
  Feeding at 08:30 | cites: (no grounding)

--- WITH retrieval (knowledge_base/) ---
retrieved sources: ['pet_profiles.md#biscuit', 'task_templates.md#feeding',
                    'task_templates.md#walk', 'scheduling_rules.md#conflicts']
  Walk at 08:00 | cites: ['pet_profiles.md#biscuit', 'task_templates.md#walk']
  Feeding at 08:30 | cites: ['pet_profiles.md#biscuit', 'task_templates.md#feeding']
```

What actually changes offline: with retrieval, every proposal is **grounded**
— it cites the exact knowledge-base sections used, the UI shows those
sections to the reviewer, and the validator rejects citations of sources
that were not retrieved (`unknown_source_id`). With a live model the
retrieved context additionally informs durations and time windows (Biscuit's
30-minute walks, the owner's 07:00–09:00 window); that effect is not
measurable with the offline client and is not claimed as measured.

## Design Decisions and Tradeoffs

- **The LLM proposes; the original system decides.** All validation, sorting,
  recurrence, and conflict logic stays in `pawpal_system.py`. Cost: an extra
  translation layer (`TaskProposal` → `Task`). Benefit: a hallucinating
  model cannot corrupt the schedule.
- **Pure-Python TF-IDF instead of scikit-learn / a vector DB** — four small
  Markdown files don't justify a heavy dependency; determinism helps tests.
- **A deterministic demo client instead of mocked screenshots** — graders can
  run every claim in this README. The demo client is honest about being
  rule-based (see `model_card.md` limitations).
- **One repair attempt, hard-coded** — bounded cost and latency, no repair
  loops; unrepairable issues (unknown pet, medical content) fail fast.
- **Warnings vs errors** — outside-availability times are warnings (flag for
  human review), not rejections; the human stays the decision-maker.

## Known Limitations

See `model_card.md` for the full list. Highlights: natural-language
ambiguity, demo-client vs live-model behavioral differences, TF-IDF's
keyword-level matching, session-only Streamlit persistence, a small
(19-case) evaluation set, heuristic confidence scores, and a strictly
non-medical scope.

## Future Improvements

- Repeat live baseline-vs-specialized runs and report variance/cost
- Persist owners/tasks (SQLite) so approvals survive restarts
- Embedding-based retrieval once the knowledge base outgrows TF-IDF
- Multi-day planning and owner-editable availability windows
- Expand the evaluation set and add live-model regression runs

## Portfolio Reflection

The most transferable lesson: **treat the model as an untrusted input
source**. Every reliability property this system has — schema boundaries,
deterministic revalidation, bounded repair, human approval, safe failure —
came from asking "what happens when the model is wrong?" rather than "what
happens when it's right?". The original PawPal+ scheduler turned out to be
the perfect backstop: because it already validated tasks and detected
conflicts deterministically, the AI layer could be added *around* it without
weakening any guarantee it made.

## Rubric Evidence Matrix

| Rubric item | Evidence |
|---|---|
| Base project identification | README: Original Base Project |
| Original scope | README: Original Capabilities |
| Substantial AI feature | `pawpal_ai/` package, Streamlit AI assistant, CLI demo |
| Integrated behavior | Approved proposals become real `Task`s via `Pet.add_task` |
| Mermaid source | `diagrams/architecture.mmd` |
| Input-to-output data flow | Architecture diagram + workflow section |
| Working end-to-end system | `streamlit run app.py`, `python main.py --demo` |
| Two or three examples | README: End-to-End Examples (3, reproducible) |
| Reliability mechanism | Guardrails, schema boundary, validator, 1-repair policy |
| Reliability examples | Examples 2–3, evaluation safety cases |
| Installation instructions | README: Installation |
| Test instructions | README: Running Unit Tests |
| AI collaboration reflection | `model_card.md` |
| Helpful / flawed AI suggestion | `model_card.md` |
| Limitations | `model_card.md` |
| RAG bonus | Retriever + knowledge base + before/after above |
| Agent bonus | Generate→check→repair workflow + committed traces |
| Specialization bonus | Few-shot specialized prompt + comparison harness |
| Evaluation bonus | `evaluate.py`, 19 cases, saved results |
