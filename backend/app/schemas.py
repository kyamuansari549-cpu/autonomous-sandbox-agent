"""Shared API schemas for the autonomous sandbox agent backend."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response body for the GET /health endpoint."""

    status: str
    service: str
