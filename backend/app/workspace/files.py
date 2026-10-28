"""Confined workspace file operations (Milestone 2).

Every operation in this module is confined to a single workspace root
directory. The confinement rule is enforced by one resolver,
:meth:`Workspace._resolve`, through which *every* public operation passes:

1. The caller supplies a relative path. Backslashes are normalized to
   forward slashes so Windows-style separators cannot smuggle a traversal
   past the checks on any platform, and absolute paths (POSIX or
   drive-letter style) are rejected outright.
2. The candidate path is fully resolved with :meth:`Path.resolve`, which
   also resolves any symlinks in existing components.
3. The resolved absolute path must be the root itself or live beneath it.
   Because the check happens *after* resolution, ``..`` segments and
   symlinks pointing outside the root are both rejected.

Additional limits come from :class:`app.config.Settings`: a maximum file
size for reads and writes, a cap on directory-listing entries, and a cap
on search matches. Files are read as UTF-8 text; undecodable (binary)
content raises :class:`WorkspaceError` instead of returning garbage.

This module is framework-independent: it knows nothing about FastAPI or
the agent loop, so tools and tests can use it directly.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from app.config import Settings, get_settings

__all__ = [
    "Workspace",
    "WorkspaceError",
    "default_root",
    "list_files",
    "read_file",
    "create_file",
    "edit_file",
    "create_directory",
    "search_workspace",
]


class WorkspaceError(Exception):
    """Raised when a workspace operation is refused or cannot complete."""


# Drive-letter paths such as "C:/evil", "C:\\evil" or drive-relative "C:evil".
_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:")


def default_root() -> Path:
    """Return the repository's ``workspace/`` directory.

    This file lives at ``backend/app/workspace/files.py``, so the
    repository root is three parents up from the ``app`` package's parent.
    """
    return Path(__file__).resolve().parents[3] / "workspace"


class Workspace:
    """File operations confined to one workspace root directory.

    The root is injectable so tests (and future per-task workspaces) can
    point the same code at a temporary directory.
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        raw_root = Path(root) if root is not None else default_root()
        raw_root.mkdir(parents=True, exist_ok=True)
        # Resolve once so containment checks compare canonical paths.
        self._root = raw_root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # The single resolver every operation funnels through.
    # ------------------------------------------------------------------
    def _resolve(self, relative_path: str) -> Path:
        """Resolve ``relative_path`` inside the root or raise WorkspaceError."""
        if not isinstance(relative_path, str):
            raise WorkspaceError("path must be a string")
        # Normalize Windows separators so "a\\..\\evil" is treated as a
        # traversal on every platform, not just on Windows.
        normalized = relative_path.replace("\\", "/")
        if normalized.startswith("/") or _DRIVE_ABSOLUTE_RE.match(normalized):
            raise WorkspaceError(f"absolute paths are not allowed: {relative_path!r}")
        candidate = (self._root / normalized).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise WorkspaceError(
                f"path escapes the workspace: {relative_path!r}"
            )
        return candidate

    def _relative(self, path: Path) -> str:
        """Return ``path`` relative to the root, POSIX-style."""
        return path.relative_to(self._root).as_posix()

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve ``relative_path`` inside the root or raise WorkspaceError.

        Public wrapper around the single internal resolver, for callers
        outside this module (e.g. the sandbox runner) that need the same
        containment guarantee for a path they are about to act on.
        """
        return self._resolve(relative_path)

    # ------------------------------------------------------------------
    # Read operations.
    # ------------------------------------------------------------------
    def list_files(self, relative_dir: str = "") -> list[dict]:
        """List entries of a workspace directory (non-recursive).

        Returns dicts with ``name``, ``type`` (``"file"``/``"dir"``) and
        ``size`` in bytes (``None`` for directories), directories first,
        capped at ``settings.max_list_entries``.
        """
        target = self._resolve(relative_dir)
        if not target.exists():
            raise WorkspaceError(f"directory does not exist: {relative_dir!r}")
        if not target.is_dir():
            raise WorkspaceError(f"not a directory: {relative_dir!r}")
        entries: list[dict] = []
        with os.scandir(target) as it:
            for entry in it:
                is_dir = entry.is_dir(follow_symlinks=False)
                entries.append(
                    {
                        "name": entry.name,
                        "type": "dir" if is_dir else "file",
                        "size": None
                        if is_dir
                        else entry.stat(follow_symlinks=False).st_size,
                    }
                )
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return entries[: self._settings.max_list_entries]

    def read_file(self, relative_path: str) -> str:
        """Read a UTF-8 text file from the workspace.

        Raises WorkspaceError if the file is missing, exceeds
        ``settings.max_file_bytes``, or is not valid UTF-8 text.
        """
        target = self._resolve(relative_path)
        if not target.is_file():
            raise WorkspaceError(f"file does not exist: {relative_path!r}")
        size = target.stat().st_size
        if size > self._settings.max_file_bytes:
            raise WorkspaceError(
                f"file is {size} bytes, over the "
                f"{self._settings.max_file_bytes}-byte limit: {relative_path!r}"
            )
        raw = target.read_bytes()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(
                f"file is not valid UTF-8 text: {relative_path!r}"
            ) from exc

    def search_workspace(self, query: str) -> list[dict]:
        """Case-insensitive substring search across workspace text files.

        Returns dicts with ``path`` (relative, POSIX-style),
        ``line_number`` (1-based) and ``snippet``, capped at
        ``settings.max_search_matches``. Files that are oversize,
        non-UTF-8, or escape the root via symlinks are skipped.
        """
        if not query:
            raise WorkspaceError("search query must not be empty")
        needle = query.lower()
        matches: list[dict] = []
        cap = self._settings.max_search_matches
        for dirpath, dirnames, filenames in os.walk(self._root):
            # Never descend into symlinked directories or VCS internals.
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d != ".git" and not (Path(dirpath) / d).is_symlink()
            )
            for filename in sorted(filenames):
                if len(matches) >= cap:
                    return matches
                file_path = Path(dirpath) / filename
                if file_path.is_symlink():
                    continue
                try:
                    text = self.read_file(self._relative(file_path))
                except WorkspaceError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if needle in line.lower():
                        matches.append(
                            {
                                "path": self._relative(file_path),
                                "line_number": lineno,
                                "snippet": line.strip()[:200],
                            }
                        )
                        if len(matches) >= cap:
                            return matches
        return matches

    # ------------------------------------------------------------------
    # Write operations.
    # ------------------------------------------------------------------
    def _write_safely(self, target: Path, data: bytes) -> None:
        """Write ``data`` to ``target`` via a temp file + atomic rename."""
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=".tmp-", suffix=".part"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def create_file(self, relative_path: str, content: str) -> None:
        """Create or overwrite a text file inside the workspace.

        Parent directories are created as needed, but only inside the
        workspace (the resolver has already proven containment). Content
        larger than ``settings.max_file_bytes`` is rejected.
        """
        data = content.encode("utf-8")
        if len(data) > self._settings.max_file_bytes:
            raise WorkspaceError(
                f"content is {len(data)} bytes, over the "
                f"{self._settings.max_file_bytes}-byte limit: {relative_path!r}"
            )
        target = self._resolve(relative_path)
        if target == self._root:
            raise WorkspaceError("cannot write a file over the workspace root")
        if target.is_dir():
            raise WorkspaceError(f"path is a directory: {relative_path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_safely(target, data)

    def edit_file(self, relative_path: str, old_text: str, new_text: str) -> None:
        """Replace the first exact occurrence of ``old_text`` in a file.

        Raises WorkspaceError if ``old_text`` is not found or the edited
        result would exceed the size limit.
        """
        if not old_text:
            raise WorkspaceError("old_text must not be empty")
        content = self.read_file(relative_path)
        if old_text not in content:
            raise WorkspaceError(
                f"text to replace was not found in: {relative_path!r}"
            )
        updated = content.replace(old_text, new_text, 1)
        data = updated.encode("utf-8")
        if len(data) > self._settings.max_file_bytes:
            raise WorkspaceError(
                f"edited file would be {len(data)} bytes, over the "
                f"{self._settings.max_file_bytes}-byte limit: {relative_path!r}"
            )
        target = self._resolve(relative_path)
        self._write_safely(target, data)

    def create_directory(self, relative_path: str) -> None:
        """Create a directory (and missing parents) inside the workspace."""
        target = self._resolve(relative_path)
        if target.exists() and not target.is_dir():
            raise WorkspaceError(
                f"a file already exists at: {relative_path!r}"
            )
        target.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------
# Module-level convenience API bound to the default workspace root.
# ----------------------------------------------------------------------
def _default_workspace() -> Workspace:
    return Workspace()


def list_files(relative_dir: str = "") -> list[dict]:
    return _default_workspace().list_files(relative_dir)


def read_file(relative_path: str) -> str:
    return _default_workspace().read_file(relative_path)


def create_file(relative_path: str, content: str) -> None:
    _default_workspace().create_file(relative_path, content)


def edit_file(relative_path: str, old_text: str, new_text: str) -> None:
    _default_workspace().edit_file(relative_path, old_text, new_text)


def create_directory(relative_path: str) -> None:
    _default_workspace().create_directory(relative_path)


def search_workspace(query: str) -> list[dict]:
    return _default_workspace().search_workspace(query)
