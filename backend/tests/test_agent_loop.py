"""Tests for the Groq client factory and the controlled agent loop.

No test here performs a network call. The loop is driven by a scripted
``FakeClient`` that mimics the OpenAI response shape
(``choices[0].message`` with ``.content`` and ``.tool_calls``), so every
assertion is about what the backend genuinely did: files really created
in a temporary workspace, real errors really fed back to the "model",
iteration caps really enforced. The live Groq call remains pending a
valid ``GROQ_API_KEY`` in ``.env``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

import app.agent.loop as loop_module
from app.agent.llm_client import LLMNotConfiguredError, create_groq_client
from app.agent.loop import run_agent
from app.config import Settings
from app.tools.definitions import ToolDispatcher, ToolError
from app.workspace import Workspace


# ----------------------------------------------------------------------
# Fake OpenAI-shaped client.
# ----------------------------------------------------------------------
class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeCompletions:
    """Pops one scripted item per create() call; exceptions are raised."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("FakeClient script exhausted")
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    def __init__(self, script: list) -> None:
        self.completions = FakeCompletions(script)
        self.chat = SimpleNamespace(completions=self.completions)


def text_response(text: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=FakeMessage(content=text))]
    )


def tool_response(name: str, arguments, call_id: str = "call_1"):
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    message = FakeMessage(
        content=None,
        tool_calls=[FakeToolCall(call_id, name, arguments)],
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def rate_limit_error() -> openai.RateLimitError:
    # openai 1.109 reads response.request when building the exception,
    # so the httpx.Response must carry a request.
    request = httpx.Request(
        "POST", "https://api.groq.com/openai/v1/chat/completions"
    )
    return openai.RateLimitError(
        "rate limited",
        response=httpx.Response(429, request=request),
        body=None,
    )


def tool_messages_sent(client: FakeClient, call_index: int) -> list[dict]:
    """The role=tool messages included in the Nth create() call."""
    messages = client.completions.calls[call_index]["messages"]
    return [m for m in messages if m.get("role") == "tool"]


# ----------------------------------------------------------------------
# Fixtures.
# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop_module, "RETRY_DELAYS", (0.0, 0.0))


@pytest.fixture()
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(root=tmp_path / "ws", settings=Settings())


@pytest.fixture()
def dispatcher(workspace: Workspace) -> ToolDispatcher:
    return ToolDispatcher(workspace)


def run(client: FakeClient, dispatcher: ToolDispatcher, **kwargs):
    settings = kwargs.pop("settings", Settings())
    return run_agent(
        task=kwargs.pop("task", "do the thing"),
        client=client,
        model="test-model",
        dispatcher=dispatcher,
        settings=settings,
        **kwargs,
    )


# ----------------------------------------------------------------------
# Happy paths.
# ----------------------------------------------------------------------
def test_plain_final_answer_completes_without_tools(dispatcher) -> None:
    client = FakeClient([text_response("All done, nothing to run.")])
    result = run(client, dispatcher)
    assert result.status == "completed"
    assert result.final_text == "All done, nothing to run."
    assert result.tool_calls == []
    assert result.iterations == 1
    assert result.error is None


def test_create_file_tool_call_really_creates_the_file(
    dispatcher, workspace: Workspace
) -> None:
    client = FakeClient(
        [
            tool_response(
                "create_file",
                {"relative_path": "hello.txt", "content": "hello agent\n"},
            ),
            text_response("Created hello.txt."),
        ]
    )
    result = run(client, dispatcher)
    assert result.status == "completed"
    assert result.tool_calls == ["create_file"]
    created = workspace.root / "hello.txt"
    assert created.is_file()
    assert created.read_text(encoding="utf-8") == "hello agent\n"


# ----------------------------------------------------------------------
# Tool failures are fed back to the model, and the loop survives them.
# ----------------------------------------------------------------------
def test_unknown_tool_error_is_fed_back_and_loop_survives(dispatcher) -> None:
    client = FakeClient(
        [
            tool_response("delete_everything", {}),
            text_response("That tool does not exist; doing nothing."),
        ]
    )
    result = run(client, dispatcher)
    assert result.status == "completed"
    feedback = tool_messages_sent(client, call_index=1)
    assert len(feedback) == 1
    assert "unknown tool" in feedback[0]["content"]


def test_malformed_json_arguments_are_fed_back(dispatcher) -> None:
    client = FakeClient(
        [
            tool_response("create_file", "{not valid json"),
            text_response("My arguments were malformed; retrying properly."),
        ]
    )
    result = run(client, dispatcher)
    assert result.status == "completed"
    feedback = tool_messages_sent(client, call_index=1)
    assert len(feedback) == 1
    assert "not valid JSON" in feedback[0]["content"]


def test_path_traversal_is_refused_and_reported(
    dispatcher, workspace: Workspace, tmp_path: Path
) -> None:
    client = FakeClient(
        [
            tool_response(
                "create_file",
                {"relative_path": "../evil.txt", "content": "pwned"},
            ),
            text_response("The path was refused by the workspace."),
        ]
    )
    result = run(client, dispatcher)
    assert result.status == "completed"
    feedback = tool_messages_sent(client, call_index=1)
    assert "escapes the workspace" in feedback[0]["content"]
    # Nothing was written outside (or inside) the workspace root.
    assert not (tmp_path / "evil.txt").exists()
    assert not (workspace.root / "evil.txt").exists()


# ----------------------------------------------------------------------
# Loop controls: iteration cap and cancellation.
# ----------------------------------------------------------------------
def test_endless_tool_calls_stop_at_max_iterations(dispatcher) -> None:
    script = [tool_response("list_files", {}) for _ in range(10)]
    client = FakeClient(script)
    result = run(client, dispatcher, settings=Settings(max_iterations=3))
    assert result.status == "max_iterations"
    assert result.iterations == 3
    assert len(client.completions.calls) == 3
    assert result.tool_calls == ["list_files"] * 3
    assert "NOT verified complete" in result.final_text


def test_pre_set_cancel_event_cancels_before_any_call(dispatcher) -> None:
    cancel = threading.Event()
    cancel.set()
    client = FakeClient([text_response("never reached")])
    result = run(client, dispatcher, cancel_event=cancel)
    assert result.status == "cancelled"
    assert result.iterations == 0
    assert client.completions.calls == []


# ----------------------------------------------------------------------
# API failure policy.
# ----------------------------------------------------------------------
def test_rate_limit_twice_then_success_completes(dispatcher) -> None:
    client = FakeClient(
        [rate_limit_error(), rate_limit_error(), text_response("recovered")]
    )
    result = run(client, dispatcher)
    assert result.status == "completed"
    assert result.final_text == "recovered"
    assert len(client.completions.calls) == 3  # 1 initial + 2 retries


def test_persistent_rate_limit_fails_after_retries(dispatcher) -> None:
    client = FakeClient([rate_limit_error() for _ in range(5)])
    result = run(client, dispatcher)
    assert result.status == "failed"
    assert result.error is not None and "rate limit" in result.error.lower()
    assert len(client.completions.calls) == 3  # retries exhausted, then stop


def test_authentication_error_fails_immediately(dispatcher) -> None:
    request = httpx.Request(
        "POST", "https://api.groq.com/openai/v1/chat/completions"
    )
    auth_error = openai.AuthenticationError(
        "invalid api key",
        response=httpx.Response(401, request=request),
        body=None,
    )
    client = FakeClient([auth_error, text_response("never reached")])
    result = run(client, dispatcher)
    assert result.status == "failed"
    assert result.error is not None and "authentication" in result.error.lower()
    assert len(client.completions.calls) == 1  # no retry on a bad key


# ----------------------------------------------------------------------
# Dispatcher validation (unit level).
# ----------------------------------------------------------------------
def test_dispatcher_rejects_unknown_tool(dispatcher) -> None:
    with pytest.raises(ToolError, match="unknown tool"):
        dispatcher.dispatch("nuke", {})


def test_dispatcher_rejects_missing_and_mistyped_args(dispatcher) -> None:
    with pytest.raises(ToolError, match="missing required argument"):
        dispatcher.dispatch("read_file", {})
    with pytest.raises(ToolError, match="must be a str"):
        dispatcher.dispatch("read_file", {"relative_path": 42})


# ----------------------------------------------------------------------
# Client factory.
# ----------------------------------------------------------------------
def test_create_groq_client_requires_key() -> None:
    settings = Settings(groq_api_key="", groq_model="llama-3.3-70b-versatile")
    with pytest.raises(LLMNotConfiguredError, match="GROQ_API_KEY"):
        create_groq_client(settings)


def test_create_groq_client_requires_model() -> None:
    settings = Settings(groq_api_key="not-a-real-key", groq_model="")
    with pytest.raises(LLMNotConfiguredError, match="GROQ_MODEL"):
        create_groq_client(settings)


def test_create_groq_client_builds_openai_client_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The SDK builds a default httpx client that honours proxy env
    # vars; this sandbox's NO_PROXY contains bracketed IPv6 entries
    # that httpx 0.28 cannot parse, which would fail construction for
    # reasons unrelated to the factory. Clear them for this test only.
    for var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(
        groq_api_key="not-a-real-key", groq_model="llama-3.3-70b-versatile"
    )
    client = create_groq_client(settings)
    assert isinstance(client, openai.OpenAI)
    assert str(client.base_url).rstrip("/") == "https://api.groq.com/openai/v1"
