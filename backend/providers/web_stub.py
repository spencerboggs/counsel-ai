"""Stub web research provider (no browsing yet)."""

from __future__ import annotations

from backend.providers.base import FetchedDocument, SearchResult


class StubWebResearchProvider:
    name = "stub"

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        raise NotImplementedError("Web research provider is not wired yet.")

    async def fetch(self, url: str) -> FetchedDocument:
        raise NotImplementedError("Document fetch is not wired yet.")
