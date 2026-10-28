"""Tool schemas and dispatch for the agent loop (Milestones 4–5).

Two responsibilities live here:

1. :data:`TOOL_SCHEMAS` — the OpenAI-format function definitions sent to
   the model. Their parameter names and shapes mirror the public methods
   of :class:`app.workspace.Workspace` exactly, so what the model asks
   for is what the backend can execute.

2. :class:`ToolDispatcher` — the backend-side gatekeeper. The model only
   ever *requests* a tool by name with a JSON arguments object; the
   dispatcher validates the name against a fixed registry, validates the
   arguments (required keys present, correct types, no unexpected keys),
   and only then calls the confined :class:`Workspace` method. Every
   refusal is raised as :class:`ToolError` with a message the agent loop
   feeds back to the model verbatim — the model sees real failures, and
   no tool can run outside the registry or outside the workspace root.

Milestone 5 adds execution and inspection tools on the same terms:
``run_python_file`` and ``run_tests`` delegate to the Docker sandbox
runner's fixed command allowlist (see
:func:`app.sandbox.runner.validate_command`) — the model picks a
workspace path, never a command line — and ``git_status`` / ``git_diff``
run two fixed, read-only git commands in the workspace. There are no
git write operations (commit, push, delete) at all. The execution
backend is injectable so tests can substitute a local executor for
Docker; the default is always the real sandbox runner, and when Docker
is unavailable its :class:`SandboxUnavailableError` surfaces as a
:class:`ToolError` saying execution is unavailable — never as a
fabricated result.
"""

from __future__ import annotations

import json
import subprocess
from typing import Callable, Optional

from app.config import Settings, get_settings
from app.sandbox.runner import (
    SandboxError,
    SandboxResult,
    SandboxUnavailableError,
)
from app.sandbox.runner import run_command as _sandbox_run_command
from app.workspace import Workspace, WorkspaceError

__all__ = ["TOOL_SCHEMAS", "ToolDispatcher", "ToolError"]


# The execution backend signature: given the bound workspace and an
# argv tail (e.g. ["python", "-m", "pytest", "."]), return the run's
# real outcome. The default implementation is the Docker sandbox
# runner; tests inject a local executor with the same shape.
ExecutionRunner = Callable[[Workspace, list[str]], SandboxResult]


class ToolError(Exception):
    """Raised when a tool request is invalid or the tool itself fails."""


def _string_property(description: str) -> dict:
    return {"type": "string", "description": description}


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List the entries of a directory inside the workspace "
                "(non-recursive). Returns each entry's name, type "
                "(file or dir) and size in bytes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_dir": _string_property(
                        "Directory path relative to the workspace root. "
                        "Use an empty string for the root itself."
                    ),
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file from the workspace and return "
                "its exact contents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": _string_property(
                        "File path relative to the workspace root."
                    ),
                },
                "required": ["relative_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": (
                "Create a text file in the workspace with the given "
                "contents, overwriting it if it already exists. Parent "
                "directories are created as needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": _string_property(
                        "File path relative to the workspace root."
                    ),
                    "content": _string_property(
                        "The full text content to write to the file."
                    ),
                },
                "required": ["relative_path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace the first exact occurrence of old_text with "
                "new_text in an existing workspace file. Fails if "
                "old_text is not found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": _string_property(
                        "File path relative to the workspace root."
                    ),
                    "old_text": _string_property(
                        "The exact text to replace (first occurrence)."
                    ),
                    "new_text": _string_property(
                        "The replacement text."
                    ),
                },
                "required": ["relative_path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": (
                "Create a directory (and any missing parents) inside "
                "the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": _string_property(
                        "Directory path relative to the workspace root."
                    ),
                },
                "required": ["relative_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace",
            "description": (
                "Case-insensitive substring search across all text "
                "files in the workspace. Returns matching paths, line "
                "numbers and snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": _string_property(
                        "The text to search for (must not be empty)."
                    ),
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_file",
            "description": (
                "Run a Python file from the workspace inside the "
                "restricted Docker sandbox and return its real stdout, "
                "stderr and exit code. If sandboxed execution is "
                "unavailable, the tool returns an error instead of a "
                "result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": _string_property(
                        "Python file path relative to the workspace root."
                    ),
                },
                "required": ["relative_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run pytest inside the restricted Docker sandbox and "
                "return its real output and exit code. Optionally takes "
                "a test file or directory inside the workspace; omit "
                "the path to run all tests in the workspace. If "
                "sandboxed execution is unavailable, the tool returns "
                "an error instead of a result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": _string_property(
                        "Optional test file or directory path relative "
                        "to the workspace root."
                    ),
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": (
                "Show the working-tree status of the workspace's git "
                "repository (read-only; runs 'git status --porcelain')."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": (
                "Show unstaged changes in the workspace's git "
                "repository (read-only; runs 'git diff')."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


# Argument contract per tool: name -> {argument name: (type, required)}.
# Keys and Python types mirror the Workspace method signatures.
_ARG_SPECS: dict[str, dict[str, tuple[type, bool]]] = {
    "list_files": {"relative_dir": (str, False)},
    "read_file": {"relative_path": (str, True)},
    "create_file": {"relative_path": (str, True), "content": (str, True)},
    "edit_file": {
        "relative_path": (str, True),
        "old_text": (str, True),
        "new_text": (str, True),
    },
    "create_directory": {"relative_path": (str, True)},
    "search_workspace": {"query": (str, True)},
    "run_python_file": {"relative_path": (str, True)},
    "run_tests": {"relative_path": (str, False)},
    "git_status": {},
    "git_diff": {},
}


def _docker_execution_runner(
    workspace: Workspace, argv_tail: list[str]
) -> SandboxResult:
    """Default execution backend: the real Docker sandbox runner."""
    return _sandbox_run_command(workspace, argv_tail)


def _format_sandbox_result(label: str, result: SandboxResult) -> str:
    """Render one sandbox run's real outcome as text for the model."""
    if result.timed_out:
        headline = f"{label} timed out; there is no exit code."
    else:
        headline = f"{label} finished with exit code {result.exit_code}."
    parts = [headline]
    if result.stdout:
        parts.append(f"--- stdout ---\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"--- stderr ---\n{result.stderr.rstrip()}")
    if not result.stdout and not result.stderr:
        parts.append("(the command produced no output)")
    return "\n".join(parts)


class ToolDispatcher:
    """Validate and execute model tool requests against one Workspace."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        settings: Optional[Settings] = None,
        execution_runner: Optional[ExecutionRunner] = None,
    ) -> None:
        self._workspace = workspace
        self._settings = settings or get_settings()
        self._execution_runner = execution_runner or _docker_execution_runner
        self._handlers: dict[str, Callable[..., str]] = {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "create_file": self._create_file,
            "edit_file": self._edit_file,
            "create_directory": self._create_directory,
            "search_workspace": self._search_workspace,
            "run_python_file": self._run_python_file,
            "run_tests": self._run_tests,
            "git_status": self._git_status,
            "git_diff": self._git_diff,
        }

    # ------------------------------------------------------------------
    # Public entry point.
    # ------------------------------------------------------------------
    def dispatch(self, name: str, args: dict) -> str:
        """Run tool ``name`` with ``args`` and return a text result.

        Raises :class:`ToolError` for an unknown tool name, invalid
        arguments, or a :class:`WorkspaceError` from the workspace
        layer (its message is preserved so the real reason — traversal,
        size limit, missing file — reaches the model unchanged).
        """
        handler = self._handlers.get(name)
        if handler is None:
            known = ", ".join(sorted(self._handlers))
            raise ToolError(
                f"unknown tool: {name!r}. Available tools: {known}"
            )
        validated = self._validate_args(name, args)
        try:
            return handler(**validated)
        except SandboxUnavailableError as exc:
            # Execution being unavailable must reach the model as an
            # unmistakable error — never as an empty or fake result.
            raise ToolError(f"execution unavailable: {exc}") from exc
        except (WorkspaceError, SandboxError) as exc:
            raise ToolError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Argument validation.
    # ------------------------------------------------------------------
    def _validate_args(self, name: str, args: dict) -> dict:
        if not isinstance(args, dict):
            raise ToolError(
                f"arguments for tool {name!r} must be a JSON object, "
                f"got {type(args).__name__}"
            )
        spec = _ARG_SPECS[name]
        unexpected = sorted(set(args) - set(spec))
        if unexpected:
            raise ToolError(
                f"unexpected argument(s) for tool {name!r}: "
                + ", ".join(unexpected)
            )
        validated: dict = {}
        for arg_name, (arg_type, required) in spec.items():
            if arg_name not in args:
                if required:
                    raise ToolError(
                        f"missing required argument {arg_name!r} "
                        f"for tool {name!r}"
                    )
                continue
            value = args[arg_name]
            if not isinstance(value, arg_type):
                raise ToolError(
                    f"argument {arg_name!r} for tool {name!r} must be "
                    f"a {arg_type.__name__}, got {type(value).__name__}"
                )
            validated[arg_name] = value
        return validated

    # ------------------------------------------------------------------
    # Handlers: adapt Workspace results to text for the model.
    # ------------------------------------------------------------------
    def _list_files(self, relative_dir: str = "") -> str:
        entries = self._workspace.list_files(relative_dir)
        return json.dumps(entries, indent=2)

    def _read_file(self, relative_path: str) -> str:
        return self._workspace.read_file(relative_path)

    def _create_file(self, relative_path: str, content: str) -> str:
        self._workspace.create_file(relative_path, content)
        size = len(content.encode("utf-8"))
        return f"Created file {relative_path!r} ({size} bytes)."

    def _edit_file(
        self, relative_path: str, old_text: str, new_text: str
    ) -> str:
        self._workspace.edit_file(relative_path, old_text, new_text)
        return f"Edited file {relative_path!r}: replaced the given text."

    def _create_directory(self, relative_path: str) -> str:
        self._workspace.create_directory(relative_path)
        return f"Created directory {relative_path!r}."

    def _search_workspace(self, query: str) -> str:
        matches = self._workspace.search_workspace(query)
        return json.dumps(matches, indent=2)

    # ------------------------------------------------------------------
    # Execution handlers: the model picks a workspace path, never a
    # command line; the sandbox runner's allowlist does the rest.
    # ------------------------------------------------------------------
    def _run_python_file(self, relative_path: str) -> str:
        result = self._execution_runner(
            self._workspace, ["python", relative_path]
        )
        return _format_sandbox_result(
            f"python {relative_path}", result
        )

    def _run_tests(self, relative_path: str = "") -> str:
        target = relative_path or "."
        result = self._execution_runner(
            self._workspace, ["python", "-m", "pytest", target]
        )
        return _format_sandbox_result("pytest", result)

    # ------------------------------------------------------------------
    # Git handlers: two FIXED read-only commands, no shell, no writes.
    # ------------------------------------------------------------------
    def _git_status(self) -> str:
        return self._run_git(
            ["status", "--porcelain"],
            empty_message="git status: working tree clean, no changes.",
        )

    def _git_diff(self) -> str:
        return self._run_git(
            ["diff"],
            empty_message="git diff: no unstaged changes.",
        )

    def _run_git(self, fixed_args: list[str], empty_message: str) -> str:
        """Run one fixed git command in the workspace root.

        The argument list is chosen by the backend handlers above —
        never by the model — and is executed in argv form with no
        shell. Output is truncated to ``settings.max_output_bytes``.
        """
        try:
            completed = subprocess.run(
                ["git", *fixed_args],
                cwd=self._workspace.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except FileNotFoundError as exc:
            raise ToolError(
                "git is not installed on this machine; the git tools "
                "are unavailable"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolError("the git command timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ToolError(f"git command failed: {detail}")
        if not completed.stdout.strip():
            return empty_message
        return self._truncate(completed.stdout.rstrip("\n"))

    def _truncate(self, text: str) -> str:
        """Cap ``text`` at ``settings.max_output_bytes`` of UTF-8."""
        limit = self._settings.max_output_bytes
        encoded = text.encode("utf-8")
        if len(encoded) <= limit:
            return text
        cut = encoded[:limit].decode("utf-8", errors="replace")
        return cut + "\n[... truncated by the backend ...]"
