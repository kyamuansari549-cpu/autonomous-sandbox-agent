"""Application configuration.

Settings are read from environment variables (and an optional local .env
file) with safe defaults. No real secrets live in source code: GROQ_API_KEY
defaults to an empty string and must be supplied via the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # Load a local .env file when python-dotenv is installed.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a declared dependency
    pass


#: Default CORS origins for the React frontend dev server (Milestone 7).
DEFAULT_FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


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

    # Web search (Milestone 6, used by app.search). The provider is
    # selected by name; an unknown or unconfigured provider is an
    # honest error at search time, never a fake result.
    search_provider: str = "duckduckgo"
    tavily_api_key: str = ""
    search_max_results: int = 5

    # Frontend CORS (Milestone 7): the origins the React dev server is
    # allowed to call this API from. Local development only — the
    # backend is not exposed publicly by default (see ROADMAP M9).
    frontend_origins: list[str] = field(
        default_factory=lambda: list(DEFAULT_FRONTEND_ORIGINS)
    )

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
            search_provider=os.environ.get(
                "SEARCH_PROVIDER", cls.search_provider
            ),
            tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
            search_max_results=int(
                os.environ.get("SEARCH_MAX_RESULTS", cls.search_max_results)
            ),
            frontend_origins=[
                origin.strip()
                for origin in os.environ.get(
                    "FRONTEND_ORIGINS", ",".join(DEFAULT_FRONTEND_ORIGINS)
                ).split(",")
                if origin.strip()
            ],
        )


def get_settings() -> Settings:
    """Return settings built from the current environment."""
    return Settings.from_env()
