"""Input guardrails for the PawPal AI workflow.

Every natural-language request passes through `check_request()` before any
retrieval or model call happens. The checks are deterministic keyword/pattern
rules — cheap, testable, and independent of the model — and they fail closed:
a rejected request never reaches the extraction step.

Medical boundary: PawPal AI may organize a routine that the owner already
knows, but it must not diagnose a pet, select medication, calculate dosage,
or replace veterinary advice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_REQUEST_CHARS = 1000

EMERGENCY_MESSAGE = (
    "This sounds like it could be a medical emergency. PawPal AI cannot help "
    "with urgent health problems - please contact your veterinarian or an "
    "emergency veterinary clinic right away."
)

_EMERGENCY_PATTERNS = [
    r"\bemergency\b",
    r"\bpoison(ed|ing)?\b",
    r"\bate\s+(chocolate|grapes|raisins|xylitol|onions?)\b",
    r"\bseizure\b",
    r"\bcollapsed?\b",
    r"\bbleeding\b",
    r"\bnot\s+breathing\b",
    r"\bcan'?t\s+breathe\b",
    r"\bunconscious\b",
    r"\bvomiting\s+blood\b",
]

_DOSAGE_PATTERNS = [
    r"\bhow\s+much\s+(\w+\s+)?(medicine|medication|med|drug)\b",
    r"\bdos(e|age|ing)\b",
    r"\bhow\s+many\s+(mg|milligrams|pills|tablets)\b",
    r"\b\d+\s*mg\b.*\b(give|safe|okay|ok)\b",
    r"\bdecide\s+how\s+much\b",
]

_MEDICATION_SELECTION_PATTERNS = [
    r"\b(what|which)\s+(\w+\s+)?(medicine|medication|drug|antibiotic|painkiller)s?\s+(should|can|do)\b",
    r"\brecommend\s+(a\s+)?(medicine|medication|drug|antibiotic)\b",
    r"\bpick\s+(a\s+)?(medicine|medication|drug)\b",
    r"\bprescribe\b",
]

_DIAGNOSIS_PATTERNS = [
    r"\bdiagnos(e|is|ing)\b",
    r"\bwhat('?s|\s+is)\s+wrong\s+with\b",
    r"\bwhy\s+is\s+\w+\s+(sick|limping|vomiting|coughing|sneezing|scratching)\b",
    r"\bis\s+(he|she|it|my\s+\w+)\s+sick\b",
    r"\bwhat\s+(disease|illness|condition)\b",
]

_OVERRIDE_PATTERNS = [
    r"\bignore\s+(all\s+|the\s+|your\s+)?(previous\s+|prior\s+)?(instructions?|rules?)\b",
    r"\bdisregard\s+(the\s+|your\s+)?(rules?|instructions?|guardrails?)\b",
    r"\bsystem\s+prompt\b",
    r"\bwithout\s+(my\s+|human\s+|the\s+owner'?s?\s+)?approval\b",
    r"\bbypass\b",
]

# Words that suggest the request actually asks to schedule/track pet care.
_ACTION_WORDS = {
    "walk", "walks", "walking", "feed", "feeds", "feeding", "food", "breakfast",
    "dinner", "meal", "clean", "cleaning", "litter", "groom", "grooming", "brush",
    "brushing", "trim", "play", "playtime", "enrichment", "fetch", "water",
    "refill", "medication", "medicine", "pill", "vet", "appointment", "reminder",
    "remind", "schedule", "task", "tasks", "exercise", "train", "training", "nail",
    "bath", "bathe",
}

# Capitalized words that are ordinary sentence words, not candidate pet names.
_COMMON_CAPITALIZED = {
    "i", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december", "am", "pm",
    "please", "schedule", "walk", "feed", "clean", "give", "add", "every",
    "morning", "evening", "afternoon", "night", "today", "tomorrow", "the",
    "a", "an", "and", "then", "after", "before", "also", "at", "make", "set",
    "remind", "he", "she", "it", "his", "her", "my", "our",
}


@dataclass
class GuardrailResult:
    """Outcome of the input guardrail check."""

    allowed: bool
    code: str
    message: str

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-safe)."""
        return {"allowed": self.allowed, "code": self.code, "message": self.message}


def _matches_any(text: str, patterns: list) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _candidate_names(request: str) -> list:
    """Return capitalized mid-sentence words that look like pet names."""
    candidates = []
    tokens = re.findall(r"[A-Za-z']+", request)
    for token in tokens:
        if token[0].isupper() and token.lower() not in _COMMON_CAPITALIZED:
            candidates.append(token.strip("'"))
    return candidates


def check_request(request: str, known_pet_names: list) -> GuardrailResult:
    """Run every input guardrail against a natural-language request.

    Returns the first failing rule as a GuardrailResult with allowed=False,
    or an `allowed` result when the request is safe to process.
    """
    if request is None or not request.strip():
        return GuardrailResult(
            False, "empty_input", "Please describe the care tasks you want to schedule."
        )

    if len(request) > MAX_REQUEST_CHARS:
        return GuardrailResult(
            False,
            "input_too_long",
            f"That request is too long ({len(request)} characters). "
            f"Please keep it under {MAX_REQUEST_CHARS} characters.",
        )

    lowered = request.lower()

    if _matches_any(lowered, _EMERGENCY_PATTERNS):
        return GuardrailResult(False, "emergency_health_request", EMERGENCY_MESSAGE)

    if _matches_any(lowered, _DOSAGE_PATTERNS):
        return GuardrailResult(
            False,
            "medical_dosage",
            "PawPal AI cannot calculate or suggest medication dosages. It can "
            "only schedule a medication routine your veterinarian has already "
            "prescribed. Please ask your vet about dosing.",
        )

    if _matches_any(lowered, _MEDICATION_SELECTION_PATTERNS):
        return GuardrailResult(
            False,
            "medication_selection",
            "PawPal AI cannot choose or recommend medication. Please consult "
            "your veterinarian; PawPal can then schedule the prescribed routine.",
        )

    if _matches_any(lowered, _DIAGNOSIS_PATTERNS):
        return GuardrailResult(
            False,
            "medical_diagnosis",
            "PawPal AI cannot diagnose health conditions. If you are worried "
            "about your pet's health, please contact your veterinarian.",
        )

    if _matches_any(lowered, _OVERRIDE_PATTERNS):
        return GuardrailResult(
            False,
            "rule_override",
            "That request asks PawPal AI to skip its safety or approval rules, "
            "which it cannot do. Every AI-generated task requires your review.",
        )

    words = set(re.findall(r"[a-z]+", lowered))
    if not words & _ACTION_WORDS:
        return GuardrailResult(
            False,
            "no_schedulable_action",
            "I couldn't find a schedulable pet-care action in that request. "
            "Try something like 'Walk Biscuit every morning at 8 for 30 minutes.'",
        )

    known_lower = {name.lower() for name in known_pet_names}
    unknown = [
        name for name in _candidate_names(request) if name.lower() not in known_lower
    ]
    mentions_known_pet = any(name in lowered for name in known_lower)
    if unknown and not mentions_known_pet:
        return GuardrailResult(
            False,
            "unknown_pet",
            f"I don't recognize the pet name(s) {', '.join(sorted(set(unknown)))}. "
            f"Known pets: {', '.join(sorted(known_pet_names)) or '(none yet)'}. "
            "Please add the pet first or check the spelling.",
        )

    return GuardrailResult(True, "allowed", "Request accepted for processing.")
