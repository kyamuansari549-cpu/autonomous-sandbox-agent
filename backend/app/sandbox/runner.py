"""Docker sandbox runner (Milestone 3).

Generated code is executed by asking the local Docker daemon to run one
throwaway container built from ``sandbox/Dockerfile``. The security model
is deliberately boring:

* :func:`build_command` returns a **fixed** argument list. The caller
  (agent loop / tool layer) chooses only *which workspace script* runs;
  it cannot add flags, images, mounts, environment variables, or network
  access. The list is executed with ``subprocess.run`` in argv form —
  ``shell=True`` is never used anywhere in this module.
* The script path is validated through the Milestone 2 workspace
  resolver (:meth:`app.workspace.Workspace.resolve_path`), so a path
  that escapes the workspace (``..``, absolute, symlink) is rejected
  before Docker is ever invoked.
* The *only* bind mount is the workspace root at ``/work``. The Docker
  socket is never mounted, the container is never privileged, and **no
  environment variables are passed in** (there is not a single ``-e``
  flag), so backend secrets such as ``GROQ_API_KEY`` cannot leak into
  executed code.
* Limits come from backend :class:`app.config.Settings` (image name,
  memory, CPUs, PID count, wall-clock timeout) — never from the model.

Cleanup and timeouts: ``--rm`` removes the container when it exits.
The subprocess timeout terminates the ``docker`` CLI process itself
(``subprocess.run`` kills and reaps it), which ends the run from the
backend's point of view; no separate ``docker rm -f`` is issued. Output
is truncated to ``Settings.max_output_bytes`` per stream.

If the ``docker`` executable is not installed at all, :func:`run_python_file`
raises :class:`SandboxUnavailableError`. It never invents a result:
either a container really ran and its real output is returned, or the
caller gets an exception / a ``timed_out`` result.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional

from app.config import Settings, get_settings
from app.workspace import Workspace

__all__ = [
    "SandboxConfig",
    "SandboxError",
    "SandboxResult",
    "SandboxUnavailableError",
    "build_command",
    "run_command",
    "run_python_file",
    "validate_command",
]

# The sandbox user created by sandbox/Dockerfile (uid/gid 10001). Pinned
# on the command line as well, so the value holds even if the image is
# rebuilt differently.
SANDBOX_USER = "10001:10001"
CONTAINER_WORKDIR = "/work"


class SandboxError(Exception):
    """Raised when a sandbox request is refused or malformed."""


class SandboxUnavailableError(SandboxError):
    """Raised when Docker itself is unavailable (e.g. CLI not installed)."""


@dataclass(frozen=True)
class SandboxConfig:
    """Fixed per-run sandbox policy, derived from backend Settings."""

    image: str
    memory: str
    cpus: str
    pids_limit: int
    timeout_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxConfig":
        return cls(
            image=settings.sandbox_image,
            memory=settings.sandbox_memory,
            cpus=settings.sandbox_cpus,
            pids_limit=settings.sandbox_pids_limit,
            timeout_seconds=settings.sandbox_timeout_seconds,
        )


@dataclass
class SandboxResult:
    """The real outcome of one container run.

    ``exit_code`` is ``None`` when the process never produced one —
    i.e. the run timed out. Fabricating a code in that case would be a
    lie, so it stays ``None`` and ``timed_out`` explains why.
    """

    stdout: str
    stderr: str
    exit_code: Optional[int]
    timed_out: bool
    duration_seconds: float


# A callable with subprocess.run's relevant signature. Injectable so the
# policy in this module can be tested without a Docker daemon.
Runner = Callable[..., subprocess.CompletedProcess]


def _container_script_path(workspace: Workspace, script_relpath: str) -> str:
    """Validate ``script_relpath`` and return its in-container path form.

    Validation goes through the workspace resolver, so traversal,
    absolute paths, and symlink escapes raise :class:`WorkspaceError`
    before Docker is involved.
    """
    resolved = workspace.resolve_path(script_relpath)
    if resolved == workspace.root:
        raise SandboxError("script path must name a file, not the workspace root")
    return resolved.relative_to(workspace.root).as_posix()


def _docker_argv_prefix(workspace: Workspace, config: SandboxConfig) -> list[str]:
    """The fixed ``docker run`` argument list, ending with the image name.

    Every safeguard flag is hard-coded here. The only variable parts are
    the policy values from :class:`SandboxConfig` (themselves sourced
    from backend settings) and the workspace mount.
    """
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        config.memory,
        "--cpus",
        config.cpus,
        "--pids-limit",
        str(config.pids_limit),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=64m",
        "-v",
        f"{workspace.root}:{CONTAINER_WORKDIR}",
        "--user",
        SANDBOX_USER,
        config.image,
    ]


def build_command(
    workspace: Workspace,
    script_relpath: str,
    config: SandboxConfig,
) -> list[str]:
    """Build the exact ``docker run`` argv for running one Python file.

    The result is the fixed prefix from :func:`_docker_argv_prefix`
    followed by ``["python", <validated script path>]``.
    """
    script = _container_script_path(workspace, script_relpath)
    return _docker_argv_prefix(workspace, config) + ["python", script]


def _container_pytest_target(workspace: Workspace, target: str) -> str:
    """Validate a pytest target and return its in-container path form.

    Unlike a script, a pytest target may be the workspace root itself
    (returned as ``"."``), a directory, or a single test file.
    """
    if target in ("", "."):
        return "."
    resolved = workspace.resolve_path(target)
    if resolved == workspace.root:
        return "."
    return resolved.relative_to(workspace.root).as_posix()


def validate_command(workspace: Workspace, argv_tail) -> list[str]:
    """Validate a requested command tail against the fixed allowlist.

    Only two command shapes are permitted, and this function returns
    their normalized in-container form:

    * ``["python", <file.py inside the workspace>]``
    * ``["python", "-m", "pytest", <path inside the workspace>]``
      (the pytest path may also be ``"."`` for the whole workspace)

    Everything else — another program, extra flags (a pytest target
    starting with ``-`` included), or a path escaping the workspace —
    raises :class:`SandboxError` (or :class:`WorkspaceError` from the
    resolver). The model may *request* a command, but it can never
    extend this list.
    """
    if not isinstance(argv_tail, (list, tuple)) or not argv_tail:
        raise SandboxError("command must be a non-empty list of arguments")
    argv = list(argv_tail)
    if any(not isinstance(token, str) or token == "" for token in argv):
        raise SandboxError("command arguments must be non-empty strings")
    if argv[0] != "python":
        raise SandboxError(
            f"only 'python' commands may run in the sandbox, got {argv[0]!r}"
        )
    if len(argv) == 2:
        target = argv[1]
        if target.startswith("-"):
            raise SandboxError(f"flags are not allowed: {target!r}")
        script = _container_script_path(workspace, target)
        if not script.endswith(".py"):
            raise SandboxError(f"not a Python file: {target!r}")
        return ["python", script]
    if len(argv) == 4 and argv[1] == "-m" and argv[2] == "pytest":
        target = argv[3]
        if target.startswith("-"):
            raise SandboxError(f"pytest flags are not allowed: {target!r}")
        return [
            "python",
            "-m",
            "pytest",
            _container_pytest_target(workspace, target),
        ]
    raise SandboxError(
        "command is not in the sandbox allowlist; only "
        "['python', <file.py>] and ['python', '-m', 'pytest', <path>] "
        "are permitted"
    )


def _as_text(value: object) -> str:
    """Normalize captured output (str, bytes, or None) to text."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate ``text`` to at most ``max_bytes`` of UTF-8."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace")


def _execute(
    argv: list[str],
    config: SandboxConfig,
    settings: Settings,
    runner: Optional[Runner],
) -> SandboxResult:
    """Hand one fully built ``docker run`` argv to the subprocess runner.

    Shared by :func:`run_python_file` and :func:`run_command`. A missing
    ``docker`` executable raises :class:`SandboxUnavailableError`; a
    timeout returns a ``timed_out`` result with the partial output and
    ``exit_code=None`` — neither outcome is ever disguised as a
    successful run.
    """
    run = runner or subprocess.run
    started = time.monotonic()
    try:
        completed = run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise SandboxUnavailableError(
            "the 'docker' executable was not found on this machine; "
            "sandboxed execution is unavailable until Docker is installed "
            "and running"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(
            stdout=_truncate(_as_text(exc.output), settings.max_output_bytes),
            stderr=_truncate(_as_text(exc.stderr), settings.max_output_bytes),
            exit_code=None,
            timed_out=True,
            duration_seconds=time.monotonic() - started,
        )
    return SandboxResult(
        stdout=_truncate(_as_text(completed.stdout), settings.max_output_bytes),
        stderr=_truncate(_as_text(completed.stderr), settings.max_output_bytes),
        exit_code=completed.returncode,
        timed_out=False,
        duration_seconds=time.monotonic() - started,
    )


def run_python_file(
    workspace: Workspace,
    script_relpath: str,
    *,
    config: Optional[SandboxConfig] = None,
    settings: Optional[Settings] = None,
    runner: Optional[Runner] = None,
) -> SandboxResult:
    """Run one workspace Python file inside the sandbox container.

    Returns a :class:`SandboxResult` with the container's real stdout,
    stderr, and exit code (each stream truncated to
    ``settings.max_output_bytes``). A timeout returns ``timed_out=True``
    with ``exit_code=None`` and whatever partial output was captured.

    Raises:
        WorkspaceError: the script path escapes the workspace.
        SandboxError: the script does not exist or is not a file.
        SandboxUnavailableError: the ``docker`` executable is missing.
    """
    settings = settings or get_settings()
    config = config or SandboxConfig.from_settings(settings)
    argv = build_command(workspace, script_relpath, config)

    script_path = workspace.resolve_path(script_relpath)
    if not script_path.is_file():
        raise SandboxError(f"script does not exist: {script_relpath!r}")

    return _execute(argv, config, settings, runner)


def run_command(
    workspace: Workspace,
    argv_tail,
    *,
    config: Optional[SandboxConfig] = None,
    settings: Optional[Settings] = None,
    runner: Optional[Runner] = None,
) -> SandboxResult:
    """Run one allowlisted command inside the sandbox container.

    ``argv_tail`` is validated by :func:`validate_command` first — only
    ``["python", <file.py>]`` and ``["python", "-m", "pytest", <path>]``
    survive — and the container receives exactly the validated tokens
    after the fixed ``docker run`` prefix. Result, timeout, and
    unavailable-Docker semantics match :func:`run_python_file`.
    """
    settings = settings or get_settings()
    config = config or SandboxConfig.from_settings(settings)
    container_argv = validate_command(workspace, argv_tail)

    target_path = workspace.root / container_argv[-1]
    if container_argv[1] == "-m":  # pytest: the target may be a directory
        if not target_path.exists():
            raise SandboxError(f"test path does not exist: {argv_tail[-1]!r}")
    elif not target_path.is_file():
        raise SandboxError(f"script does not exist: {argv_tail[-1]!r}")

    argv = _docker_argv_prefix(workspace, config) + container_argv
    return _execute(argv, config, settings, runner)
