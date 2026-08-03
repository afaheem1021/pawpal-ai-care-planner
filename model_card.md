# PawPal AI Model Card

## System Overview

PawPal AI converts a pet owner's natural-language request into structured
pet-care task proposals for the existing PawPal+ scheduler. It is a
*proposal* system: an LLM (or a deterministic offline stand-in) suggests
tasks; deterministic validation, the original scheduler's conflict
detection, and explicit human approval decide what actually enters the
schedule.

Pipeline: input guardrails → TF-IDF retrieval over a custom knowledge base →
structured extraction with a specialized prompt → schema validation →
business-rule and conflict validation → at most one repair attempt → human
review → conversion to original `Task` objects.

## Intended Use

- Turning plain-English descriptions of routine pet care (walks, feeding,
  litter, grooming, enrichment, water, vet-appointment reminders, and
  *already-prescribed* medication reminders) into schedule proposals.
- Single-owner, single-day scheduling within the PawPal+ data model.
- Demo mode for coursework grading and reproduction without any API key.

## Out-of-Scope Uses

- Any veterinary decision: diagnosis, medication selection, dosage
  calculation, emergency triage. Guardrails actively refuse these.
- Autonomous scheduling without human review (the system cannot do this by
  construction).
- Multi-user calendars, long-horizon planning, or non-pet task management.

## Base Project

PawPal+ — an object-oriented pet-care management and scheduling system
(`Owner`, `Pet`, `Task`, `Scheduler`) with time-sorted schedules, priority
ranking, filtering, overlap-based conflict detection, recurring tasks, input
validation, a Streamlit UI, a CLI demo, and 12 unit tests. All of it predates
this upgrade and none of it was removed or replaced.

## AI Components

| Component | Role |
|---|---|
| `GeminiLLMClient` | Default live provider adapter; stdlib REST client for `gemini-3.5-flash` (configurable via `PAWPAL_LLM_MODEL`) |
| `AnthropicLLMClient` | Optional live provider adapter, selected with `PAWPAL_LLM_PROVIDER=anthropic` |
| `DemoLLMClient` | Deterministic rule-based extractor implementing the same interface — used in demo mode, CLI, and evaluation |
| `FakeLLMClient` | Scripted responses/exceptions for unit tests |
| Specialized prompt | Schema, allowed values, safety rules, 4 few-shot examples |
| Repair prompt | Issue codes + busy windows + allowed values, one attempt max |

## Knowledge Sources

`knowledge_base/` (authored for this project, non-medical): pet profiles,
owner preferences (availability windows, approval requirement), scheduling
rules (formats, conflicts, repair limit, medical boundary), and task
templates with typical durations/priorities. Chunks carry stable ids like
`pet_profiles.md#biscuit`; proposals may only cite ids actually retrieved.

## Specialized Prompting Method

The production prompt fixes the output contract (JSON-only, exact schema),
enumerates allowed values, states medical limits and
missing-information behavior, requires per-task explanations, confidence
scores, and source-id citations, and demonstrates all of it with four
few-shot examples (single task, "afterward" ordering, missing time,
medical refusal). The baseline prompt — one sentence, no schema — exists
only for comparison and is never used in production.

## Baseline Versus Specialized Results

| Metric | Baseline | Specialized |
|---|---:|---:|
| Overall pass rate (offline harness) | 100.0% | 100.0% |
| Structured output validity | 13/15 | 13/15 |
| Guardrail behavior | 4/4 | 4/4 |
| Repair success | 6/6 | 6/6 |

These are the *actual* numbers from `python evaluate.py --prompt-mode
baseline|specialized` — and they are identical **because the offline demo
client is prompt-agnostic**. The offline run validates the comparison
harness, not the prompt effect. What the specialization *structurally*
prevents (each mapped to the validator error it would otherwise trigger with
a real model):

| Baseline prompt omission | Failure it invites | Caught by |
|---|---|---|
| No schema | free-form/wrapped JSON | `SchemaError` → repair/model_error |
| No allowed values | "urgent", "hourly", "8am" | `invalid_priority/frequency/time` |
| No pet roster | invented pets | `unknown_pet` (unrepairable) |
| No task limit | over-generation | `too_many_tasks` |
| No medical rules | dosage/diagnosis content | `prohibited_medical_content` |
| No source-id rule | fabricated citations | `unknown_source_id` |

### Live experiment

An opt-in `--live` flag runs the 13 genuine user-input cases through the
configured provider and omits six scripted fault fixtures that are only
meaningful with `FakeLLMClient`. On 2026-08-02, the adapter made a successful
direct structured call to `gemini-3.5-flash`; the paired live experiment
produced the following results:

| Metric | Baseline | Specialized |
|---|---:|---:|
| Overall pass rate | 30.8% (4/13) | 92.3% (12/13) |
| Structured output validity | 0/9 | 8/9 |
| Correct task-count rate | 5/13 | 12/13 |
| Conflict-free final plans | 0/0 | 7/7 |
| Guardrail behavior | 4/4 | 4/4 |
| Repair success | 0/0 | 2/2 |

The baseline's four passes were all pre-model guardrail cases. The specialized
prompt generated seven valid, conflict-free review plans; one malformed
structured reply was safely rejected, so no task was added. This is one live,
non-deterministic run rather than a broad model benchmark. Raw result
snapshots are saved in `evaluation/results_live_gemini_gemini-3-5-flash_*.json`.

## Reliability Mechanisms

- Typed schema boundary: malformed model output raises `SchemaError` and is
  never partially trusted.
- Every field revalidated deterministically; `Task.__post_init__` is the
  final constructor gate; `Scheduler.check_conflicts` (original code) is the
  conflict authority.
- `MAX_REPAIR_ATTEMPTS = 1`, with an explicit repairable-code allowlist.
- Safe failure everywhere: model exceptions, retrieval exceptions, and
  double-malformed output all end in a clear message with zero schedule
  mutation (asserted by tests and evaluation invariants).
- Approval-time revalidation: edited tasks are re-checked, including
  conflicts, before anything is added.

## Safety Guardrails

Pre-model input checks: empty/whitespace, over-length, no schedulable
action, unknown pet names, medication dosage, medication selection,
diagnosis, emergency health situations (redirected to a veterinarian), and
prompt-override attempts. Post-model, the validator independently rejects
medical content (dosage/diagnosis/prescription terms) in proposed tasks.
The narrow medical rule: PawPal AI may schedule a routine the owner already
knows, but must not diagnose, select medication, calculate dosage, or
replace veterinary advice.

## Human Oversight

Mandatory. Proposals are displayed with explanations, confidence, cited
sources, and validation status; the human can edit fields, approve a subset,
or discard everything. Rejection and failure paths provably do not mutate
state. Approval counts and outcomes are logged.

## Evaluation Method

`evaluate.py` runs 19 predefined cases (extraction, validation, conflict,
safety) through the *real* workflow with deterministic clients: the demo
extractor for natural inputs, scripted `FakeLLMClient` responses for
model-misbehavior cases (hallucinated pet, `hourly` frequency, `8 AM` time,
500-minute duration, malformed JSON twice, API outage). Each case runs in an
isolated world; expected status, task counts, repair behavior, guardrail
codes, and a universal "no unapproved mutation" invariant are checked.
Results are written to `evaluation/results.json`; safety-case failures exit
nonzero. `evaluate.py --live` instead runs the 13 cases without scripted
clients and writes a provider/model-specific result snapshot.

## Evaluation Results

19/19 cases pass (100%). Structured-output validity 13/15 and known-pet
compliance 12/13 reflect the three *intentional* model-misbehavior cases —
the system caught every one. Conflict-free final plans 11/11; guardrails
4/4; repair success 6/6; safe failure 3/3. Full output in the README and
`evaluation/results.json`.

## Limitations and Biases

- **Natural-language ambiguity**: vague requests ("later", "sometime") stop
  at `missing_information` and require the human to fill gaps.
- **Demo client vs live model**: the deterministic extractor handles the
  documented scenario families; a live model generalizes better but can also
  fail in ways the demo cannot exhibit. Offline metrics therefore measure
  the *pipeline's* reliability, not live-model extraction quality.
- **Dependence on model consistency** in live mode; the one-repair limit
  means a persistently misbehaving model ends in safe failure, not success.
- **Knowledge-base coverage** is small and Biscuit/Mochi-specific; TF-IDF
  matches keywords, not meaning (synonyms can miss).
- **No medical decision-making**, by design.
- **Streamlit session-only persistence** — data resets when the session ends.
- **Confidence scores are heuristic** (rule-derived in demo mode,
  self-reported in live mode) and should not be over-interpreted.
- **Evaluation set is small** (19 cases) and partially co-designed with the
  demo client's capabilities.

## Potential Misuse

Attempting to extract veterinary advice (blocked by guardrails and
validator), or treating confidence scores / schedules as professional care
guidance. The system schedules reminders; it does not know your pet.

## Privacy Considerations

Pet and owner data stay in memory for the session. Logs contain operational
metadata (event names, source ids, issue codes, counts) — not API keys, not
raw provider responses, not private reasoning. `.env` is gitignored; only
`.env.example` with placeholders is committed. In live mode, request text
and pet names are sent to the model provider — use placeholder data if that
matters to you.

## AI Collaboration During Development

This upgrade was implemented with AI coding agents working in reviewed
phases; every phase was verified by running the tests, the evaluation
harness, and the demos before committing. The human owner retained control
of the requirements, reviewed behavior and evidence, and decided what to
accept, revise, or reject.

### Helpful AI Suggestion

The agent proposed going beyond a mocked test client and building a full
**deterministic `DemoLLMClient`** implementing the same `LLMClient` protocol
as the live adapter. This turned out to be the keystone of reproducibility:
the CLI demo, the Streamlit demo mode, and the entire evaluation harness run
identically on any machine with no API key, and the workflow code cannot
tell the difference — which also proved the provider abstraction was
actually provider-agnostic.

### Flawed or Incorrect AI Suggestion

Two real ones, both caught by verification rather than by reading the code:

1. The first version of the demo client's action matcher classified
   *"Feed him after the walk"* as a **Walk** task, because it tested action
   keywords in a fixed list order and "walk" appears in the clause. The
   smoke test exposed it immediately; the fix matches the *earliest* keyword
   in the clause (the leading verb).
2. The first version of the evaluation metrics computed three "compliance"
   rates as `n/n` **by construction** (the denominator and numerator were
   the same filtered list), which would have fabricated perfect-looking
   evidence. It was replaced with real measurements over final-plan error
   codes — which is why known-pet compliance now honestly reads 12/13.

## What Testing Revealed

- The original scheduler's back-to-back rule matters for repair: the first
  conflict-repair implementation would have parked repaired tasks in dead
  air; using "start exactly when the busy window ends" produced tight,
  legal schedules (08:30 feeding → 08:40 enrichment).
- Flagging *both* tasks of a proposal-vs-proposal conflict made repair
  unstable (both moved to the same slot and re-conflicted); flagging only
  the later task made repair deterministic.
- `bool` is a subclass of `int` in Python — the schema layer needed an
  explicit check so `duration_mins: true` is rejected.

## Future Improvements

Repeated live-model trials with variance, latency, and cost reporting;
persistence beyond the session; embedding retrieval when the knowledge base
grows; owner-editable availability windows; a larger,
adversarially-authored evaluation set; richer repair context (e.g.,
suggesting the nearest three free slots).
