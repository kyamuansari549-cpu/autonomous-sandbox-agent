"""Shared API schemas for the autonomous sandbox agent backend."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response body for the GET /health endpoint."""

    status: str
    service: str


class TaskCreateRequest(BaseModel):
    """Request body for POST /tasks."""

    task: str = Field(min_length=1)


class TaskCreatedResponse(BaseModel):
    """Response body for POST /tasks: the new task's id and status."""

    task_id: str
    status: str


class TaskRecordResponse(BaseModel):
    """Full stored record for one task (GET /tasks, GET /tasks/{id})."""

    task_id: str
    task: str
    status: str
    created_at: str
    updated_at: str
    result_summary: Optional[str] = None
    tool_calls: list[str] = Field(default_factory=list)
    error: Optional[str] = None
