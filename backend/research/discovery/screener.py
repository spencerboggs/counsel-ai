"""Deterministic stock screener with budget / affordability filters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from backend.providers.base import HistoryBar, MarketDataProvider, Quote

T = TypeVar("T")
ProgressCallback = Callable[[int, int, str, str], Awaitable[None] | None]


@dataclass
class ScreenedCandidate:
    ticker: str
    quote: Quote | None = None
    history: list[HistoryBar] = field(default_factory=list)
    financials: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    screen_score: float = 0.0
    pass_reason: str = ""


async def _await_unless_stopped(
    awaitable: Awaitable[T],
    should_stop: Callable[[], bool] | None,
) -> T:
    """Await market I/O but abandon within ~150ms of Stop."""
    if should_stop is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            if should_stop():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                raise asyncio.CancelledError()
            done, _ = await asyncio.wait({task}, timeout=0.15)
            if done:
                return task.result()
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        raise


def _compute_history_metrics(history: list[HistoryBar]) -> dict[str, Any]:
    closes = [b.close for b in history if b.close is not None]
    volumes = [b.volume for b in history if b.volume is not None]
    out: dict[str, Any] = {}
    if len(closes) >= 21:
        out["momentum_20d"] = (closes[-1] / closes[-21] - 1.0) if closes[-21] else None
    if len(closes) >= 50:
        ma50 = sum(closes[-50:]) / 50
        out["ma50"] = ma50
        out["above_50dma"] = closes[-1] > ma50
    if len(closes) >= 21:
        rets = []
        for i in range(1, min(21, len(closes))):
            if closes[-i - 1]:
                rets.append(closes[-i] / closes[-i - 1] - 1.0)
        if rets:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            out["volatility"] = var**0.5
    if volumes:
        out["avg_volume"] = sum(volumes[-20:]) / min(20, len(volumes))
    if closes:
        out["last_close"] = closes[-1]
    return out


class DeterministicScreener:
    """Screen for names a small budget can actually size into.

    Hard filters:
 - price in [min_price, investable_amount / min_whole_shares]
 - market_cap <= max_market_cap (skip mega-caps)
 - minimum average volume for tradability

    Ranking favors affordability, smaller caps, and positive momentum -
    not household-name market-cap dominance.
    """

    def __init__(
        self,
        market: MarketDataProvider,
        *,
        investable_amount: float = 100.0,
        min_whole_shares: int = 5,
        min_price: float = 1.0,
        min_avg_volume: float = 150_000,
        max_market_cap: float = 40_000_000_000,
    ) -> None:
        self.market = market
        self.investable_amount = max(investable_amount, 1.0)
        self.min_whole_shares = max(min_whole_shares, 1)
        self.min_price = min_price
        self.min_avg_volume = min_avg_volume
        self.max_market_cap = max_market_cap
        self.max_price = self.investable_amount / self.min_whole_shares

    async def screen(
        self,
        tickers: list[str],
        *,
        pool_size: int = 25,
        should_stop: Callable[[], bool] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[ScreenedCandidate]:
        passed: list[ScreenedCandidate] = []
        total = len(tickers)
        for index, ticker in enumerate(tickers, start=1):
            if should_stop and should_stop():
                break
            status = "skip"
            try:
                quote = await _await_unless_stopped(
                    self.market.get_quote(ticker), should_stop
                )
                history = await _await_unless_stopped(
                    self.market.get_history(ticker, "6mo"), should_stop
                )
                financials = await _await_unless_stopped(
                    self.market.get_financials(ticker), should_stop
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                status = "error"
                msg = str(exc).lower()
                if "rate limit" in msg or "too many requests" in msg:
                    status = "error:rate limit"
                    # Give Yahoo a short breather so the whole run does not stay hot.
                    await asyncio.sleep(2.0)
                if on_progress is not None:
                    maybe = on_progress(index, total, ticker, status)
                    if maybe is not None:
                        await maybe
                continue

            if should_stop and should_stop():
                break

            hist_metrics = _compute_history_metrics(history)
            fin = financials.get("metrics") or {}
            price = quote.price or hist_metrics.get("last_close")
            avg_vol = hist_metrics.get("avg_volume") or _safe(fin.get("averageVolume"))
            market_cap = _safe(fin.get("marketCap"))

            keep = True
            skip_reason = "skip"
            if price is None or price < self.min_price:
                keep = False
                skip_reason = "skip:no/low price"
            elif price > self.max_price:
                keep = False
                skip_reason = f"skip:too expensive (${price:.2f})"
            elif avg_vol is None or avg_vol < self.min_avg_volume:
                keep = False
                skip_reason = "skip:thin volume"
            elif market_cap is not None and market_cap > self.max_market_cap:
                keep = False
                skip_reason = "skip:market cap"

            if not keep:
                if on_progress is not None:
                    maybe = on_progress(index, total, ticker, skip_reason)
                    if maybe is not None:
                        await maybe
                continue

            shares_buyable = int(self.investable_amount // price)
            metrics = {
                **hist_metrics,
                "price": price,
                "avg_volume": avg_vol,
                "roe": _safe(fin.get("returnOnEquity")),
                "profit_margin": _safe(fin.get("profitMargins")),
                "revenue_growth": _safe(fin.get("revenueGrowth")),
                "debt_to_equity": _safe(fin.get("debtToEquity")),
                "current_ratio": _safe(fin.get("currentRatio")),
                "pe": _safe(fin.get("trailingPE")),
                "ps": _safe(fin.get("priceToSalesTrailing12Months")),
                "beta": _safe(fin.get("beta")),
                "market_cap": market_cap,
                "sector": fin.get("sector"),
                "industry": fin.get("industry"),
                "name": fin.get("shortName") or fin.get("longName"),
                "investable_amount": self.investable_amount,
                "shares_buyable": shares_buyable,
                "max_affordable_price": self.max_price,
            }

            # Rank for discovery: affordability + smaller cap + momentum
            screen_score = 0.0
            # More shares for the budget = better for "buy a lot into"
            screen_score += min(shares_buyable / 20.0, 1.0) * 35
            # Prefer mid/small over large within the cap ceiling
            if market_cap is not None and market_cap > 0:
                # Higher score for smaller caps (log-ish via inverse)
                relative = min(market_cap / self.max_market_cap, 1.0)
                screen_score += (1.0 - relative) * 30
            else:
                screen_score += 10
            if metrics.get("momentum_20d") is not None:
                mom = float(metrics["momentum_20d"])
                screen_score += max(min(mom * 120, 25), -15) + 10
            else:
                screen_score += 8
            if metrics.get("revenue_growth") is not None:
                growth = float(metrics["revenue_growth"])
                screen_score += max(min(growth * 40, 15), -5)
            # Light liquidity bonus (enough to trade, not mega-volume chase)
            if avg_vol:
                screen_score += min(float(avg_vol) / 2_000_000, 1.0) * 10

            passed.append(
                ScreenedCandidate(
                    ticker=ticker.upper(),
                    quote=quote,
                    history=history,
                    financials=financials,
                    metrics=metrics,
                    screen_score=screen_score,
                    pass_reason=(
                        f"affordable: {shares_buyable} shares @ ${price:.2f} "
                        f"with ${self.investable_amount:.0f}"
                    ),
                )
            )
            status = "pass"
            if on_progress is not None:
                maybe = on_progress(index, total, ticker, status)
                if maybe is not None:
                    await maybe

            # First-come affordable names from a shuffled universe - no need to
            # finish the whole batch just to re-rank later.
            if len(passed) >= pool_size:
                break

        passed.sort(key=lambda c: c.screen_score, reverse=True)
        return passed[:pool_size]

    async def load_one(self, ticker: str) -> ScreenedCandidate:
        """Load one ticker for reexamination. Does not scan the universe."""
        quote = await self.market.get_quote(ticker)
        history = await self.market.get_history(ticker, "6mo")
        financials = await self.market.get_financials(ticker)
        hist_metrics = _compute_history_metrics(history)
        fin = financials.get("metrics") or {}
        price = quote.price or hist_metrics.get("last_close")
        if price is None:
            raise RuntimeError(f"No price available for {ticker}")
        avg_vol = hist_metrics.get("avg_volume") or _safe(fin.get("averageVolume"))
        market_cap = _safe(fin.get("marketCap"))
        shares_buyable = int(self.investable_amount // price) if price else 0
        metrics = {
            **hist_metrics,
            "price": price,
            "avg_volume": avg_vol,
            "roe": _safe(fin.get("returnOnEquity")),
            "profit_margin": _safe(fin.get("profitMargins")),
            "revenue_growth": _safe(fin.get("revenueGrowth")),
            "debt_to_equity": _safe(fin.get("debtToEquity")),
            "current_ratio": _safe(fin.get("currentRatio")),
            "pe": _safe(fin.get("trailingPE")),
            "ps": _safe(fin.get("priceToSalesTrailing12Months")),
            "beta": _safe(fin.get("beta")),
            "market_cap": market_cap,
            "sector": fin.get("sector"),
            "industry": fin.get("industry"),
            "name": fin.get("shortName") or fin.get("longName"),
            "investable_amount": self.investable_amount,
            "shares_buyable": shares_buyable,
            "max_affordable_price": self.max_price,
        }
        return ScreenedCandidate(
            ticker=ticker.upper(),
            quote=quote,
            history=history,
            financials=financials,
            metrics=metrics,
            screen_score=0.0,
            pass_reason="reexamine",
        )


def _safe(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if number != number:
            return None
        return number
    except (TypeError, ValueError):
        return None
