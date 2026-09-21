"""Build EvidenceItem records from market data."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from typing import Any

from backend.evidence.models import EvidenceItem
from backend.providers.base import MarketDataProvider, NewsItem
from backend.research.discovery.screener import ScreenedCandidate


class EvidenceGatherer:
    def __init__(self, market: MarketDataProvider) -> None:
        self.market = market
        self._counter = count(1)

    def _next_id(self, run_id: str) -> str:
        return f"EV-{run_id[-6:].upper()}-{next(self._counter):04d}"

    async def gather_for_candidate(
        self,
        candidate: ScreenedCandidate,
        run_id: str,
    ) -> list[EvidenceItem]:
        now = datetime.now(timezone.utc).isoformat()
        ticker = candidate.ticker
        items: list[EvidenceItem] = []
        m = candidate.metrics

        def add(
            claim: str,
            *,
            data_points: dict[str, Any],
            reliability: float = 0.85,
            freshness: float = 0.9,
            directness: float = 1.0,
            source_type: str = "secondary",
            supporting_text: str | None = None,
        ) -> None:
            items.append(
                EvidenceItem(
                    id=self._next_id(run_id),
                    ticker=ticker,
                    claim=claim,
                    source_name="Yahoo Finance (yfinance)",
                    source_url=f"https://finance.yahoo.com/quote/{ticker}",
                    source_type=source_type,
                    published_at=None,
                    retrieved_at=now,
                    supporting_text=supporting_text,
                    data_points=data_points,
                    reliability=reliability,
                    freshness=freshness,
                    directness=directness,
                    corroboration=0.5,
                    research_run_id=run_id,
                )
            )

        if m.get("price") is not None:
            add(
                f"{ticker} last price observed at {m['price']}.",
                data_points={"price": m["price"], "currency": candidate.quote.currency if candidate.quote else None},
            )
        if m.get("shares_buyable") is not None and m.get("investable_amount") is not None:
            add(
                (
                    f"With ${m['investable_amount']:.0f}, approximately "
                    f"{m['shares_buyable']} whole shares of {ticker} can be purchased "
                    f"at the observed price."
                ),
                data_points={
                    "investable_amount": m["investable_amount"],
                    "shares_buyable": m["shares_buyable"],
                    "price": m.get("price"),
                    "max_affordable_price": m.get("max_affordable_price"),
                },
                source_type="derived",
                reliability=0.95,
                supporting_text="Computed from investable budget / last price (whole shares).",
            )
        if m.get("market_cap") is not None:
            add(
                f"{ticker} market capitalization reported.",
                data_points={"market_cap": m["market_cap"]},
            )
        if m.get("roe") is not None:
            add(
                f"{ticker} return on equity reported.",
                data_points={"roe": m["roe"]},
                reliability=0.8,
            )
        if m.get("profit_margin") is not None:
            add(
                f"{ticker} profit margin reported.",
                data_points={"profit_margin": m["profit_margin"]},
            )
        if m.get("revenue_growth") is not None:
            add(
                f"{ticker} revenue growth reported.",
                data_points={"revenue_growth": m["revenue_growth"]},
            )
        if m.get("debt_to_equity") is not None:
            add(
                f"{ticker} debt-to-equity reported.",
                data_points={"debt_to_equity": m["debt_to_equity"]},
            )
        if m.get("pe") is not None:
            add(
                f"{ticker} trailing P/E reported.",
                data_points={"trailing_pe": m["pe"]},
            )
        if m.get("momentum_20d") is not None:
            add(
                f"{ticker} 20-session price change computed from history.",
                data_points={
                    "momentum_20d": m["momentum_20d"],
                    "above_50dma": m.get("above_50dma"),
                },
                supporting_text="Computed from yfinance adjusted daily closes.",
                reliability=0.9,
                source_type="derived",
            )
        if m.get("volatility") is not None:
            add(
                f"{ticker} short-horizon volatility computed from daily returns.",
                data_points={"volatility": m["volatility"]},
                source_type="derived",
                reliability=0.88,
            )

        news: list[NewsItem] = []
        try:
            news = await self.market.get_news(ticker)
        except Exception:
            news = []
        candidate.metrics["news_count"] = len(news)
        for article in news[:5]:
            add(
                f"News: {article.title}",
                data_points={"title": article.title},
                reliability=0.55,
                freshness=0.75,
                directness=0.5,
                supporting_text=article.summary,
                source_type="secondary",
            )
            if items:
                items[-1].source_url = article.url or items[-1].source_url
                items[-1].published_at = article.published_at
                if article.source:
                    items[-1].source_name = f"{article.source} via yfinance"

        return items
