"""Deterministic offline "model" for demo mode, evaluation, and grading.

`DemoLLMClient` implements the same `LLMClient` protocol as the live
Anthropic adapter, but produces responses with rule-based parsing instead of
a network call. It reads the machine-readable `*_JSON:` lines that
`pawpal_ai.prompts` embeds in every prompt, so the workflow code is identical
in demo and live mode.

It is intentionally honest about being a stand-in: it handles the demo and
evaluation scenarios (explicit times, "afterward" ordering, morning/evening
words, missing times, repair-by-rescheduling) deterministically, and puts
anything it cannot resolve into `missing_information` rather than guessing.
"""

from __future__ import annotations

import json
import re

# action keyword -> (description, default duration, default priority, template slug)
_ACTIONS = [
    (("walk", "walks", "walking"), "Walk", 30, "high", "walk"),
    (("feed", "feeds", "feeding", "breakfast", "dinner"), "Feeding", 10, "high", "feeding"),
    (("litter",), "Clean litter box", 10, "medium", "litter-box-cleaning"),
    (("water",), "Refill water", 5, "medium", "water-refill"),
    (("play", "playtime", "enrichment", "fetch"), "Enrichment play", 15, "medium", "enrichment"),
    (("groom", "grooming", "brush", "brushing", "nail"), "Grooming", 15, "low", "grooming"),
    (("pill", "medication", "medicine"), "Give prescribed medication", 5, "high",
     "prescribed-medication-reminder"),
    (("vet", "appointment"), "Vet appointment", 60, "high", "vet-appointment-reminder"),
]

_TIME_RE = re.compile(r"\b(?:at|around)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)
_DURATION_RE = re.compile(r"(\d+)[-\s]*min(?:ute)?s?", re.IGNORECASE)
_AFTER_RE = re.compile(r"\bafter(ward|wards)?\b|\bafter (the|that|his|her|it)\b", re.IGNORECASE)
_PRONOUN_RE = re.compile(r"\b(him|her|he|she|his|hers|it|its)\b", re.IGNORECASE)


def _read_json_line(prompt: str, marker: str, default):
    """Extract the JSON payload following `marker` on a prompt line."""
    match = re.search(rf"^{marker}:\s*(.+)$", prompt, re.MULTILINE)
    if not match:
        return default
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return default


def _read_request(prompt: str) -> str:
    match = re.search(r"<<<REQUEST>>>\n(.*?)\n<<<END_REQUEST>>>", prompt, re.DOTALL)
    return match.group(1).strip() if match else ""


def _minutes_to_hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class DemoLLMClient:
    """Rule-based deterministic extractor with the LLMClient interface."""

    def generate_structured(self, system_prompt: str, user_prompt: str) -> dict:
        """Produce a PlanProposal-shaped dict from the embedded prompt data."""
        if "## REPAIR REQUEST" in user_prompt:
            return self._repair(user_prompt)
        return self._extract(user_prompt)

    # ------------------------------------------------------------ extraction

    def _extract(self, prompt: str) -> dict:
        pets = _read_json_line(prompt, "PETS_JSON", [])
        source_ids = set(_read_json_line(prompt, "SOURCE_IDS_JSON", []))
        request = _read_request(prompt)

        pet_names = [pet["name"] for pet in pets]
        tasks: list = []
        missing: list = []
        warnings: list = []
        last_pet = None
        last_end = None  # minutes since midnight when the previous task ends

        clauses = [c.strip() for c in re.split(r"[.;!\n]|,?\s+and\s+|,\s*then\s+", request)
                   if c.strip()]
        for clause in clauses:
            action = self._match_action(clause)
            if action is None:
                continue
            description, default_duration, priority, template_slug = action

            pet = self._match_pet(clause, pet_names, last_pet)
            if pet is None:
                missing.append(f"Which pet is '{clause}' for?")
                continue
            last_pet = pet

            duration = default_duration
            duration_match = _DURATION_RE.search(clause)
            explicit_duration = duration_match is not None
            if duration_match:
                duration = int(duration_match.group(1))

            start, time_source = self._match_time(clause, last_end)
            if start is None:
                missing.append(
                    f"What time should '{description}' for {pet} happen? "
                    "No time was given and PawPal AI does not invent times."
                )
                continue
            last_end = start + duration

            confidence = {"explicit": 0.9, "inferred": 0.7, "relative": 0.8}[time_source]
            if explicit_duration and time_source == "explicit":
                confidence = 0.95

            chunk_ids = [
                cid for cid in (
                    f"pet_profiles.md#{pet.lower()}",
                    f"task_templates.md#{template_slug}",
                )
                if cid in source_ids
            ]
            explanation = (
                f"The owner asked to schedule '{description.lower()}' for {pet}"
                + (" at an explicit time." if time_source == "explicit"
                   else " right after the previous task." if time_source == "relative"
                   else " using the owner's usual time window.")
            )
            tasks.append({
                "pet_name": pet,
                "description": description,
                "time": _minutes_to_hhmm(start),
                "duration_mins": duration,
                "priority": priority,
                "frequency": self._match_frequency(clause, request),
                "explanation": explanation,
                "confidence": confidence,
                "source_ids": chunk_ids,
            })

        from .prompts import MAX_GENERATED_TASKS
        if len(tasks) > MAX_GENERATED_TASKS:
            warnings.append(
                f"Request implied {len(tasks)} tasks; only the first "
                f"{MAX_GENERATED_TASKS} are proposed (configured limit)."
            )
            tasks = tasks[:MAX_GENERATED_TASKS]
        if not tasks and not missing:
            missing.append("No schedulable pet-care task could be identified.")
        return {"tasks": tasks, "missing_information": missing, "warnings": warnings}

    @staticmethod
    def _match_action(clause: str):
        """Pick the action whose keyword appears earliest (the leading verb).

        'Feed him after the walk' mentions both feed and walk; the clause is
        about feeding, and its verb comes first.
        """
        lowered = clause.lower()
        best = None
        best_pos = None
        for keywords, description, duration, priority, slug in _ACTIONS:
            for keyword in keywords:
                match = re.search(rf"\b{keyword}\b", lowered)
                if match and (best_pos is None or match.start() < best_pos):
                    best_pos = match.start()
                    best = (description, duration, priority, slug)
        return best

    @staticmethod
    def _match_pet(clause: str, pet_names: list, last_pet):
        for name in pet_names:
            if re.search(rf"\b{re.escape(name)}", clause, re.IGNORECASE):
                return name
        if last_pet and _PRONOUN_RE.search(clause):
            return last_pet
        if len(pet_names) == 1:
            return pet_names[0]
        return None

    @staticmethod
    def _match_time(clause: str, last_end):
        """Return (minutes-since-midnight, source) or (None, ...) when absent."""
        lowered = clause.lower()
        if _AFTER_RE.search(lowered) and last_end is not None:
            return last_end, "relative"
        match = _TIME_RE.search(clause)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            meridiem = (match.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif not meridiem and hour < 12 and re.search(
                r"\bevening\b|\btonight\b|\bpm\b", lowered
            ):
                hour += 12
            if hour > 23 or minute > 59:
                return None, "none"
            return hour * 60 + minute, "explicit"
        # Scheduling rules: "morning" means 08:00, "evening" means 18:00.
        if re.search(r"\bmorning\b", lowered):
            return 8 * 60, "inferred"
        if re.search(r"\bevening\b|\btonight\b", lowered):
            return 18 * 60, "inferred"
        return None, "none"

    @staticmethod
    def _match_frequency(clause: str, request: str) -> str:
        lowered = clause.lower()
        if re.search(r"\bevery (morning|evening|day|night)\b|\bdaily\b|\beach day\b", lowered):
            return "daily"
        if re.search(r"\bevery week\b|\bweekly\b", lowered):
            return "weekly"
        if re.search(r"\bevery month\b|\bmonthly\b", lowered):
            return "monthly"
        return "once"

    # ---------------------------------------------------------------- repair

    def _repair(self, prompt: str) -> dict:
        """Deterministically fix the issues named in the repair prompt."""
        proposal = _read_json_line(prompt, "ORIGINAL_PROPOSAL_JSON", None)
        issues = _read_json_line(prompt, "ISSUES_JSON", [])
        busy_windows = _read_json_line(prompt, "BUSY_WINDOWS_JSON", [])
        if not isinstance(proposal, dict):
            # Nothing structured to repair (e.g. previous output was garbage).
            return {"tasks": [], "missing_information": [],
                    "warnings": ["Previous output could not be repaired."]}

        tasks = list(proposal.get("tasks", []))
        warnings = list(proposal.get("warnings", []))
        missing = list(proposal.get("missing_information", []))
        drop_indexes = set()

        for issue in issues:
            index = issue.get("task_index")
            code = issue.get("code")
            if index is None or index >= len(tasks):
                continue
            task = tasks[index]
            if code in ("schedule_conflict", "proposal_conflict"):
                task["time"] = self._next_free_slot(task, busy_windows)
                task["explanation"] = (
                    task.get("explanation", "")
                    + " Rescheduled to the next free slot to resolve a conflict."
                ).strip()
            elif code == "invalid_time":
                fixed = self._coerce_time(str(task.get("time", "")))
                if fixed is None:
                    drop_indexes.add(index)
                    missing.append(
                        f"What time should '{task.get('description')}' happen?"
                    )
                else:
                    task["time"] = fixed
            elif code == "invalid_frequency":
                task["frequency"] = "daily" if "every" in str(
                    task.get("frequency", "")).lower() else "once"
            elif code == "invalid_priority":
                task["priority"] = "medium"
            elif code in ("invalid_duration", "duration_out_of_range"):
                try:
                    task["duration_mins"] = max(1, min(240, int(task["duration_mins"])))
                except (ValueError, TypeError):
                    task["duration_mins"] = 15
            elif code == "unknown_source_id":
                task["source_ids"] = []
            else:
                # unknown pet, medical content, etc. - not repairable; drop it
                drop_indexes.add(index)
                warnings.append(
                    f"Removed task '{task.get('description')}' ({code}): not repairable."
                )

        tasks = [task for i, task in enumerate(tasks) if i not in drop_indexes]
        return {"tasks": tasks, "missing_information": missing, "warnings": warnings}

    @staticmethod
    def _next_free_slot(task: dict, busy_windows: list) -> str:
        """Slide the task's start time forward until it overlaps nothing."""
        try:
            hour, minute = str(task.get("time", "08:00")).split(":")
            start = int(hour) * 60 + int(minute)
        except ValueError:
            start = 8 * 60
        duration = int(task.get("duration_mins", 15))
        windows = sorted(
            (int(w["start"]), int(w["end"])) for w in busy_windows
            if isinstance(w, dict) and "start" in w and "end" in w
        )
        moved = True
        while moved:
            moved = False
            for window_start, window_end in windows:
                if start < window_end and start + duration > window_start:
                    start = window_end  # back-to-back with the busy window is legal
                    moved = True
        return _minutes_to_hhmm(start)

    @staticmethod
    def _coerce_time(raw: str):
        """Try to turn '8am' / '8 pm' / '18.30' into HH:MM; None if hopeless."""
        match = re.match(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*$", raw, re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = (match.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        return f"{hour:02d}:{minute:02d}"
