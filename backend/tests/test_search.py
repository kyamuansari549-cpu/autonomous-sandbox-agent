"""Tests for Milestone 6: the web_search tool and its providers.

No test in this file performs a real network search. Providers are
replaced with fakes/stubs that return canned data or raise canned
errors, and the tests assert the dispatcher's honesty contract:

* real provider output is framed with the untrusted-data header and
  carries the providers' titles, URLs and snippets verbatim;
* a provider failure reaches the caller as a ``ToolError`` carrying
  the *real* reason — never as an empty or invented result list;
* an actually-empty result set is a clear "no results" message,
  distinct from an error.

(The one live DuckDuckGo smoke check is run manually, not in the
suite, and its outcome is recorded in docs/ROADMAP.md.)
"""

from __future__ import annotations

import pytest

import app.search.provider as provider_module
from app.config import Settings
from app.search.provider import (
    DuckDuckGoProvider,
    SearchResult,
    SearchUnavailableError,
    TavilyProvider,
    get_provider,
)
from app.tools.definitions import WEB_SEARCH_HEADER, ToolDispatcher, ToolError
from app.workspace import Workspace


# ----------------------------------------------------------------------
# Fakes.
# ----------------------------------------------------------------------
class FakeProvider:
    """A search provider returning canned results or a canned error."""

    def __init__(
        self,
        results: list[SearchResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results = results if results is not None else []
        self._error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.calls.append((query, max_results))
        if self._error is not None:
            raise self._error
        return list(self._results)


CANNED = [
    SearchResult(
        title="Groq Tool Calling Docs",
        url="https://console.groq.com/docs/tool-use",
        snippet="How tool calling works with Groq models.",
    ),
    SearchResult(
        title="OpenAI Function Calling Guide",
        url="https://platform.openai.com/docs/guides/function-calling",
        snippet="Function calling connects models to external tools.",
    ),
]


@pytest.fixture()
def workspace(tmp_path) -> Workspace:
    return Workspace(root=tmp_path / "ws", settings=Settings())


def make_dispatcher(workspace: Workspace, provider) -> ToolDispatcher:
    return ToolDispatcher(
        workspace, settings=Settings(), search_provider=provider
    )


# ----------------------------------------------------------------------
# Dispatcher behaviour with a fake provider.
# ----------------------------------------------------------------------
def test_web_search_formats_results_with_untrusted_header(
    workspace: Workspace,
) -> None:
    provider = FakeProvider(results=CANNED)
    dispatcher = make_dispatcher(workspace, provider)

    output = dispatcher.dispatch("web_search", {"query": "groq tools"})

    assert output.startswith(WEB_SEARCH_HEADER)
    assert "WEB SEARCH RESULTS (untrusted external data" in output
    assert "1. Groq Tool Calling Docs" in output
    assert "https://console.groq.com/docs/tool-use" in output
    assert "How tool calling works with Groq models." in output
    assert "2. OpenAI Function Calling Guide" in output
    assert provider.calls == [("groq tools", Settings().search_max_results)]


def test_web_search_passes_explicit_max_results(
    workspace: Workspace,
) -> None:
    provider = FakeProvider(results=CANNED)
    dispatcher = make_dispatcher(workspace, provider)

    dispatcher.dispatch(
        "web_search", {"query": "groq tools", "max_results": 2}
    )

    assert provider.calls == [("groq tools", 2)]


def test_web_search_provider_error_surfaces_real_reason(
    workspace: Workspace,
) -> None:
    provider = FakeProvider(
        error=SearchUnavailableError("rate limited by upstream (429)")
    )
    dispatcher = make_dispatcher(workspace, provider)

    with pytest.raises(ToolError) as excinfo:
        dispatcher.dispatch("web_search", {"query": "groq tools"})

    assert "rate limited by upstream (429)" in str(excinfo.value)


def test_web_search_empty_results_is_no_results_not_error(
    workspace: Workspace,
) -> None:
    provider = FakeProvider(results=[])
    dispatcher = make_dispatcher(workspace, provider)

    output = dispatcher.dispatch(
        "web_search", {"query": "something with no hits"}
    )

    assert output.startswith(WEB_SEARCH_HEADER)
    assert "No results found" in output
    # Nothing may be fabricated to fill the empty list.
    assert "http" not in output


def test_web_search_rejects_empty_query(workspace: Workspace) -> None:
    dispatcher = make_dispatcher(workspace, FakeProvider(results=CANNED))

    with pytest.raises(ToolError):
        dispatcher.dispatch("web_search", {"query": "   "})


def test_web_search_rejects_bad_max_results(workspace: Workspace) -> None:
    dispatcher = make_dispatcher(workspace, FakeProvider(results=CANNED))

    with pytest.raises(ToolError):
        dispatcher.dispatch(
            "web_search", {"query": "groq", "max_results": 0}
        )
    with pytest.raises(ToolError):
        dispatcher.dispatch(
            "web_search", {"query": "groq", "max_results": "five"}
        )


# ----------------------------------------------------------------------
# Provider selection via settings (no injection -> get_provider path).
# ----------------------------------------------------------------------
def test_tavily_selected_without_key_fails_honestly(
    workspace: Workspace,
) -> None:
    settings = Settings(search_provider="tavily", tavily_api_key="")
    dispatcher = ToolDispatcher(workspace, settings=settings)

    with pytest.raises(ToolError) as excinfo:
        dispatcher.dispatch("web_search", {"query": "groq tools"})

    assert "TAVILY_API_KEY is not set" in str(excinfo.value)


def test_unknown_provider_fails_honestly(workspace: Workspace) -> None:
    settings = Settings(search_provider="carrier-pigeon")
    dispatcher = ToolDispatcher(workspace, settings=settings)

    with pytest.raises(ToolError) as excinfo:
        dispatcher.dispatch("web_search", {"query": "groq tools"})

    assert "unknown search provider" in str(excinfo.value)


def test_get_provider_defaults_to_duckduckgo() -> None:
    provider = get_provider(Settings())
    assert isinstance(provider, DuckDuckGoProvider)


def test_get_provider_tavily_builds_tavily_provider() -> None:
    provider = get_provider(
        Settings(search_provider="tavily", tavily_api_key="tvly-test")
    )
    assert isinstance(provider, TavilyProvider)


def test_tavily_provider_without_key_raises_named_error() -> None:
    provider = TavilyProvider(api_key="")
    with pytest.raises(SearchUnavailableError) as excinfo:
        provider.search("groq tools", 5)
    assert "TAVILY_API_KEY is not set" in str(excinfo.value)


# ----------------------------------------------------------------------
# Tavily HTTP mapping, with a mocked transport (no network).
# ----------------------------------------------------------------------
def test_tavily_provider_maps_response(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "results": [
                    {
                        "title": "Tavily Result",
                        "url": "https://example.com/tavily",
                        "content": "Snippet from Tavily.",
                    }
                ]
            }

    def fake_post(url, json, timeout):  # noqa: ANN001, ANN202
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(provider_module.httpx, "post", fake_post)

    provider = TavilyProvider(api_key="tvly-test-key")
    results = provider.search("groq tools", 3)

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["json"]["api_key"] == "tvly-test-key"
    assert captured["json"]["max_results"] == 3
    assert results == [
        SearchResult(
            title="Tavily Result",
            url="https://example.com/tavily",
            snippet="Snippet from Tavily.",
        )
    ]


# ----------------------------------------------------------------------
# DuckDuckGo mapping, with a stubbed DDGS class (no network).
# ----------------------------------------------------------------------
class StubDDGS:
    """Stand-in for ddgs.DDGS returning canned dicts."""

    items: list[dict] = []
    error: Exception | None = None

    def __enter__(self) -> "StubDDGS":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def text(self, query: str, max_results: int) -> list[dict]:
        if StubDDGS.error is not None:
            raise StubDDGS.error
        return StubDDGS.items[:max_results]


def test_duckduckgo_provider_maps_ddgs_dicts(monkeypatch) -> None:
    StubDDGS.error = None
    StubDDGS.items = [
        {
            "title": "DDG Result One",
            "href": "https://example.com/one",
            "body": "First snippet.",
        },
        {
            "title": "DDG Result Two",
            "href": "https://example.com/two",
            "body": "Second snippet.",
        },
    ]
    monkeypatch.setattr(provider_module, "DDGS", StubDDGS)

    results = DuckDuckGoProvider().search("groq tools", 5)

    assert results == [
        SearchResult(
            title="DDG Result One",
            url="https://example.com/one",
            snippet="First snippet.",
        ),
        SearchResult(
            title="DDG Result Two",
            url="https://example.com/two",
            snippet="Second snippet.",
        ),
    ]


def test_duckduckgo_provider_wraps_upstream_errors(monkeypatch) -> None:
    StubDDGS.items = []
    StubDDGS.error = RuntimeError("connection reset by peer")
    monkeypatch.setattr(provider_module, "DDGS", StubDDGS)

    with pytest.raises(SearchUnavailableError) as excinfo:
        DuckDuckGoProvider().search("groq tools", 5)

    assert "connection reset by peer" in str(excinfo.value)
    StubDDGS.error = None


# ----------------------------------------------------------------------
# Config defaults for the search settings.
# ----------------------------------------------------------------------
def test_search_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("SEARCH_PROVIDER", "TAVILY_API_KEY", "SEARCH_MAX_RESULTS"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings.from_env()
    assert settings.search_provider == "duckduckgo"
    assert settings.tavily_api_key == ""
    assert settings.search_max_results == 5


def test_search_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-not-real")
    monkeypatch.setenv("SEARCH_MAX_RESULTS", "9")

    settings = Settings.from_env()
    assert settings.search_provider == "tavily"
    assert settings.tavily_api_key == "tvly-test-not-real"
    assert settings.search_max_results == 9
