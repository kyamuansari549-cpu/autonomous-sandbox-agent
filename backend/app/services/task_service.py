"""Task service: run agent tasks in the background and persist them.

:class:`TaskService` is the layer between the HTTP API and the agent
loop. Creating a task stores a :class:`TaskRecord` in SQLite
(``settings.tasks_db_path``), starts :func:`app.agent.loop.run_agent`
on a daemon thread with its own cancellation event, and writes every
status transition back to the database — so records survive restarts
and the API never has to guess a task's state.

Honesty rules, inherited from the layers below:

* If the Groq client is not configured, :meth:`TaskService.create_task`
  raises :class:`LLMNotConfiguredError` — a task is never accepted and
  then silently faked.
* The stored ``result_summary``, ``tool_calls`` and ``error`` are copied
  verbatim from the real :class:`AgentResult`; a failed or cancelled
  task is stored as exactly that.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.agent.llm_client import LLMNotConfiguredError, create_groq_client
from app.agent.loop import run_agent
from app.config import Settings
from app.tools.definitions import ExecutionRunner, ToolDispatcher
from app.workspace import Workspace

__all__ = ["TaskRecord", "TaskService", "TASK_STATUSES"]

#: Every status a task record can be in. The last four mirror the
#: agent loop's own outcomes; "queued"/"running" are service-level.
TASK_STATUSES = (
    "queued",
    "running",
    "completed",
    "max_iterations",
    "failed",
    "cancelled",
)

_FINAL_STATUSES = ("completed", "max_iterations", "failed", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TaskRecord:
    """One task and everything the backend knows about its outcome."""

    id: str
    task: str
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    result_summary: Optional[str] = None
    tool_calls: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.id,
            "task": self.task,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result_summary": self.result_summary,
            "tool_calls": list(self.tool_calls),
            "error": self.error,
        }


class TaskService:
    """Create, run, cancel, and look up agent tasks (SQLite-backed)."""

    def __init__(
        self,
        settings: Settings,
        *,
        client=None,
        workspace: Optional[Workspace] = None,
        db_path: Optional[Path] = None,
        execution_runner: Optional[ExecutionRunner] = None,
    ) -> None:
        self._settings = settings
        self._workspace = workspace or Workspace(settings=settings)
        self._execution_runner = execution_runner
        self._db_path = self._resolve_db_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._init_db()

        # Build the model client once. A configuration problem is
        # remembered and reported by create_task, not raised here, so
        # the API can still serve reads on an unconfigured backend.
        self._client = client
        self._client_error: Optional[LLMNotConfiguredError] = None
        if client is None:
            try:
                self._client = create_groq_client(settings)
            except LLMNotConfiguredError as exc:
                self._client_error = exc

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------
    def create_task(self, task: str) -> TaskRecord:
        """Store a new task and start it on a background thread.

        Raises :class:`LLMNotConfiguredError` when no model client is
        configured — the task is not stored in that case.
        """
        if not task or not task.strip():
            raise ValueError("task text must not be empty")
        if self._client is None:
            raise LLMNotConfiguredError(str(self._client_error))
        record = TaskRecord(id=uuid.uuid4().hex, task=task)
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[record.id] = cancel_event
            self._save(record)
        thread = threading.Thread(
            target=self._run,
            args=(record.id, cancel_event),
            name=f"task-{record.id[:8]}",
            daemon=True,
        )
        thread.start()
        return record

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Return the stored record for ``task_id``, or None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
            finally:
                conn.close()
        return self._row_to_record(row) if row else None

    def list_tasks(self) -> list[TaskRecord]:
        """Return all stored records, newest first."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC, id DESC"
                ).fetchall()
            finally:
                conn.close()
        return [self._row_to_record(row) for row in rows]

    def cancel_task(self, task_id: str) -> Optional[TaskRecord]:
        """Request cancellation of a queued/running task.

        Sets the task's cancellation event; the background thread
        observes it at the next model round and stores the final
        ``cancelled`` status itself. Cancelling a finished task is a
        no-op. Returns the record as currently stored, or None.
        """
        record = self.get_task(task_id)
        if record is None:
            return None
        if record.status not in _FINAL_STATUSES:
            event = self._cancel_events.get(task_id)
            if event is not None:
                event.set()
        return record

    # ------------------------------------------------------------------
    # Background execution.
    # ------------------------------------------------------------------
    def _run(self, task_id: str, cancel_event: threading.Event) -> None:
        record = self.get_task(task_id)
        if record is None:  # pragma: no cover - record was just saved
            return
        record.status = "running"
        record.updated_at = _now()
        with self._lock:
            self._save(record)
        dispatcher = ToolDispatcher(
            self._workspace,
            settings=self._settings,
            execution_runner=self._execution_runner,
        )
        try:
            result = run_agent(
                task=record.task,
                client=self._client,
                model=self._settings.groq_model,
                dispatcher=dispatcher,
                settings=self._settings,
                cancel_event=cancel_event,
            )
            record.status = result.status
            record.result_summary = result.final_text
            record.tool_calls = list(result.tool_calls)
            record.error = result.error
        except Exception as exc:  # noqa: BLE001 - stored, not swallowed
            record.status = "failed"
            record.error = f"unexpected task failure: {type(exc).__name__}: {exc}"
        record.updated_at = _now()
        with self._lock:
            self._save(record)
            self._cancel_events.pop(task_id, None)

    # ------------------------------------------------------------------
    # SQLite storage (one short-lived connection per operation).
    # ------------------------------------------------------------------
    def _resolve_db_path(self, db_path: Optional[Path]) -> Path:
        raw = Path(db_path) if db_path is not None else Path(
            self._settings.tasks_db_path
        )
        if raw.is_absolute():
            return raw
        # Relative paths hang off backend/ (this file lives in
        # backend/app/services/, so backend/ is three parents up).
        backend_dir = Path(__file__).resolve().parents[2]
        return backend_dir / raw

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY,
                        task TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        result_summary TEXT,
                        tool_calls TEXT NOT NULL DEFAULT '[]',
                        error TEXT
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _save(self, record: TaskRecord) -> None:
        """Insert or replace the record. Caller must hold the lock."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO tasks
                    (id, task, status, created_at, updated_at,
                     result_summary, tool_calls, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.task,
                    record.status,
                    record.created_at,
                    record.updated_at,
                    record.result_summary,
                    json.dumps(record.tool_calls),
                    record.error,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            task=row["task"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result_summary=row["result_summary"],
            tool_calls=json.loads(row["tool_calls"]),
            error=row["error"],
        )
