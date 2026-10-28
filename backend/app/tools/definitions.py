"""Tool schemas and dispatch for the agent loop (Milestone 4).

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
"""

from __future__ import annotations

import json
from typing import Callable

from app.workspace import Workspace, WorkspaceError

__all__ = ["TOOL_SCHEMAS", "ToolDispatcher", "ToolError"]


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
}


class ToolDispatcher:
    """Validate and execute model tool requests against one Workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._handlers: dict[str, Callable[..., str]] = {
            "list_files": self._list_files,
            "read_file": self._read_file,
            "create_file": self._create_file,
            "edit_file": self._edit_file,
            "create_directory": self._create_directory,
            "search_workspace": self._search_workspace,
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
        except WorkspaceError as exc:
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
