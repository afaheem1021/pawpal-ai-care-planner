"""Structured operational tracing for the PawPal AI workflow.

Writes JSON Lines records to `logs/pawpal_ai.jsonl` when enabled. Records
capture WHAT happened at each step (guardrail codes, retrieved source ids,
validation issue codes, repair outcome, approval counts) - never API keys,
raw provider payloads, or private model reasoning.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_FILENAME = "pawpal_ai.jsonl"


class InteractionLogger:
    """Append-only JSONL logger for workflow events."""

    def __init__(self, log_dir: Optional[Path] = None, enabled: Optional[bool] = None):
        """Create a logger writing under `log_dir` (default: project logs/).

        `enabled` defaults to the PAWPAL_LOGGING_ENABLED env var (true unless
        explicitly disabled). Logging failures are swallowed - tracing must
        never break the application.
        """
        self.log_dir = Path(log_dir) if log_dir else \
            Path(__file__).resolve().parent.parent / "logs"
        if enabled is None:
            enabled = os.environ.get(
                "PAWPAL_LOGGING_ENABLED", "true"
            ).lower() not in {"0", "false", "no", "off"}
        self.enabled = enabled

    def log_event(self, event: str, **fields) -> None:
        """Append one structured event record; never raises."""
        if not self.enabled:
            return
        record = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                  "event": event}
        record.update(fields)
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_dir / LOG_FILENAME, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            pass  # tracing must never take down the app

    def log_workflow_result(self, result) -> None:
        """Log the one-line summary record for a completed workflow run."""
        validation_codes = []
        if result.validation:
            validation_codes = [issue.code for issue in result.validation.issues]
        self.log_event(
            "workflow_complete",
            status=result.status,
            retrieved_source_ids=[c.source_id for c in result.retrieved_chunks],
            retrieval_scores=[c.score for c in result.retrieved_chunks],
            proposed_task_count=len(result.proposal.tasks) if result.proposal else 0,
            validation_issue_codes=validation_codes,
            repair_attempted=result.repair_attempted,
            trace_steps=[f"{e.step}:{e.status}" for e in result.trace],
        )
