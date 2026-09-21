"""Stub market-data provider interface placeholder (no live data yet)."""

from __future__ import annotations

from typing import Any

from backend.providers.base import HistoryBar, NewsItem, Quote


class StubMarketDataProvider:
    """Implements MarketDataProvider without fabricating market values."""

    name = "stub"

    async def get_quote(self, ticker: str) -> Quote:
        raise NotImplementedError(
            "Market data providers are not wired yet. Configure yfinance/SEC later."
        )

    async def get_history(self, ticker: str, period: str) -> list[HistoryBar]:
        raise NotImplementedError("Market history is not available yet.")

    async def get_financials(self, ticker: str) -> dict[str, Any]:
        raise NotImplementedError("Financials are not available yet.")

    async def get_news(self, ticker: str) -> list[NewsItem]:
        raise NotImplementedError("News is not available yet.")
