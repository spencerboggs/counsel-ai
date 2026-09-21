"""Screener unit tests with mock market provider."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.providers.base import HistoryBar, NewsItem, Quote
from backend.research.discovery.screener import DeterministicScreener


class FakeMarket:
    name = "fake"

    def __init__(self) -> None:
        self.quotes = {
            "GOOD": Quote(ticker="GOOD", price=12.0, currency="USD"),
            "CHEAP": Quote(ticker="CHEAP", price=0.4, currency="USD"),
            "ILLIQ": Quote(ticker="ILLIQ", price=8.0, currency="USD"),
            "PRICEY": Quote(ticker="PRICEY", price=50.0, currency="USD"),
            "MEGA": Quote(ticker="MEGA", price=10.0, currency="USD"),
        }
        self.caps = {
            "GOOD": 5e9,
            "CHEAP": 1e9,
            "ILLIQ": 2e9,
            "PRICEY": 3e9,
            "MEGA": 500e9,
        }
        self.vols = {
            "GOOD": 1_000_000,
            "CHEAP": 1_000_000,
            "ILLIQ": 1_000,
            "PRICEY": 1_000_000,
            "MEGA": 5_000_000,
        }

    async def get_quote(self, ticker: str) -> Quote:
        return self.quotes[ticker]

    async def get_history(self, ticker: str, period: str = "1y") -> list[HistoryBar]:
        vol = self.vols[ticker]
        price = self.quotes[ticker].price or 10.0
        bars: list[HistoryBar] = []
        start = date(2026, 1, 2)
        for i in range(60):
            d = start + timedelta(days=i)
            bars.append(
                HistoryBar(
                    date=d.isoformat(),
                    open=price,
                    high=price,
                    low=price,
                    close=price * (1 + i * 0.001),
                    volume=float(vol),
                )
            )
        return bars

    async def get_financials(self, ticker: str) -> dict:
        return {
            "ticker": ticker,
            "metrics": {
                "returnOnEquity": 0.2,
                "profitMargins": 0.1,
                "revenueGrowth": 0.05,
                "debtToEquity": 40,
                "currentRatio": 1.4,
                "trailingPE": 18,
                "marketCap": self.caps[ticker],
                "averageVolume": self.vols[ticker],
                "sector": "Tech",
                "shortName": ticker,
            },
        }

    async def get_news(self, ticker: str) -> list[NewsItem]:
        return []


@pytest.mark.asyncio
async def test_screener_budget_and_mega_filters():
    # $100 / 5 shares => max price $20
    screener = DeterministicScreener(
        FakeMarket(),
        investable_amount=100,
        min_whole_shares=5,
        min_price=1.0,
        max_market_cap=40_000_000_000,
    )
    results = await screener.screen(
        ["GOOD", "CHEAP", "ILLIQ", "PRICEY", "MEGA"],
        pool_size=10,
    )
    tickers = [r.ticker for r in results]
    assert "GOOD" in tickers
    assert "CHEAP" not in tickers  # below min price
    assert "ILLIQ" not in tickers  # illiquid
    assert "PRICEY" not in tickers  # can't buy 5 shares with $100
    assert "MEGA" not in tickers  # mega-cap
    good = next(r for r in results if r.ticker == "GOOD")
    assert good.metrics["shares_buyable"] >= 5
