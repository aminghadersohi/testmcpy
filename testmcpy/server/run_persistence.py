"""Incremental DB persistence for in-flight test runs.

Historically the WebSocket runner saved a run to the database only once,
at the very end (``save_test_run_to_file``) — a server crash at test 29/30
lost everything. ``RunRecord`` makes the DB the source of truth for
partial progress instead:

- ``begin()``   — creates the suite + a ``test_runs`` row (status=running)
  as soon as the run starts executing.
- ``append()``  — writes one ``question_results`` row per completed test.
- ``finish()``  — stamps the terminal status (completed/error/stopped) and
  the denormalized totals. Idempotent.

DB errors are swallowed (logged through the run's own log stream): a
persistence hiccup must degrade history, never kill a live run.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from testmcpy.storage import get_storage


def mint_run_id() -> str:
    """Legacy ``<8-hex>_<timestamp>`` run-id shape shared with the run
    registry and ``save_test_run_to_file`` so every code path mints
    correlatable identifiers."""
    return f"{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def question_result_kwargs(r: dict[str, Any]) -> dict[str, Any]:
    """Map a TestResult.to_dict() shape onto ``save_question_result``
    kwargs. Single source of truth for the mapping — used by both the
    end-of-run ``save_test_run_to_file`` and the incremental ``RunRecord``.
    """
    return {
        "question_id": r.get("test_name", r.get("question_id", "unknown")),
        "passed": r.get("passed", False),
        "score": r.get("score", 0.0),
        "answer": r.get("response", r.get("answer")),
        "tool_uses": r.get("tool_calls", r.get("tool_uses")),
        "tool_results": r.get("tool_results"),
        "tokens_input": (r.get("token_usage") or {}).get("input", 0),
        "tokens_output": (r.get("token_usage") or {}).get("output", 0),
        "duration_ms": int(r.get("duration", 0) * 1000),
        "evaluations": r.get("evaluations"),
        "error": r.get("error"),
        "cost_usd": r.get("cost", r.get("cost_usd", 0.0)),
    }


class RunRecord:
    """Write-through record of one run (one YAML file) in the results DB.

    All writes are best-effort: a failure marks the record broken and is
    reported once through ``log``, after which subsequent calls no-op so
    a flaky DB doesn't spam the run log or slow the run down.
    """

    def __init__(self, run_id: str | None = None, log: Callable[[str], None] | None = None):
        self.run_id = run_id or mint_run_id()
        self._log = log or (lambda msg: None)
        self._began = False
        self._finished = False
        self._broken = False

    def _report_db_error(self, op: str, exc: SQLAlchemyError) -> None:
        self._broken = True
        self._log(f"⚠️ Results DB unavailable ({op}): {exc} — run continues without history")

    def begin(
        self,
        *,
        test_file: str,
        model: str,
        provider: str,
        mcp_profile: str | None = None,
        llm_profile: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create the suite + the run row (status=running) up front."""
        if self._began or self._broken:
            return
        try:
            storage = get_storage()
            storage.save_suite(suite_id=test_file, name=test_file, questions=[])
            storage.save_run(
                run_id=self.run_id,
                test_id=test_file,
                test_version=1,
                model=model,
                provider=provider,
                started_at=datetime.now(timezone.utc).isoformat(),
                mcp_profile_id=mcp_profile,
                llm_profile_id=llm_profile,
                metadata=metadata,
            )
            self._began = True
        except SQLAlchemyError as exc:
            self._report_db_error("begin", exc)

    def append(self, result: dict[str, Any]) -> None:
        """Persist one completed test immediately (crash-safe progress)."""
        if not self._began or self._finished or self._broken:
            return
        try:
            get_storage().save_question_result(run_id=self.run_id, **question_result_kwargs(result))
        except SQLAlchemyError as exc:
            self._report_db_error("append", exc)

    def finish(self, status: str) -> None:
        """Stamp the terminal status + denormalized totals. Idempotent —
        the first terminal status wins (e.g. ``stopped`` from the cancel
        path must not be overwritten by a later generic finalizer)."""
        if not self._began or self._finished or self._broken:
            return
        try:
            get_storage().finish_run(
                self.run_id, status=status, completed_at=datetime.now(timezone.utc).isoformat()
            )
            self._finished = True
        except SQLAlchemyError as exc:
            self._report_db_error("finish", exc)
