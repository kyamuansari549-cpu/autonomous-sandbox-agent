"""FastAPI entry point for the autonomous sandbox agent backend.

Wires together the health endpoint and the task routes
(:mod:`app.api.tasks`) backed by a :class:`TaskService` built from
settings. CORS is enabled for the React frontend's dev origins
(``settings.frontend_origins``, Milestone 7) so the browser app can
call this API; no other origins are allowed.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.task_service = task_service or TaskService(settings)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness check: confirms the backend process is answering."""
        return HealthResponse(status="ok", service=settings.app_name)

    app.include_router(tasks_router)
    return app


app = create_app()
