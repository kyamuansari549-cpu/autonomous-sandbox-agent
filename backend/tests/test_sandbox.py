"""Policy tests for the Docker sandbox runner (Milestone 3).

These tests are **daemon-free on purpose**: this environment has no
Docker, so they verify the security *policy* — the exact argument list
the backend would hand to Docker, path validation, timeout handling,
output truncation, and honest failure when Docker is missing — using
injected fake runners. They never claim a container actually ran; live
execution is verified separately on a Docker host (see docs/ROADMAP.md).
"""

import os
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.sandbox import (
    SandboxConfig,
    SandboxError,
    SandboxUnavailableError,
    build_command,
    run_python_file,
)
from app.workspace import Workspace, WorkspaceError


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    workspace = Workspace(root=tmp_path / "ws")
    workspace.create_file("hello.py", "print('hello')\n")
    return workspace


@pytest.fixture()
def config() -> SandboxConfig:
    return SandboxConfig.from_settings(Settings())


def flag_value(argv: list[str], flag: str) -> str:
    """Return the token immediately after ``flag`` in ``argv``."""
    return argv[argv.index(flag) + 1]


# ----------------------------------------------------------------------
# Command construction: safeguards present
# ----------------------------------------------------------------------
def test_command_is_docker_run_with_python_script(
    ws: Workspace, config: SandboxConfig
) -> None:
    argv = build_command(ws, "hello.py", config)
    assert argv[:2] == ["docker", "run"]
    assert argv[-3] == "autonomous-sandbox-agent:latest"
    assert argv[-2:] == ["python", "hello.py"]


def test_command_contains_every_safeguard(
    ws: Workspace, config: SandboxConfig
) -> None:
    argv = build_command(ws, "hello.py", config)
    assert "--rm" in argv
    assert flag_value(argv, "--network") == "none"
    assert flag_value(argv, "--memory") == "256m"
    assert flag_value(argv, "--cpus") == "0.5"
    assert flag_value(argv, "--pids-limit") == "64"
    assert flag_value(argv, "--cap-drop") == "ALL"
    assert flag_value(argv, "--security-opt") == "no-new-privileges"
    assert "--read-only" in argv
    assert flag_value(argv, "--tmpfs") == "/tmp:rw,size=64m"
    assert flag_value(argv, "--user") == "10001:10001"


def test_command_uses_config_values(ws: Workspace) -> None:
    custom = SandboxConfig(
        image="example/image:v1",
        memory="512m",
        cpus="1.5",
        pids_limit=32,
        timeout_seconds=9,
    )
    argv = build_command(ws, "hello.py", custom)
    assert flag_value(argv, "--memory") == "512m"
    assert flag_value(argv, "--cpus") == "1.5"
    assert flag_value(argv, "--pids-limit") == "32"
    assert argv[-3] == "example/image:v1"


def test_config_defaults_match_spec() -> None:
    config = SandboxConfig.from_settings(Settings())
    assert config.image == "autonomous-sandbox-agent:latest"
    assert config.memory == "256m"
    assert config.cpus == "0.5"
    assert config.pids_limit == 64
    assert config.timeout_seconds == 30


# ----------------------------------------------------------------------
# Command construction: forbidden items absent
# ----------------------------------------------------------------------
def test_command_has_no_forbidden_items(
    ws: Workspace, config: SandboxConfig
) -> None:
    argv = build_command(ws, "hello.py", config)
    assert "--privileged" not in argv
    assert "-e" not in argv
    assert "--env" not in argv
    assert "--env-file" not in argv
    assert all("docker.sock" not in token for token in argv)
    assert "host" not in argv  # no host networking / host anything
    assert flag_value(argv, "--network") == "none"


def test_workspace_mount_is_the_only_mount(
    ws: Workspace, config: SandboxConfig
) -> None:
    argv = build_command(ws, "hello.py", config)
    assert argv.count("-v") == 1
    assert "--volume" not in argv
    assert "--mount" not in argv
    assert flag_value(argv, "-v") == f"{ws.root}:/work"


def test_script_in_subdirectory_uses_posix_relative_path(
    ws: Workspace, config: SandboxConfig
) -> None:
    ws.create_file("sub/prog.py", "print('x')\n")
    argv = build_command(ws, "sub/prog.py", config)
    assert argv[-1] == "sub/prog.py"


# ----------------------------------------------------------------------
# Path validation through the workspace resolver
# ----------------------------------------------------------------------
def test_script_outside_workspace_is_rejected(
    ws: Workspace, config: SandboxConfig
) -> None:
    with pytest.raises(WorkspaceError):
        build_command(ws, "../outside.py", config)


def test_absolute_script_path_is_rejected(
    ws: Workspace, config: SandboxConfig
) -> None:
    with pytest.raises(WorkspaceError):
        build_command(ws, "/etc/passwd", config)


def test_symlink_escaping_workspace_is_rejected(
    ws: Workspace, config: SandboxConfig, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("print('escaped')\n", encoding="utf-8")
    link = ws.root / "link.py"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform")
    with pytest.raises(WorkspaceError):
        build_command(ws, "link.py", config)


def test_workspace_root_is_not_a_script(
    ws: Workspace, config: SandboxConfig
) -> None:
    with pytest.raises(SandboxError):
        build_command(ws, "", config)


# ----------------------------------------------------------------------
# Execution behaviour via fake runners (no daemon involved)
# ----------------------------------------------------------------------
def _completed(argv: list[str], returncode: int, stdout: str, stderr: str):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_run_returns_real_output_and_exit_code(ws: Workspace) -> None:
    def fake_runner(argv, **kwargs):
        return _completed(argv, 3, "some stdout", "some stderr")

    result = run_python_file(ws, "hello.py", runner=fake_runner)
    assert result.exit_code == 3
    assert result.stdout == "some stdout"
    assert result.stderr == "some stderr"
    assert result.timed_out is False
    assert result.duration_seconds >= 0


def test_run_passes_timeout_to_runner(ws: Workspace) -> None:
    seen: dict = {}

    def fake_runner(argv, **kwargs):
        seen.update(kwargs)
        return _completed(argv, 0, "", "")

    run_python_file(ws, "hello.py", runner=fake_runner)
    assert seen["timeout"] == 30


def test_run_timeout_returns_timed_out_result(ws: Workspace) -> None:
    def fake_runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=argv,
            timeout=kwargs.get("timeout", 30),
            output="partial stdout",
            stderr="partial stderr",
        )

    result = run_python_file(ws, "hello.py", runner=fake_runner)
    assert result.timed_out is True
    assert result.exit_code is None
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"


def test_run_missing_docker_raises_unavailable(ws: Workspace) -> None:
    def fake_runner(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "docker")

    with pytest.raises(SandboxUnavailableError):
        run_python_file(ws, "hello.py", runner=fake_runner)


def test_run_truncates_oversized_output(ws: Workspace) -> None:
    def fake_runner(argv, **kwargs):
        return _completed(argv, 0, "x" * 500, "y" * 500)

    result = run_python_file(
        ws,
        "hello.py",
        settings=Settings(max_output_bytes=40),
        runner=fake_runner,
    )
    assert result.stdout == "x" * 40
    assert result.stderr == "y" * 40


def test_run_missing_script_raises_without_running(ws: Workspace) -> None:
    def forbidden_runner(argv, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("runner must not be called for a missing script")

    with pytest.raises(SandboxError):
        run_python_file(ws, "nope.py", runner=forbidden_runner)
