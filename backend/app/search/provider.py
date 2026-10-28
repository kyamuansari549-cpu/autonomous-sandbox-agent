"""Web search providers (Milestone 6).

A *provider* turns a query string into a list of :class:`SearchResult`
records through one real external service. Two providers exist:

* :class:`DuckDuckGoProvider` — the default. Uses the ``ddgs``
  package, which needs no API key. It is a best-effort public search
  endpoint: it can rate-limit or fail, and every such failure is
  reported honestly (see below), never papered over.

* :class:`TavilyProvider` — uses the Tavily search API and requires
  ``TAVILY_API_KEY``. Selected but unconfigured, it raises
  :class:`SearchUnavailableError` instead of pretending to search.

Failure contract: a provider raises :class:`SearchUnavailableError`
carrying the *real* reason (network error, rate limit, empty upstream
response, missing key, …) whenever it cannot produce results. It never
returns fabricated entries. An actually-empty result set is returned
as an empty list — a legitimate outcome the caller reports as "no
results", distinct from an error.

Search results are **untrusted external data**. Providers return them
as facts about the web; nothing in a result may ever be treated as an
instruction to the agent (see ``docs/SECURITY.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

import httpx

from app.config import Settings

try:  # Optional at import time; absence is an honest runtime error.
    from ddgs import DDGS
except ImportError:  # pragma: no cover - ddgs is a declared dependency
    DDGS = None  # type: ignore[assignment]

__all__ = [
    "SearchProvider",
    "SearchResult",
    "SearchUnavailableError",
    "DuckDuckGoProvider",
    "TavilyProvider",
    "get_provider",
]


class SearchUnavailableError(Exception):
    """Raised when search cannot be performed; carries the real reason."""


@dataclass
class SearchResult:
    """One web search result: a title, its URL, and a short snippet."""

    title: str
    url: str
    snippet: str


@runtime_checkable
class SearchProvider(Protocol):
    """Anything that can run a real web search."""

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return up to ``max_results`` results for ``query``.

        Raises :class:`SearchUnavailableError` when the search cannot
        be performed; returns an empty list when the search ran but
        found nothing.
        """
        ...


class DuckDuckGoProvider:
    """Search via DuckDuckGo using the ``ddgs`` package (no API key).

    Tests substitute a stub by monkeypatching this module's ``DDGS``
    name, so no test performs real network I/O through this class.
    """

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        if DDGS is None:
            raise SearchUnavailableError(
                "the 'ddgs' package is not installed; DuckDuckGo search "
                "is unavailable"
            )
        try:
            with DDGS() as client:
                raw = client.text(query, max_results=max_results)
                items = list(raw) if raw is not None else []
        except Exception as exc:  # network, rate limit, upstream change…
            raise SearchUnavailableError(
                f"DuckDuckGo search failed: {exc}"
            ) from exc
        results = [
            SearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("href", "")),
                snippet=str(item.get("body", "")),
            )
            for item in items
        ]
        return results


class TavilyProvider:
    """Search via the Tavily API (requires ``TAVILY_API_KEY``).

    The key is checked on every search: an unconfigured provider
    raises :class:`SearchUnavailableError` naming the missing key
    instead of issuing a doomed request.
    """

    _API_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        if not self._api_key:
            raise SearchUnavailableError(
                "Tavily selected but TAVILY_API_KEY is not set"
            )
        try:
            response = httpx.post(
                self._API_URL,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise SearchUnavailableError(
                f"Tavily search failed: {exc}"
            ) from exc
        results = [
            SearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("content", "")),
            )
            for item in payload.get("results", [])
        ]
        return results


def get_provider(settings: Settings) -> SearchProvider:
    """Build the provider named by ``settings.search_provider``.

    An unknown name raises :class:`SearchUnavailableError` describing
    the problem — the caller surfaces it as an honest tool error
    rather than silently falling back to some other service.
    """
    name = settings.search_provider.strip().lower()
    if name == "duckduckgo":
        return DuckDuckGoProvider()
    if name == "tavily":
        return TavilyProvider(api_key=settings.tavily_api_key)
    raise SearchUnavailableError(
        f"unknown search provider: {settings.search_provider!r} "
        "(expected 'duckduckgo' or 'tavily')"
    )
