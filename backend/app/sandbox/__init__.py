"""Docker sandbox execution (Milestone 3).

Generated code runs in a throwaway container via the fixed, backend-built
``docker run`` argument list in :mod:`app.sandbox.runner`; see that
module's docstring and docs/SECURITY.md for the security model and its
honest limitations.
"""

from app.sandbox.runner import (
    SandboxConfig,
    SandboxError,
    SandboxResult,
    SandboxUnavailableError,
    build_command,
    run_python_file,
)

__all__ = [
    "SandboxConfig",
    "SandboxError",
    "SandboxResult",
    "SandboxUnavailableError",
    "build_command",
    "run_python_file",
]
