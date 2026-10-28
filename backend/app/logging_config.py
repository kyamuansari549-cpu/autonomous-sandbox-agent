"""Structured logging setup (Milestone 8, stdlib only).

All backend modules log under the ``asa`` logger tree
(``asa.agent``, ``asa.tasks``, …) so one configuration controls the
whole backend. :func:`configure_logging` attaches a single stream
handler with a consistent format — timestamp, level, logger name,
message — and sets the tree's level. It is idempotent: the app
factory and :class:`app.services.task_service.TaskService` both call
it, and repeat calls change nothing (the requested level of the
*first* call wins), so it is safe to call from any entry point.

What gets logged, and what never does:

* Logged: task lifecycle (created / started / finished, with the task
  id), each tool call's **name**, loop failures, and tool
  unavailability (sandbox / search) as warnings via the loop.
* **Never logged:** the Groq API key (or any credential), tool
  *argument values* (a ``create_file`` argument is file content), and
  file contents generally. Only names, ids, statuses and error types
  cross the log boundary — a log file must never become a second,
  unguarded copy of the workspace or of the user's secrets.
"""

from __future__ import annotations

import logging
import threading

__all__ = ["configure_logging", "get_logger"]

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_lock = threading.Lock()
_configured = False


def _coerce_level(level: str | int) -> int:
    """Accept a level name ("INFO") or number; fall back to INFO."""
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: str | int = "INFO") -> None:
    """Configure the ``asa`` logger tree once (idempotent).

    Safe to call from multiple entry points and multiple threads;
    only the first call installs the handler and sets the level.
    """
    global _configured
    with _lock:
        if _configured:
            return
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        root = logging.getLogger("asa")
        root.addHandler(handler)
        root.setLevel(_coerce_level(level))
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return the ``asa.<name>`` logger for a backend module."""
    return logging.getLogger(f"asa.{name}")
