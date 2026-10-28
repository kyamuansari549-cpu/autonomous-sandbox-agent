"""Groq client factory (Milestone 4).

Groq exposes an OpenAI-compatible API, so the agent talks to it through
the official ``openai`` Python client pointed at Groq's base URL. The
API key and model come from :class:`app.config.Settings` (environment /
``.env``); nothing is hardcoded and the key is never logged or printed.

If the key or model is missing, :func:`create_groq_client` raises
:class:`LLMNotConfiguredError` with an actionable message instead of
letting the SDK fail later with a confusing error. A live model call is
only possible with a valid key in ``.env``; constructing the client
itself performs no network I/O.
"""

from __future__ import annotations

from openai import OpenAI

from app.config import Settings

__all__ = ["LLMNotConfiguredError", "create_groq_client"]


class LLMNotConfiguredError(Exception):
    """Raised when the Groq client cannot be built from the settings."""


def create_groq_client(settings: Settings) -> OpenAI:
    """Build an OpenAI-compatible client for the Groq API.

    Raises :class:`LLMNotConfiguredError` if ``settings.groq_api_key``
    or ``settings.groq_model`` is empty. The key is passed to the SDK
    and nowhere else — it is never logged, printed, or included in an
    error message.
    """
    if not settings.groq_api_key:
        raise LLMNotConfiguredError(
            "GROQ_API_KEY is not set. Copy backend/.env.example to "
            "backend/.env and fill in a valid key from "
            "https://console.groq.com — the agent cannot call the model "
            "without one."
        )
    if not settings.groq_model:
        raise LLMNotConfiguredError(
            "GROQ_MODEL is not set. Set it in backend/.env to a Groq "
            "model that supports tool calling (see the recommendation "
            "in backend/.env.example)."
        )
    return OpenAI(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
    )
