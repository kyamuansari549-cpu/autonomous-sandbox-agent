"""FastAPI entry point for the autonomous sandbox agent backend.

Milestone 1 scope: application factory + health endpoint only.
Task orchestration, tools, the sandbox, and search arrive in later
milestones (see docs/ROADMAP.md).
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.schemas import HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness check: confirms the backend process is answering."""
        return HealthResponse(status="ok", service=settings.app_name)

    return app


app = create_app()
