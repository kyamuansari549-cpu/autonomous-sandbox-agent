"""Application configuration.

Settings are read from environment variables (and an optional local .env
file) with safe defaults. No real secrets live in source code: GROQ_API_KEY
defaults to an empty string and must be supplied via the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # Load a local .env file when python-dotenv is installed.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a declared dependency
    pass


@dataclass
class Settings:
    """Runtime settings for the autonomous sandbox agent backend."""

    app_name: str = "autonomous-sandbox-agent"
    groq_api_key: str = ""
    groq_model: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Agent loop guardrails (enforced by the backend, never by the model).
    max_iterations: int = 25
    task_timeout_seconds: int = 600
    max_output_bytes: int = 65536

    # Workspace confinement limits (Milestone 2, enforced by app.workspace).
    max_file_bytes: int = 1_000_000
    max_list_entries: int = 500
    max_search_matches: int = 100

    # Task service persistence (Milestone 5, used by app.services).
    # Relative paths are resolved against the backend/ directory.
    tasks_db_path: str = "data/tasks.db"

    # Docker sandbox policy (Milestone 3, enforced by app.sandbox.runner).
    # These are backend-side limits: the model can never override them,
    # and the runner turns them into fixed `docker run` flags.
    sandbox_image: str = "autonomous-sandbox-agent:latest"
    sandbox_memory: str = "256m"
    sandbox_cpus: str = "0.5"
    sandbox_pids_limit: int = 64
    sandbox_timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables, falling back to defaults."""
        return cls(
            app_name=os.environ.get("APP_NAME", cls.app_name),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            groq_model=os.environ.get("GROQ_MODEL", ""),
            groq_base_url=os.environ.get("GROQ_BASE_URL", cls.groq_base_url),
            max_iterations=int(os.environ.get("MAX_ITERATIONS", cls.max_iterations)),
            task_timeout_seconds=int(
                os.environ.get("TASK_TIMEOUT_SECONDS", cls.task_timeout_seconds)
            ),
            max_output_bytes=int(
                os.environ.get("MAX_OUTPUT_BYTES", cls.max_output_bytes)
            ),
            max_file_bytes=int(os.environ.get("MAX_FILE_BYTES", cls.max_file_bytes)),
            max_list_entries=int(
                os.environ.get("MAX_LIST_ENTRIES", cls.max_list_entries)
            ),
            max_search_matches=int(
                os.environ.get("MAX_SEARCH_MATCHES", cls.max_search_matches)
            ),
            tasks_db_path=os.environ.get("TASKS_DB_PATH", cls.tasks_db_path),
            sandbox_image=os.environ.get("SANDBOX_IMAGE", cls.sandbox_image),
            sandbox_memory=os.environ.get("SANDBOX_MEMORY", cls.sandbox_memory),
            sandbox_cpus=os.environ.get("SANDBOX_CPUS", cls.sandbox_cpus),
            sandbox_pids_limit=int(
                os.environ.get("SANDBOX_PIDS_LIMIT", cls.sandbox_pids_limit)
            ),
            sandbox_timeout_seconds=int(
                os.environ.get(
                    "SANDBOX_TIMEOUT_SECONDS", cls.sandbox_timeout_seconds
                )
            ),
        )


def get_settings() -> Settings:
    """Return settings built from the current environment."""
    return Settings.from_env()
