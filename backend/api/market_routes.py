"""Market data routes (quotes / charts) with Yahoo cache + stale fallback."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.providers.yfinance_provider import YahooRateLimitError, YFinanceProvider

market_router = APIRouter(prefix="/market", tags=["market"])

_ALLOWED_RANGES = frozenset({"1d", "5d", "1mo", "3mo", "6mo", "1y", "5y"})


@market_router.get("/chart/{ticker}")
async def chart_snapshot(
    ticker: str,
    range_key: str = Query("1mo", alias="range"),
) -> dict:
    symbol = ticker.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker required")
    key = (range_key or "1mo").strip().lower()
    if key not in _ALLOWED_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid range. Allowed: {', '.join(sorted(_ALLOWED_RANGES))}",
        )

    market = YFinanceProvider()
    try:
        snap = await market.get_chart_snapshot(symbol, key)
        return snap
    except YahooRateLimitError as exc:
        stale = market.get_stale_chart_snapshot(symbol, key)
        if stale is not None:
            return stale
        raise HTTPException(
            status_code=429,
            detail=(
                "Yahoo rate-limited chart requests. Try again in a minute, "
                "or open Yahoo / TradingView for a live chart."
            ),
        ) from exc
    except Exception as exc:
        stale = market.get_stale_chart_snapshot(symbol, key)
        if stale is not None:
            return stale
        raise HTTPException(
            status_code=502,
            detail=f"Could not load chart for {symbol}: {exc}",
        ) from exc
