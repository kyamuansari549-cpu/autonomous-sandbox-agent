"""Web search (Milestone 6).

Real web searches run through a separately configured provider in
:mod:`app.search.provider` (DuckDuckGo by default, Tavily optional).
Results are untrusted external data — information, never instructions
— and provider failures surface as :class:`SearchUnavailableError`
with the real reason, never as fabricated results.
"""

from app.search.provider import (
    DuckDuckGoProvider,
    SearchProvider,
    SearchResult,
    SearchUnavailableError,
    TavilyProvider,
    get_provider,
)

__all__ = [
    "DuckDuckGoProvider",
    "SearchProvider",
    "SearchResult",
    "SearchUnavailableError",
    "TavilyProvider",
    "get_provider",
]
