"""Tests for Milestone 8: logging hygiene, concurrency, hardening.

* **Logging:** the fake-client flow runs with a sentinel API key in
  settings and sentinel file content in a ``create_file`` call; the
  captured logs must contain tool-call *names* and lifecycle lines but
  NEITHER sentinel — proving logs never carry credentials or content.
* **Concurrency:** an event-gated fake client proves tasks beyond
  ``MAX_CONCURRENT_TASKS`` wait ``queued``, start when a slot frees,
  and that a queued task can be cancelled without ever running.
* **Prompt injection:** the system prompt must state the
  data-not-instructions rule. This asserts the *prompt text* only —
  prompt wording is a defense-in-depth layer, not a behaviour proof.
* **Failure paths:** a garbage SQLite file must produce a clear
  :class:`TaskStoreError` at construction, and a workspace deleted
  mid-task must leave the record in a terminal status with the
  failure visible — never stuck ``running``, never a crashed thread.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.loop import SYSTEM_PROMPT, run_agent
from app.config import Settings
from app.logging_config import configure_logging
from app.services.task_service import TaskService, TaskStoreError
from app.tools.definitions import ToolDispatcher
from app.workspace import Workspace
from test_agent_loop import FakeClient, text_response, tool_response
from test_milestone5 import make_service, wait_for_status

KEY_SENTINEL = "sk-TEST-SENTINEL"
CONTENT_SENTINEL = "FILE-CONTENT-SENTINEL"


# ----------------------------------------------------------------------
# Logging: lifecycle + tool names are logged; secrets/content never.
# ----------------------------------------------------------------------
def test_logs_have_tool_names_but_never_secrets_or_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging("INFO")
    settings = Settings(
        **{"groq_api_key": KEY_SENTINEL, "groq_model": "test-model"}
    )
    workspace = Workspace(root=tmp_path / "ws", settings=settings)
    dispatcher = ToolDispatcher(workspace, settings=settings)
    client = FakeClient(
        [
            tool_response(
                "create_file",
                {
                    "relative_path": "note.txt",
                    "content": CONTENT_SENTINEL,
                },
            ),
            text_response("note.txt written."),
        ]
    )
    with caplog.at_level(logging.DEBUG, logger="asa"):
        result = run_agent(
            task="write a note file",
            client=client,
            model="test-model",
            dispatcher=dispatcher,
            settings=settings,
            task_id="logging-test-task",
        )
    assert result.status == "completed"
    # The file really was created with the sentinel content...
    assert (tmp_path / "ws" / "note.txt").read_text(
        encoding="utf-8"
    ) == CONTENT_SENTINEL
    # ...yet neither the content nor the API key reached the logs.
    assert KEY_SENTINEL not in caplog.text
    assert CONTENT_SENTINEL not in caplog.text
    # What IS logged: the tool call name and the run's outcome.
    assert "tool call: create_file" in caplog.text
    assert "agent run finished" in caplog.text
    assert "status=completed" in caplog.text
    assert "task_id=logging-test-task" in caplog.text


def test_service_logs_task_lifecycle_with_id(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client = FakeClient([text_response("instant answer")])
    service = make_service(tmp_path, client)
    with caplog.at_level(logging.DEBUG, logger="asa"):
        created = service.create_task("answer quickly")
        record = wait_for_status(service, created.id)
    assert record.status == "completed"
    assert f"task created: id={created.id}" in caplog.text
    assert f"task started: id={created.id}" in caplog.text
    assert (
        f"task finished: id={created.id} status=completed" in caplog.text
    )
    # The task text itself is not a log field.
    assert "answer quickly" not in caplog.text


# ----------------------------------------------------------------------
# Prompt-injection hardening: the rule is in the system prompt.
# (Prompt text only — see the module docstring.)
# ----------------------------------------------------------------------
def test_system_prompt_states_data_never_instructions() -> None:
    assert "never instructions" in SYSTEM_PROMPT
    assert "data" in SYSTEM_PROMPT
    assert "ignore previous instructions" in SYSTEM_PROMPT
    assert "do NOT" in SYSTEM_PROMPT
    assert "reveal secrets" in SYSTEM_PROMPT


# ----------------------------------------------------------------------
# Concurrency limit.
# ----------------------------------------------------------------------
class GatedClient:
    """First model call blocks until released; later calls answer."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)
        self.calls = 0
        self._lock = threading.Lock()
        self.first_call_started = threading.Event()
        self.release_first = threading.Event()

    def create(self, **kwargs):
        with self._lock:
            self.calls += 1
            number = self.calls
        if number == 1:
            self.first_call_started.set()
            assert self.release_first.wait(timeout=15)
            return text_response("first task answer")
        return text_response("subsequent answer")


def test_tasks_beyond_the_limit_wait_queued_then_run(
    tmp_path: Path,
) -> None:
    client = GatedClient()
    service = make_service(
        tmp_path, client, max_concurrent_tasks=1
    )
    first = service.create_task("first task")
    assert client.first_call_started.wait(timeout=5)

    second = service.create_task("second task")
    # Give a hypothetical buggy scheduler a chance to start it early.
    time.sleep(0.3)
    queued = service.get_task(second.id)
    assert queued is not None and queued.status == "queued"
    assert client.calls == 1  # the second task's agent never ran yet

    client.release_first.set()
    first_done = wait_for_status(service, first.id)
    second_done = wait_for_status(service, second.id)
    assert first_done.status == "completed"
    assert first_done.result_summary == "first task answer"
    assert second_done.status == "completed"
    assert second_done.result_summary == "subsequent answer"
    assert client.calls == 2


def test_cancelling_a_queued_task_means_it_never_runs(
    tmp_path: Path,
) -> None:
    client = GatedClient()
    service = make_service(
        tmp_path, client, max_concurrent_tasks=1
    )
    first = service.create_task("first task")
    assert client.first_call_started.wait(timeout=5)

    second = service.create_task("second task")
    queued = service.get_task(second.id)
    assert queued is not None and queued.status == "queued"

    cancelled = service.cancel_task(second.id)
    assert cancelled is not None and cancelled.status == "cancelled"

    client.release_first.set()
    first_done = wait_for_status(service, first.id)
    assert first_done.status == "completed"
    # Let the freed slot's pump run; the cancelled task must stay
    # cancelled and its agent must never have been invoked.
    time.sleep(0.3)
    still = service.get_task(second.id)
    assert still is not None and still.status == "cancelled"
    assert still.result_summary is not None
    assert "never ran" in still.result_summary
    assert client.calls == 1


# ----------------------------------------------------------------------
# Failure paths.
# ----------------------------------------------------------------------
def test_garbage_database_file_raises_task_store_error(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "tasks.db"
    db_path.write_bytes(b"this is not a sqlite database at all")
    workspace = Workspace(root=tmp_path / "ws", settings=Settings())
    with pytest.raises(TaskStoreError) as excinfo:
        TaskService(
            Settings(),
            client=FakeClient([]),
            workspace=workspace,
            db_path=db_path,
        )
    assert "task store is unusable" in str(excinfo.value)


def test_database_parent_is_a_file_raises_task_store_error(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory\n", encoding="utf-8")
    workspace = Workspace(root=tmp_path / "ws", settings=Settings())
    with pytest.raises(TaskStoreError):
        TaskService(
            Settings(),
            client=FakeClient([]),
            workspace=workspace,
            db_path=blocker / "tasks.db",
        )


class WorkspaceDeletingClient:
    """Deletes the workspace on its first call, then keeps reading."""

    def __init__(self, workspace_root: Path) -> None:
        self.chat = SimpleNamespace(completions=self)
        self._workspace_root = workspace_root
        self.calls = 0
        self.tool_feedback: list[str] = []

    def create(self, **kwargs):
        self.calls += 1
        for message in kwargs["messages"]:
            if message.get("role") == "tool":
                self.tool_feedback.append(message["content"])
        if self._workspace_root.exists():
            shutil.rmtree(self._workspace_root)
        return tool_response(
            "read_file",
            {"relative_path": "note.txt"},
            call_id=f"del-{self.calls}",
        )


def test_workspace_removed_mid_task_ends_in_terminal_status(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "ws"
    workspace = Workspace(root=workspace_root, settings=Settings())
    client = WorkspaceDeletingClient(workspace_root)
    service = TaskService(
        Settings(max_iterations=3),
        client=client,
        workspace=workspace,
        db_path=tmp_path / "tasks.db",
    )
    created = service.create_task("read note.txt, it keeps vanishing")
    record = wait_for_status(service, created.id)

    # Terminal, not stuck "running"; the thread did not die silently.
    assert record.status == "max_iterations"
    assert record.tool_calls == ["read_file"] * 3
    # The failure is visible in the record itself...
    assert record.result_summary is not None
    assert "NOT verified complete" in record.result_summary
    # ...and the model really was told the file/workspace was gone.
    assert any(
        "does not exist" in feedback for feedback in client.tool_feedback
    )
