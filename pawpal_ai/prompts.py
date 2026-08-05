"""Prompt construction and response parsing for PawPal AI.

Two prompt modes exist:

* BASELINE - an intentionally simple prompt used only for the
  baseline-vs-specialized comparison experiment (never in production).
* SPECIALIZED - the production prompt: role, exact JSON schema, allowed
  values, retrieved context, few-shot examples, and safety rules.

User prompts embed machine-readable `*_JSON:` lines alongside the prose
sections. Real models get richer grounding from them, and the deterministic
`DemoLLMClient` parses them to produce offline responses.
"""

from __future__ import annotations

import json

from .schemas import PlanProposal

MAX_GENERATED_TASKS = 5

BASELINE_SYSTEM_PROMPT = (
    "Convert this request into pet-care tasks and return JSON."
)

SPECIALIZED_SYSTEM_PROMPT = """\
You are PawPal AI, a careful assistant that converts a pet owner's natural-language
request into structured care-task proposals for the PawPal+ scheduler.

## Output schema

Return ONLY a JSON object (no prose, no markdown fences) with exactly this shape:

{
  "tasks": [
    {
      "pet_name": "<name of an existing pet>",
      "description": "<short task description>",
      "time": "<24-hour HH:MM>",
      "duration_mins": <integer minutes>,
      "priority": "high" | "medium" | "low",
      "frequency": "daily" | "weekly" | "monthly" | "once",
      "explanation": "<one sentence: why this task, citing context when used>",
      "confidence": <number between 0 and 1>,
      "source_ids": ["<retrieved source id>", ...]
    }
  ],
  "missing_information": ["<question the owner must answer>", ...],
  "warnings": ["<safety or scheduling note>", ...]
}

## Rules

1. Return structured JSON only - no other text.
2. Only use pets listed under KNOWN PETS. Match names case-insensitively, then
   copy the pet name with the exact spelling and capitalization from KNOWN PETS.
   Never invent a pet.
3. priority must be one of: high, medium, low.
4. frequency must be one of: daily, weekly, monthly, once.
5. time must be 24-hour HH:MM (e.g. "08:00", "18:30").
6. Never generate more than {max_tasks} tasks per request.
7. Never invent medication names or dosages.
8. Never diagnose health conditions; PawPal AI only schedules routines the
   owner already knows. For medical questions, refer the owner to a vet.
9. A start time is required. If the owner omits the time, do NOT invent it - add
   a question to missing_information instead. "Morning" means 08:00 and
   "evening" means 18:00 per the scheduling rules; anything vaguer is missing.
10. A duration is NOT blocking information. When the owner gives a start time
    but omits duration, always create the task using a sensible default. First
    use a matching duration from RETRIEVED CONTEXT. If none is available, use:
    walk 30; feeding 10 for a dog or 5 for a cat; litter cleaning 10; general
    cleaning/grooming/brushing/bath 15; water refill 5; play/enrichment 15;
    prescribed medication reminder 5; vet appointment 60; any other safe
    routine-care task 15 minutes. The owner's explicit duration always wins.
    Mention an inferred duration in the explanation and use confidence 0.75-0.85.
    NEVER ask for a duration in missing_information when one of these defaults
    can be used.
11. An explicit user-requested time always wins over owner availability
    preferences. A task during work hours or outside a usual availability
    window must still be proposed at the requested time. Add a warning for
    human review, but NEVER put availability in missing_information, omit the
    task, or move it solely because of work hours.
12. Propose every independently schedulable task in the request, up to the
    {max_tasks}-task limit. Do not discard the other tasks just because one task
    needs clarification.
13. If recurrence is omitted, use frequency "once". Words such as "daily",
    "every morning", or "every evening" mean frequency "daily".
14. source_ids may only contain ids listed under RETRIEVED CONTEXT.
15. Never claim retrieved context contains facts it does not contain.
16. Preserve relative ordering: "feed him after the walk" means the feeding
    starts when the walk ends.
17. Use lower confidence (0.5-0.75) when the request is ambiguous; high
    confidence (0.85-1.0) only when every detail is explicit.

## Examples

### Example 1: single daily task
Input: Walk Biscuit every morning at 8 for 30 minutes.
Output:
{"tasks": [{"pet_name": "Biscuit", "description": "Morning walk", "time": "08:00",
"duration_mins": 30, "priority": "high", "frequency": "daily",
"explanation": "The owner asked for a daily 30-minute morning walk at 8.",
"confidence": 0.95, "source_ids": ["pet_profiles.md#biscuit"]}],
"missing_information": [], "warnings": []}

### Example 2: ordered tasks
Input: Walk Biscuit at 8 for 30 minutes and feed him afterward.
Output:
{"tasks": [{"pet_name": "Biscuit", "description": "Morning walk", "time": "08:00",
"duration_mins": 30, "priority": "high", "frequency": "daily",
"explanation": "Explicit 30-minute walk at 8.", "confidence": 0.9,
"source_ids": ["pet_profiles.md#biscuit"]},
{"pet_name": "Biscuit", "description": "Feed Biscuit", "time": "08:30",
"duration_mins": 10, "priority": "high", "frequency": "daily",
"explanation": "Feeding follows the walk, so it starts when the walk ends at 08:30.",
"confidence": 0.85, "source_ids": ["task_templates.md#feeding"]}],
"missing_information": [], "warnings": []}

### Example 3: missing information
Input: Schedule grooming for Biscuit.
Output:
{"tasks": [], "missing_information":
["What time should Biscuit's grooming happen? The duration can default to 15 minutes."],
"warnings": []}

### Example 4: omitted durations and requested work-hour times
Input: Walk Biscuit at 12 PM and clean Mochi at 12:45 PM.
Output:
{"tasks": [{"pet_name": "Biscuit", "description": "Walk", "time": "12:00",
"duration_mins": 30, "priority": "high", "frequency": "once",
"explanation": "The owner requested a noon walk; the 30-minute duration uses the walk default.",
"confidence": 0.82, "source_ids": ["task_templates.md#walk"]},
{"pet_name": "Mochi", "description": "Cleaning", "time": "12:45",
"duration_mins": 15, "priority": "low", "frequency": "once",
"explanation": "The owner requested cleaning at 12:45; the 15-minute duration uses the general cleaning default.",
"confidence": 0.8, "source_ids": ["task_templates.md#general-pet-cleaning"]}],
"missing_information": [], "warnings":
["The requested times are during the owner's usual work hours; keep the exact times and flag them for review."]}

### Example 5: medical boundary
Input: Decide how much medicine Biscuit should receive.
Output:
{"tasks": [], "missing_information": [], "warnings":
["PawPal AI cannot select medication or calculate dosage. Please ask your
veterinarian; PawPal can then schedule the prescribed routine."]}
""".replace("{max_tasks}", str(MAX_GENERATED_TASKS))


def _pets_json(pets: list) -> str:
    return json.dumps(
        [{"name": pet.name, "species": pet.species} for pet in pets]
    )


def _tasks_json(tasks: list) -> str:
    return json.dumps(
        [
            {
                "pet_name": task.pet_name,
                "description": task.description,
                "time": task.time,
                "duration_mins": task.duration_mins,
            }
            for task in tasks
        ]
    )


def build_user_prompt(request: str, pets: list, existing_tasks: list,
                      retrieved_chunks: list) -> str:
    """Assemble the user prompt: request, pets, schedule, retrieved context.

    Only the relevant slice of application state is included - pet names and
    today's tasks - never the whole object graph.
    """
    context_lines = []
    for chunk in retrieved_chunks:
        context_lines.append(f"[{chunk.source_id}] (score {chunk.score})\n{chunk.text}")
    context_block = "\n\n".join(context_lines) if context_lines else "(none retrieved)"

    return f"""\
## KNOWN PETS
PETS_JSON: {_pets_json(pets)}

## EXISTING TASKS (today's schedule)
EXISTING_TASKS_JSON: {_tasks_json(existing_tasks)}

## RETRIEVED CONTEXT
SOURCE_IDS_JSON: {json.dumps([c.source_id for c in retrieved_chunks])}

{context_block}

## USER REQUEST
<<<REQUEST>>>
{request}
<<<END_REQUEST>>>

Convert the user request into the JSON schema you were given. Remember:
JSON only, known pets only, retrieved source ids only. Missing duration is not
blocking: apply the retrieved or system default and propose the task. Keep every
explicit requested time even when it falls during work hours; availability is a
warning for review, never missing information.
"""


def build_repair_prompt(request: str, original_proposal, issues: list,
                        busy_windows: list, pets: list,
                        retrieved_chunks: list, raw_output=None) -> str:
    """Assemble the one-shot repair prompt after validation/conflict failure.

    Includes the original request and proposal, machine-readable issue codes,
    the busy time windows behind any conflicts, and the allowed values, then
    asks for a complete corrected proposal.
    """
    issues_payload = [
        {"code": i.code, "message": i.message, "task_index": i.task_index}
        for i in issues
    ]
    proposal_json = json.dumps(original_proposal.to_dict()) if original_proposal else "null"

    return f"""\
## REPAIR REQUEST
Your previous proposal for the request below failed validation. Return a
COMPLETE corrected JSON proposal in the same schema (all tasks, not a diff).

## ORIGINAL USER REQUEST
<<<REQUEST>>>
{request}
<<<END_REQUEST>>>

## KNOWN PETS
PETS_JSON: {_pets_json(pets)}

## YOUR PREVIOUS PROPOSAL
ORIGINAL_PROPOSAL_JSON: {proposal_json}
{f"RAW_MODEL_OUTPUT: {raw_output}" if raw_output else ""}

## VALIDATION ISSUES
ISSUES_JSON: {json.dumps(issues_payload)}

## BUSY TIME WINDOWS (already occupied on the schedule; minutes since midnight)
BUSY_WINDOWS_JSON: {json.dumps(busy_windows)}

## RETRIEVED CONTEXT SOURCE IDS
SOURCE_IDS_JSON: {json.dumps([c.source_id for c in retrieved_chunks])}

## RULES REMINDER
- Move conflicting tasks to a free time slot (a task may start exactly when
  another ends - back-to-back is allowed).
- Keep every valid task unchanged.
- priority: high|medium|low; frequency: daily|weekly|monthly|once; time: HH:MM.
- JSON only.
"""


def parse_plan_response(data: dict) -> PlanProposal:
    """Convert a raw model response dict into a validated PlanProposal.

    Raises SchemaError (from the schemas module) when the structure is wrong;
    the workflow treats that as a repairable model failure.
    """
    return PlanProposal.from_dict(data)
