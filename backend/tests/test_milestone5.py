"""Tests for Milestone 5: execution tools, task service, end-to-end.

Two execution backends appear in this file, and the difference matters:

* The **real** Docker sandbox runner. This environment has no Docker,
  so tests against it assert the honest outcome: a ``ToolError`` /
  fed-back error saying execution is unavailable. Nothing is mocked
  into a fake success.
* A **local executor stand-in** (clearly marked below) that runs the
  allowlist-validated command with the current interpreter in the
  workspace directory. It exists so the agent's fix-a-bug loop can be
  verified end to end with *real* pytest output; it provides no
  isolation and is never used outside these tests.

The model is always the scripted ``FakeClient`` from
``test_agent_loop`` — no test performs a network call.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import run_agent
from app.config import Settings
from app.main import create_app
from app.sandbox import SandboxError, SandboxResult, validate_command
from app.services.task_service import TaskService
from app.tools.definitions import ToolDispatcher, ToolError
from app.workspace import Workspace, WorkspaceError
from test_agent_loop import (
    FakeClient,
    FakeMessage,
    FakeToolCall,
    text_response,
    tool_messages_sent,
    tool_response,
)


# ----------------------------------------------------------------------
# Local executor: TEST STAND-IN for the Docker sandbox.
# ----------------------------------------------------------------------
def local_executor(workspace: Workspace, argv_tail: list[str]) -> SandboxResult:
    """Run an allowlist-validated command locally (no isolation).

    Validation goes through the same :func:`validate_command` the
    Docker runner uses, so a command the sandbox would refuse is
    refused here too. Only the container is missing — which is exactly
    why this stand-in lives in the tests and nowhere else.
    """
    container_argv = validate_command(workspace, argv_tail)
    argv = [sys.executable, *container_argv[1:]]
    # PYTHONDONTWRITEBYTECODE: repeated runs share this workspace, and
    # a stale .pyc whose (mtime, size) happens to match an edited file
    # would make a later run execute the OLD code — a real trap the
    # fresh-container sandbox does not have, removed here so the
    # stand-in stays faithful.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(
            stdout=exc.output.decode() if isinstance(exc.output, bytes) else (exc.output or ""),
            stderr=exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            exit_code=None,
            timed_out=True,
            duration_seconds=time.monotonic() - started,
        )
    return SandboxResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        timed_out=False,
        duration_seconds=time.monotonic() - started,
    )


# ----------------------------------------------------------------------
# Fixtures and helpers.
# ----------------------------------------------------------------------
@pytest.fixture()
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(root=tmp_path / "ws", settings=Settings())


@pytest.fixture()
def dispatcher(workspace: Workspace) -> ToolDispatcher:
    """A dispatcher on the REAL sandbox runner (no Docker here)."""
    return ToolDispatcher(workspace, settings=Settings())


def run(client, dispatcher, **kwargs):
    settings = kwargs.pop("settings", Settings())
    return run_agent(
        task=kwargs.pop("task", "do the thing"),
        client=client,
        model="test-model",
        dispatcher=dispatcher,
        settings=settings,
        **kwargs,
    )


def wait_for_status(service: TaskService, task_id: str, timeout=10.0):
    """Poll a task record until it reaches a final status."""
    deadline = time.monotonic() + timeout
    final = ("completed", "max_iterations", "failed", "cancelled")
    while time.monotonic() < deadline:
        record = service.get_task(task_id)
        assert record is not None
        if record.status in final:
            return record
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not finish in {timeout}s")


# ----------------------------------------------------------------------
# Execution tools in THIS environment: honestly unavailable.
# ----------------------------------------------------------------------
def test_run_tests_tool_reports_sandbox_unavailable(dispatcher) -> None:
    with pytest.raises(ToolError, match="unavailable"):
        dispatcher.dispatch("run_tests", {})


def test_run_python_file_tool_reports_sandbox_unavailable(
    dispatcher, workspace: Workspace
) -> None:
    workspace.create_file("prog.py", "print('hi')\n")
    with pytest.raises(ToolError, match="unavailable"):
        dispatcher.dispatch("run_python_file", {"relative_path": "prog.py"})


# ----------------------------------------------------------------------
# Command allowlist.
# ----------------------------------------------------------------------
def test_allowlist_accepts_the_two_command_shapes(
    workspace: Workspace,
) -> None:
    workspace.create_file("prog.py", "print(1)\n")
    workspace.create_file("test_prog.py", "def test_ok():\n    assert True\n")
    assert validate_command(workspace, ["python", "prog.py"]) == [
        "python",
        "prog.py",
    ]
    assert validate_command(workspace, ["python", "-m", "pytest", "."]) == [
        "python",
        "-m",
        "pytest",
        ".",
    ]
    assert validate_command(
        workspace, ["python", "-m", "pytest", "test_prog.py"]
    ) == ["python", "-m", "pytest", "test_prog.py"]


@pytest.mark.parametrize(
    "bad_tail",
    [
        ["python", "../outside.py"],  # file outside the workspace
        ["python", "-m", "pytest", "../outside"],  # pytest path outside
        ["python", "-m", "pytest", "-p", "no:cacheprovider"],  # flag + plugin
        ["python", "-m", "pytest", "--collect-only"],  # flag as the target
        ["python", "-m", "pytest", "test_prog.py", "--tb=short"],  # extra flag
        ["python", "-c", "print(1)"],  # inline code flag
        ["python", "-m", "pip", "install", "requests"],  # another module
        ["python", "prog.py", ";", "rm", "-rf", "."],  # shell-style chaining
        ["bash", "prog.py"],  # not python at all
        ["python", "notes.txt"],  # not a Python file
    ],
)
def test_allowlist_rejects_everything_else(
    workspace: Workspace, bad_tail: list[str]
) -> None:
    workspace.create_file("prog.py", "print(1)\n")
    with pytest.raises((SandboxError, WorkspaceError)):
        validate_command(workspace, bad_tail)


def test_flag_injection_is_a_sandbox_error(workspace: Workspace) -> None:
    # Flag-shaped attacks are policy refusals (SandboxError), distinct
    # from paths that escape the workspace (WorkspaceError).
    with pytest.raises(SandboxError):
        validate_command(workspace, ["python", "-m", "pytest", "--collect-only"])
    with pytest.raises(SandboxError):
        validate_command(workspace, ["python", "-m", "pytest", "-p", "x"])


# ----------------------------------------------------------------------
# Git tools (read-only) against a real temporary git repository.
# ----------------------------------------------------------------------
def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


@pytest.fixture()
def git_dispatcher(tmp_path: Path) -> ToolDispatcher:
    root = tmp_path / "ws"
    root.mkdir()
    _git(root, "init", "-q")
    workspace = Workspace(root=root, settings=Settings())
    return ToolDispatcher(workspace, settings=Settings())


def test_git_status_clean_repo(git_dispatcher: ToolDispatcher) -> None:
    assert "clean" in git_dispatcher.dispatch("git_status", {})


def test_git_status_shows_untracked_file(
    git_dispatcher: ToolDispatcher,
) -> None:
    workspace_root = Path(git_dispatcher._workspace.root)
    (workspace_root / "new_file.txt").write_text("hello\n", encoding="utf-8")
    output = git_dispatcher.dispatch("git_status", {})
    assert "?? new_file.txt" in output


def test_git_diff_shows_real_change(git_dispatcher: ToolDispatcher) -> None:
    root = Path(git_dispatcher._workspace.root)
    tracked = root / "tracked.txt"
    tracked.write_text("line one\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(
        root,
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    tracked.write_text("line one\nline two\n", encoding="utf-8")
    output = git_dispatcher.dispatch("git_diff", {})
    assert "+line two" in output


def test_git_tools_fail_honestly_outside_a_repo(dispatcher) -> None:
    with pytest.raises(ToolError, match="git command failed"):
        dispatcher.dispatch("git_status", {})


def test_git_write_operations_do_not_exist(dispatcher) -> None:
    for name in ("git_commit", "git_push", "git_add"):
        with pytest.raises(ToolError, match="unknown tool"):
            dispatcher.dispatch(name, {})


# ----------------------------------------------------------------------
# END-TO-END: the agent fixes a real bug using real pytest output.
# (Fake model + local executor stand-in; the pytest runs are real.)
# ----------------------------------------------------------------------
BUGGY_CALCULATOR = "def add(a, b):\n    return a - b\n"
FIXED_CALCULATOR = (
    "def add(a, b):\n    return a + b  # bug fix: add, not subtract\n"
)
CALCULATOR_TESTS = (
    "from calculator import add\n"
    "\n"
    "\n"
    "def test_add_positive():\n"
    "    assert add(2, 3) == 5\n"
    "\n"
    "\n"
    "def test_add_negative():\n"
    "    assert add(-1, -1) == -2\n"
)


def test_end_to_end_agent_fixes_bug_via_real_test_feedback(
    workspace: Workspace,
) -> None:
    dispatcher = ToolDispatcher(
        workspace, settings=Settings(), execution_runner=local_executor
    )
    client = FakeClient(
        [
            tool_response(
                "create_file",
                {"relative_path": "calculator.py", "content": BUGGY_CALCULATOR},
                call_id="c1",
            ),
            tool_response(
                "create_file",
                {"relative_path": "test_calculator.py", "content": CALCULATOR_TESTS},
                call_id="c2",
            ),
            tool_response("run_tests", {}, call_id="c3"),
            tool_response(
                "edit_file",
                {
                    "relative_path": "calculator.py",
                    "old_text": "return a - b",
                    "new_text": "return a + b  # bug fix: add, not subtract",
                },
                call_id="c4",
            ),
            tool_response("run_tests", {}, call_id="c5"),
            text_response("Fixed add(); the test suite now passes."),
        ]
    )
    result = run(
        client, dispatcher, task="Build a calculator and make its tests pass"
    )

    assert result.status == "completed"
    assert result.tool_calls == [
        "create_file",
        "create_file",
        "run_tests",
        "edit_file",
        "run_tests",
    ]

    # The feedback after the FIRST run_tests call (seen by the model in
    # its 4th request) is the real pytest failure: exit code 1, the
    # failing test names, and pytest's own "failed" summary.
    first_run_feedback = "\n".join(
        m["content"] for m in tool_messages_sent(client, call_index=3)
    )
    assert "exit code 1" in first_run_feedback
    assert "test_add_positive" in first_run_feedback
    assert "failed" in first_run_feedback

    # The feedback after the SECOND run_tests call reports a real pass.
    second_run_feedback = "\n".join(
        m["content"] for m in tool_messages_sent(client, call_index=5)
    )
    assert "exit code 0" in second_run_feedback
    assert "passed" in second_run_feedback

    # And the file on disk really is the fixed version.
    assert (
        workspace.root / "calculator.py"
    ).read_text(encoding="utf-8") == FIXED_CALCULATOR


# ----------------------------------------------------------------------
# END-TO-END honesty: with the REAL sandbox runner (unavailable here),
# the error reaches the model and no success is invented.
# ----------------------------------------------------------------------
def test_end_to_end_execution_unavailable_is_reported_honestly(
    dispatcher,
) -> None:
    client = FakeClient(
        [
            tool_response("run_tests", {}, call_id="c1"),
            text_response(
                "I could not run the tests: sandboxed execution is "
                "unavailable on this machine, so nothing is verified."
            ),
        ]
    )
    result = run(client, dispatcher, task="Run the project tests")
    assert result.status == "completed"
    assert result.tool_calls == ["run_tests"]
    feedback = tool_messages_sent(client, call_index=1)
    assert len(feedback) == 1
    assert "unavailable" in feedback[0]["content"]


# ----------------------------------------------------------------------
# Task service.
# ----------------------------------------------------------------------
def make_service(tmp_path: Path, client, **settings_kwargs) -> TaskService:
    workspace = Workspace(root=tmp_path / "ws", settings=Settings())
    return TaskService(
        Settings(**settings_kwargs),
        client=client,
        workspace=workspace,
        db_path=tmp_path / "tasks.db",
    )


def test_task_service_completes_a_task(tmp_path: Path) -> None:
    client = FakeClient(
        [
            tool_response(
                "create_file",
                {"relative_path": "note.txt", "content": "from the agent\n"},
            ),
            text_response("note.txt created."),
        ]
    )
    service = make_service(tmp_path, client)
    created = service.create_task("write a note file")
    record = wait_for_status(service, created.id)
    assert record.status == "completed"
    assert record.result_summary == "note.txt created."
    assert record.tool_calls == ["create_file"]
    assert record.error is None
    written = tmp_path / "ws" / "note.txt"
    assert written.read_text(encoding="utf-8") == "from the agent\n"


class SlowClient:
    """Always requests list_files, slowly — never finishes unaided."""

    def __init__(self, delay: float = 0.05) -> None:
        self._delay = delay
        self._count = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        time.sleep(self._delay)
        self._count += 1
        message = FakeMessage(
            content=None,
            tool_calls=[
                FakeToolCall(f"slow-{self._count}", "list_files", "{}")
            ],
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_task_service_cancels_a_running_task(tmp_path: Path) -> None:
    service = make_service(
        tmp_path, SlowClient(), max_iterations=100_000
    )
    created = service.create_task("loop forever")
    # Wait until the task is actually running before cancelling.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        current = service.get_task(created.id)
        assert current is not None
        if current.status == "running":
            break
        time.sleep(0.02)
    service.cancel_task(created.id)
    record = wait_for_status(service, created.id)
    assert record.status == "cancelled"


def test_task_service_persists_records_in_sqlite(tmp_path: Path) -> None:
    client = FakeClient([text_response("instant answer")])
    service = make_service(tmp_path, client)
    created = service.create_task("answer quickly")
    finished = wait_for_status(service, created.id)
    assert finished.status == "completed"

    # A brand-new service on the same database file sees the record.
    reopened = make_service(tmp_path, FakeClient([]))
    stored = reopened.get_task(created.id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.result_summary == "instant answer"
    assert [r.id for r in reopened.list_tasks()] == [created.id]


def test_task_service_refuses_to_create_without_llm(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "ws", settings=Settings())
    service = TaskService(
        Settings(groq_api_key="", groq_model=""),
        workspace=workspace,
        db_path=tmp_path / "tasks.db",
    )
    from app.agent.llm_client import LLMNotConfiguredError

    with pytest.raises(LLMNotConfiguredError):
        service.create_task("anything")
    assert service.list_tasks() == []


# ----------------------------------------------------------------------
# Task API.
# ----------------------------------------------------------------------
def test_post_tasks_returns_503_without_llm_config() -> None:
    app = create_app(Settings(groq_api_key="", groq_model=""))
    client = TestClient(app)
    response = client.post("/tasks", json={"task": "do something"})
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_task_api_round_trip_and_cancel(tmp_path: Path) -> None:
    from app.api.tasks import get_task_service

    fake = FakeClient(
        [
            tool_response(
                "create_file",
                {"relative_path": "api.txt", "content": "via api\n"},
            ),
            text_response("api task done"),
        ]
    )
    service = make_service(tmp_path, fake)
    app = create_app(Settings())
    app.dependency_overrides[get_task_service] = lambda: service
    client = TestClient(app)

    created = client.post("/tasks", json={"task": "make api.txt"})
    assert created.status_code == 200
    body = created.json()
    task_id = body["task_id"]
    assert body["status"] in ("queued", "running")

    deadline = time.monotonic() + 10.0
    record = None
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        record = response.json()
        if record["status"] == "completed":
            break
        time.sleep(0.05)
    assert record is not None and record["status"] == "completed"
    assert record["result_summary"] == "api task done"
    assert record["tool_calls"] == ["create_file"]

    listing = client.get("/tasks")
    assert listing.status_code == 200
    assert [r["task_id"] for r in listing.json()] == [task_id]

    # Cancelling a finished task is a no-op returning the record.
    cancelled = client.post(f"/tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "completed"


def test_task_api_unknown_task_is_404() -> None:
    client = TestClient(create_app(Settings()))
    assert client.get("/tasks/does-not-exist").status_code == 404
    assert client.post("/tasks/does-not-exist/cancel").status_code == 404
