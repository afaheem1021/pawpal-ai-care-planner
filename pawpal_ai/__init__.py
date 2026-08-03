"""PawPal AI: natural-language pet-care scheduling on top of PawPal+.

This package adds an AI proposal pipeline (guardrails -> retrieval ->
extraction -> validation -> repair -> human approval) around the existing
deterministic PawPal+ scheduler. The original `pawpal_system` classes remain
the source of truth for task validation, sorting, conflicts, and recurrence.
"""
