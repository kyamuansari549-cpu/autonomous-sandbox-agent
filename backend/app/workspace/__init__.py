"""Confined workspace file operations (Milestone 2).

All file tools live in :mod:`app.workspace.files` and are confined to a
single workspace root by one path resolver; see that module's docstring
for the security model.
"""

from app.workspace.files import (
    Workspace,
    WorkspaceError,
    create_directory,
    create_file,
    default_root,
    edit_file,
    list_files,
    read_file,
    search_workspace,
)

__all__ = [
    "Workspace",
    "WorkspaceError",
    "create_directory",
    "create_file",
    "default_root",
    "edit_file",
    "list_files",
    "read_file",
    "search_workspace",
]
