"""Task HTTP routes (Milestone 5).

Thin wrappers over :class:`app.services.task_service.TaskService`: the
routes translate between HTTP and the service, nothing more. Creating
a task on a backend whose model client is not configured returns
**503** with the real configuration problem — an honest refusal, never
a fake "queued" success for a task that can never run.

The service is resolved through the :func:`get_task_service`
dependency, which reads the instance stored on the app at creation;
tests override the dependency to inject a service backed by a fake
model client and a temporary workspace.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.llm_client import LLMNotConfiguredError
from app.schemas import (
    TaskCreateRequest,
    TaskCreatedResponse,
    TaskRecordResponse,
)
from app.services.task_service import TaskService

router = APIRouter(tags=["tasks"])


def get_task_service(request: Request) -> TaskService:
    """Return the TaskService instance stored on the application."""
    return request.app.state.task_service


@router.post("/tasks", response_model=TaskCreatedResponse)
def create_task(
    payload: TaskCreateRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskCreatedResponse:
    """Create a task and start it in the background."""
    try:
        record = service.create_task(payload.task)
    except LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TaskCreatedResponse(task_id=record.id, status=record.status)


@router.get("/tasks", response_model=list[TaskRecordResponse])
def list_tasks(
    service: TaskService = Depends(get_task_service),
) -> list[TaskRecordResponse]:
    """List all stored task records, newest first."""
    return [
        TaskRecordResponse(**record.to_dict())
        for record in service.list_tasks()
    ]


@router.get("/tasks/{task_id}", response_model=TaskRecordResponse)
def get_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> TaskRecordResponse:
    """Return one task's full stored record."""
    record = service.get_task(task_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"no such task: {task_id}"
        )
    return TaskRecordResponse(**record.to_dict())


@router.post("/tasks/{task_id}/cancel", response_model=TaskRecordResponse)
def cancel_task(
    task_id: str,
    service: TaskService = Depends(get_task_service),
) -> TaskRecordResponse:
    """Request cancellation of a queued or running task."""
    record = service.cancel_task(task_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"no such task: {task_id}"
        )
    return TaskRecordResponse(**record.to_dict())
