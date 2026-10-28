"""Security and behaviour tests for the confined workspace (Milestone 2).

Every test runs against a temporary workspace root injected into
:class:`app.workspace.Workspace`, so the real project ``workspace/``
directory is never touched.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.workspace import Workspace, WorkspaceError


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    return Workspace(root=tmp_path / "ws")


@pytest.fixture()
def small_ws(tmp_path: Path) -> Workspace:
    """A workspace with tiny limits, so limit tests stay fast."""
    return Workspace(
        root=tmp_path / "ws",
        settings=Settings(max_file_bytes=16, max_list_entries=3, max_search_matches=2),
    )


# ----------------------------------------------------------------------
# Basic roundtrips
# ----------------------------------------------------------------------
def test_create_and_read_roundtrip(ws: Workspace) -> None:
    ws.create_file("hello.txt", "hello world")
    assert ws.read_file("hello.txt") == "hello world"


def test_create_file_makes_parent_directories(ws: Workspace) -> None:
    ws.create_file("a/b/c/deep.txt", "deep content")
    assert ws.read_file("a/b/c/deep.txt") == "deep content"


def test_create_file_overwrites(ws: Workspace) -> None:
    ws.create_file("f.txt", "first")
    ws.create_file("f.txt", "second")
    assert ws.read_file("f.txt") == "second"


def test_read_missing_file_raises(ws: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        ws.read_file("nope.txt")


def test_edit_file_replaces_first_occurrence_only(ws: Workspace) -> None:
    ws.create_file("f.txt", "one one one")
    ws.edit_file("f.txt", "one", "two")
    assert ws.read_file("f.txt") == "two one one"


def test_edit_file_not_found_raises(ws: Workspace) -> None:
    ws.create_file("f.txt", "hello")
    with pytest.raises(WorkspaceError):
        ws.edit_file("f.txt", "absent text", "replacement")
    # The failed edit must not have modified the file.
    assert ws.read_file("f.txt") == "hello"


def test_create_directory(ws: Workspace) -> None:
    ws.create_directory("sub/nested")
    entries = ws.list_files("")
    assert {"name": "sub", "type": "dir", "size": None} in entries
    assert ws.list_files("sub") == [
        {"name": "nested", "type": "dir", "size": None}
    ]


def test_list_files_reports_names_types_and_sizes(ws: Workspace) -> None:
    ws.create_file("b.txt", "12345")
    ws.create_file("a.txt", "xy")
    ws.create_directory("mid")
    entries = ws.list_files("")
    assert entries == [
        {"name": "mid", "type": "dir", "size": None},
        {"name": "a.txt", "type": "file", "size": 2},
        {"name": "b.txt", "type": "file", "size": 5},
    ]


def test_list_files_is_capped(small_ws: Workspace) -> None:
    for i in range(6):
        small_ws.create_file(f"f{i}.txt", "x")
    assert len(small_ws.list_files("")) == 3


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
def test_search_hit_is_case_insensitive_with_line_numbers(ws: Workspace) -> None:
    ws.create_file("notes.txt", "first line\nThe Quick Brown Fox\nlast line\n")
    ws.create_file("sub/other.txt", "nothing here\nQUICK again\n")
    results = ws.search_workspace("quick")
    assert [(r["path"], r["line_number"]) for r in results] == [
        ("notes.txt", 2),
        ("sub/other.txt", 2),
    ]
    assert results[0]["snippet"] == "The Quick Brown Fox"


def test_search_miss_returns_empty(ws: Workspace) -> None:
    ws.create_file("notes.txt", "some content")
    assert ws.search_workspace("zzz-not-present") == []


def test_search_results_are_capped(small_ws: Workspace) -> None:
    small_ws.create_file("f.txt", "hit\nhit\nhit\nhit\n")
    assert len(small_ws.search_workspace("hit")) == 2


def test_search_skips_binary_files(ws: Workspace, tmp_path: Path) -> None:
    (tmp_path / "ws" / "bin.dat").write_bytes(b"\xff\xfe\x00binary")
    ws.create_file("ok.txt", "findme")
    results = ws.search_workspace("findme")
    assert [r["path"] for r in results] == ["ok.txt"]


# ----------------------------------------------------------------------
# Path traversal and escapes — the heart of this milestone
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "evil",
    [
        "../evil.txt",
        "..\\evil.txt",
        "a/../../evil.txt",
        "sub/../../../evil.txt",
        "/etc/passwd",
        "C:/evil.txt",
        "C:\\evil.txt",
    ],
)
def test_traversal_rejected_for_read_and_create(ws: Workspace, evil: str) -> None:
    with pytest.raises(WorkspaceError):
        ws.read_file(evil)
    with pytest.raises(WorkspaceError):
        ws.create_file(evil, "pwned")
    with pytest.raises(WorkspaceError):
        ws.create_directory(evil)


def test_traversal_create_writes_nothing_outside(
    ws: Workspace, tmp_path: Path
) -> None:
    with pytest.raises(WorkspaceError):
        ws.create_file("../evil.txt", "pwned")
    assert not (tmp_path / "evil.txt").exists()


def test_symlink_file_escape_is_blocked(ws: Workspace, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")
    link = tmp_path / "ws" / "innocent.txt"
    link.symlink_to(outside)
    with pytest.raises(WorkspaceError):
        ws.read_file("innocent.txt")


def test_symlink_directory_escape_is_blocked(ws: Workspace, tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("top secret", encoding="utf-8")
    (tmp_path / "ws" / "linkdir").symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(WorkspaceError):
        ws.read_file("linkdir/secret.txt")
    with pytest.raises(WorkspaceError):
        ws.create_file("linkdir/new.txt", "pwned")
    assert not (outside_dir / "new.txt").exists()


# ----------------------------------------------------------------------
# Size limits and content safety
# ----------------------------------------------------------------------
def test_oversize_write_rejected(small_ws: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        small_ws.create_file("big.txt", "x" * 17)  # limit is 16 bytes
    with pytest.raises(WorkspaceError):
        small_ws.read_file("big.txt")  # nothing was written


def test_oversize_read_rejected(small_ws: Workspace, tmp_path: Path) -> None:
    # Written directly on disk, bypassing the API, then read via the API.
    (tmp_path / "ws" / "big.txt").write_text("x" * 100, encoding="utf-8")
    with pytest.raises(WorkspaceError):
        small_ws.read_file("big.txt")


def test_edit_that_would_exceed_limit_rejected(small_ws: Workspace) -> None:
    small_ws.create_file("f.txt", "short")
    with pytest.raises(WorkspaceError):
        small_ws.edit_file("f.txt", "short", "a much longer replacement text")
    assert small_ws.read_file("f.txt") == "short"


def test_binary_read_rejected(ws: Workspace, tmp_path: Path) -> None:
    (tmp_path / "ws" / "bin.dat").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xd8")
    with pytest.raises(WorkspaceError):
        ws.read_file("bin.dat")
