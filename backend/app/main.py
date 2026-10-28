"""FastAPI entry point for the autonomous sandbox agent backend.

Wires together the health endpoint and the task routes
(:mod:`app.api.tasks`) backed by a :class:`TaskService` built from
settings. Web search and the frontend arrive in later milestones (see
docs/ROADMAP.md).
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI

from app.api.tasks import router as tasks_router
from app.config import Settings, get_settings
from app.schemas import HealthResponse
from app.services.task_service import TaskService


def create_app(
    settings: Settings | None = None,
    task_service: Optional[TaskService] = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    ``task_service`` may be injected (tests use this to supply a
    service backed by a fake model client); otherwise one is built
    from ``settings``.
    """
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name)
    app.state.task_service = task_service or TaskService(settings)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness check: confirms the backend process is answering."""
        return HealthResponse(status="ok", service=settings.app_name)

    app.include_router(tasks_router)
    return app


app = create_app()
