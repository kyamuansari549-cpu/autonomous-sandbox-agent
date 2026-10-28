"""The controlled agent loop (Milestone 4).

:func:`run_agent` drives one task through a bounded tool-calling loop:

1. The model receives the task plus :data:`TOOL_SCHEMAS` and either
   answers in text (task done) or requests tool calls.
2. Every requested call is executed by the backend
   (:class:`app.tools.definitions.ToolDispatcher`) — never by the
   model — and the *actual* result, success or failure, is appended to
   the conversation as a ``tool`` message. The model sees real errors
   (unknown tool, bad arguments, path traversal refusals) and can react
   to them; nothing is hidden or fabricated on its behalf.
3. The loop stops on the first of: a plain-text answer
   (``completed``), ``settings.max_iterations`` model rounds
   (``max_iterations``), a set ``cancel_event`` (``cancelled``), or an
   unrecoverable API failure (``failed``).

API failure policy: ``RateLimitError`` is retried with a short backoff
(:data:`RETRY_DELAYS`, at most :data:`MAX_RATE_LIMIT_RETRIES` retries);
``AuthenticationError`` fails immediately (retrying cannot fix a bad
key); any other ``APIError`` or unexpected exception fails the task
with the real error text in :attr:`AgentResult.error`.

The ``client`` parameter is duck-typed: anything exposing
``client.chat.completions.create(...)`` with the OpenAI response shape
works, which is how the tests inject a scripted fake — no test in this
project performs a live network call.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import openai

from app.config import Settings
from app.tools.definitions import TOOL_SCHEMAS, ToolDispatcher, ToolError

__all__ = ["AgentResult", "SYSTEM_PROMPT", "run_agent"]


SYSTEM_PROMPT = """\
You are the agent inside an autonomous sandbox coding assistant. You \
work on the user's task by calling the provided tools, which operate \
on a confined workspace.

Rules you must follow:
- Report ONLY what the tools actually returned. Never invent file \
contents, command output, or results you did not receive.
- If a tool call fails, say so honestly in your summary and describe \
the real error. Never claim a step succeeded when it did not.
- When the task is done, give a plain-text final answer summarizing \
what was actually completed, including any failures or unverified \
items.
- All file paths are relative to the workspace root. You cannot access \
anything outside the workspace.
"""

# Backoff between rate-limit retries, in seconds. Indexed by retry
# number; tests monkeypatch this to (0.0, 0.0) to stay fast.
RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0)
MAX_RATE_LIMIT_RETRIES = 2


@dataclass
class AgentResult:
    """The verified outcome of one :func:`run_agent` execution."""

    status: str  # "completed" | "max_iterations" | "failed" | "cancelled"
    final_text: str
    iterations: int
    tool_calls: list[str] = field(default_factory=list)
    error: Optional[str] = None


class _CallFailed(Exception):
    """Internal: the model call failed unrecoverably; carries the reason."""


def _create_with_retry(client, model: str, messages: list[dict]):
    """One chat completion, with bounded retries on rate limiting."""
    retries_used = 0
    while True:
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except openai.RateLimitError as exc:
            if retries_used >= MAX_RATE_LIMIT_RETRIES:
                raise _CallFailed(
                    f"Groq rate limit persisted after "
                    f"{MAX_RATE_LIMIT_RETRIES} retries: {exc}"
                ) from exc
            delay = RETRY_DELAYS[min(retries_used, len(RETRY_DELAYS) - 1)]
            time.sleep(delay)
            retries_used += 1
        except openai.AuthenticationError as exc:
            raise _CallFailed(
                f"Groq authentication failed (check GROQ_API_KEY in "
                f".env): {exc}"
            ) from exc
        except openai.APIError as exc:
            raise _CallFailed(f"Groq API error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            raise _CallFailed(
                f"Unexpected error calling the model: {exc}"
            ) from exc


def _truncate(text: str, max_bytes: int) -> str:
    """Cap a tool result at ``max_bytes`` of UTF-8, noting the cut."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return cut + "\n[... tool result truncated by the backend ...]"


def run_agent(
    task: str,
    client,
    model: str,
    dispatcher: ToolDispatcher,
    settings: Settings,
    cancel_event: Optional[threading.Event] = None,
) -> AgentResult:
    """Run ``task`` through the controlled tool-calling loop.

    ``client`` is any object with the OpenAI client's
    ``chat.completions.create`` shape (the real Groq-backed client from
    :func:`app.agent.llm_client.create_groq_client`, or a test fake).
    The returned :class:`AgentResult` reports only what genuinely
    happened: tools that ran are listed in ``tool_calls``, and failures
    surface in the conversation and in ``error``.
    """
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    tool_calls_made: list[str] = []
    iterations = 0

    while True:
        if cancel_event is not None and cancel_event.is_set():
            return AgentResult(
                status="cancelled",
                final_text=(
                    "Task cancelled before completion; no further tool "
                    "calls were made."
                ),
                iterations=iterations,
                tool_calls=tool_calls_made,
            )
        if iterations >= settings.max_iterations:
            return AgentResult(
                status="max_iterations",
                final_text=(
                    f"Stopped after {iterations} model round(s): the "
                    f"configured maximum of {settings.max_iterations} "
                    f"iterations was reached before the model produced "
                    f"a final answer. The task is NOT verified complete."
                ),
                iterations=iterations,
                tool_calls=tool_calls_made,
            )
        iterations += 1

        try:
            response = _create_with_retry(client, model, messages)
        except _CallFailed as exc:
            return AgentResult(
                status="failed",
                final_text=(
                    "The task failed because the model call failed; "
                    "see the error field for the real reason."
                ),
                iterations=iterations,
                tool_calls=tool_calls_made,
                error=str(exc),
            )

        message = response.choices[0].message
        requested = list(getattr(message, "tool_calls", None) or [])
        if not requested:
            return AgentResult(
                status="completed",
                final_text=message.content or "",
                iterations=iterations,
                tool_calls=tool_calls_made,
            )

        # Record the assistant turn (with its tool calls) before the
        # tool results, as the chat-completions format requires.
        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in requested
                ],
            }
        )

        for tc in requested:
            name = tc.function.name
            tool_calls_made.append(name)
            result_text = _run_one_tool(dispatcher, name, tc.function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": _truncate(result_text, settings.max_output_bytes),
                }
            )


def _run_one_tool(dispatcher: ToolDispatcher, name: str, raw_arguments) -> str:
    """Execute one requested tool call; return its result or error text.

    Errors are returned as text (never raised) so the loop can feed the
    real failure back to the model as the tool result.
    """
    try:
        args = json.loads(raw_arguments) if raw_arguments else {}
    except (json.JSONDecodeError, TypeError) as exc:
        return (
            f"Error: arguments for tool {name!r} were not valid JSON "
            f"({exc}). No tool was executed."
        )
    if not isinstance(args, dict):
        return (
            f"Error: arguments for tool {name!r} must be a JSON object. "
            f"No tool was executed."
        )
    try:
        return dispatcher.dispatch(name, args)
    except ToolError as exc:
        return f"Error: {exc}"
