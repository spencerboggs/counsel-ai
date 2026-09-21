"""Feature bundles for Autopilot candidates (strategies.md quantitative spine)."""

from __future__ import annotations

from typing import Any

from backend.autopilot.sec_edgar import recent_filings
from backend.providers.base import HistoryBar
from backend.providers.yfinance_provider import YFinanceProvider
from backend.research.discovery.catalysts import score_news_for_catalysts


def _closes(history: list[HistoryBar]) -> list[float]:
    return [float(b.close) for b in history if b.close is not None]


def _momentum(closes: list[float], days: int) -> float | None:
    if len(closes) <= days or closes[-days - 1] == 0:
        return None
    return closes[-1] / closes[-days - 1] - 1.0


def _ma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def historical_probe(closes: list[float], *, lookback: int = 120) -> dict[str, Any]:
    """In-sample forward-return stats when momentum was strong."""
    if len(closes) < lookback + 15:
        return {
            "samples": 0,
            "note": "Insufficient history for probe.",
        }
    hits: list[dict[str, float]] = []
    start = max(60, len(closes) - lookback)
    for i in range(start, len(closes) - 11):
        window = closes[: i + 1]
        mom = _momentum(window, 20)
        ma200 = _ma(window, min(200, len(window)))
        if mom is None or mom < 0.05:
            continue
        if ma200 is not None and window[-1] < ma200:
            continue
        base = closes[i]
        if not base:
            continue
        fwd = {}
        for d in (1, 3, 5, 10):
            if i + d < len(closes) and closes[i + d]:
                fwd[f"d{d}"] = closes[i + d] / base - 1.0
        if fwd:
            hits.append(fwd)
    if not hits:
        return {"samples": 0, "note": "No similar historical hits in window."}

    def stats(key: str) -> dict[str, float | None]:
        vals = [h[key] for h in hits if key in h]
        if not vals:
            return {"mean": None, "win_rate": None}
        wins = sum(1 for v in vals if v > 0)
        return {
            "mean": round(sum(vals) / len(vals), 4),
            "win_rate": round(wins / len(vals), 3),
            "n": len(vals),
        }

    return {
        "samples": len(hits),
        "forward": {k: stats(k) for k in ("d1", "d3", "d5", "d10")},
        "note": "In-sample probe only. Not out-of-sample validation.",
    }


def history_context(closes: list[float], history: list[HistoryBar]) -> dict[str, Any]:
    """Compact historical context from Yahoo daily bars for crew prompts."""
    if len(closes) < 5:
        return {"bars": len(closes), "note": "Insufficient history."}
    last = closes[-1]
    def ret(days: int) -> float | None:
        if len(closes) <= days or not closes[-days - 1]:
            return None
        return round(closes[-1] / closes[-days - 1] - 1.0, 4)

    # Simple realized vol (20d)
    rets = []
    for i in range(1, min(21, len(closes))):
        if closes[-i - 1]:
            rets.append(closes[-i] / closes[-i - 1] - 1.0)
    vol = None
    if len(rets) >= 5:
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / len(rets)
        vol = round((var ** 0.5) * (252 ** 0.5), 4)

    hi_52 = max(closes[-252:]) if len(closes) >= 20 else max(closes)
    lo_52 = min(closes[-252:]) if len(closes) >= 20 else min(closes)
    # Last ~10 session closes for shape
    recent = [
        {"date": history[i].date, "close": float(history[i].close)}
        for i in range(max(0, len(history) - 10), len(history))
        if history[i].close is not None
    ]
    return {
        "bars": len(closes),
        "return_5d": ret(5),
        "return_20d": ret(20),
        "return_60d": ret(60),
        "return_120d": ret(120),
        "vol_20d_ann": vol,
        "pct_from_52w_high": round(last / hi_52 - 1.0, 4) if hi_52 else None,
        "pct_from_52w_low": round(last / lo_52 - 1.0, 4) if lo_52 else None,
        "recent_closes": recent,
        "note": "Yahoo daily history. Historical returns do not predict future results.",
    }


async def build_features(
    ticker: str,
    *,
    market: YFinanceProvider | None = None,
    buying_power: float | None = None,
) -> dict[str, Any]:
    market = market or YFinanceProvider()
    symbol = ticker.upper().strip()
    quote = await market.get_quote(symbol)
    history = await market.get_history(symbol, "1y")
    financials = await market.get_financials(symbol)
    try:
        news = await market.get_news(symbol)
    except Exception:
        news = []
    closes = _closes(history)
    price = quote.price or (closes[-1] if closes else None)
    mom20 = _momentum(closes, 20)
    mom60 = _momentum(closes, 60)
    ma50 = _ma(closes, 50)
    ma200 = _ma(closes, 200)
    above_50 = bool(ma50 and price and price > ma50)
    above_200 = bool(ma200 and price and price > ma200)
    cat_score, cat_labels, cat_headline, horizon = score_news_for_catalysts(news, hold_days=5)
    info = financials if isinstance(financials, dict) else {}
    pe = info.get("trailingPE") or info.get("pe")
    roe = info.get("returnOnEquity") or info.get("roe")
    margins = info.get("profitMargins") or info.get("profit_margin")
    revenue_growth = info.get("revenueGrowth") or info.get("revenue_growth")
    shares_buyable = None
    if price and buying_power and price > 0:
        shares_buyable = int(float(buying_power) // float(price))

    filings: list[dict[str, Any]] = []
    try:
        filings = await recent_filings(symbol, limit=6)
    except Exception:
        filings = []

    probe = historical_probe(closes)
    hist_ctx = history_context(closes, history)

    from backend.portfolio.kelly import kelly_fraction_from_probe, size_notional

    kelly = kelly_fraction_from_probe(probe)
    sizing = None
    if buying_power is not None:
        sizing = size_notional(equity_or_bp=float(buying_power), probe=probe)

    signal_score = 40.0
    if mom20 is not None:
        signal_score += max(-15, min(25, mom20 * 100))
    if above_50:
        signal_score += 8
    if above_200:
        signal_score += 6
    signal_score += (cat_score - 50) * 0.25
    if revenue_growth is not None:
        try:
            signal_score += max(-8, min(12, float(revenue_growth) * 40))
        except (TypeError, ValueError):
            pass
    # Soft boost when probe has edge
    if kelly.get("bet_pct", 0) > 0:
        signal_score += min(8, float(kelly["bet_pct"]) * 100)
    signal_score = max(0.0, min(100.0, signal_score))

    return {
        "ticker": symbol,
        "price": price,
        "currency": quote.currency,
        "momentum_20d": mom20,
        "momentum_60d": mom60,
        "above_50dma": above_50,
        "above_200dma": above_200,
        "pe": pe,
        "roe": roe,
        "profit_margin": margins,
        "revenue_growth": revenue_growth,
        "catalyst_score": cat_score,
        "catalyst_labels": cat_labels,
        "catalyst_headline": cat_headline,
        "horizon_fit": horizon,
        "news_count": len(news),
        "filings": filings,
        "historical_probe": probe,
        "history_context": hist_ctx,
        "kelly": kelly,
        "suggested_sizing": sizing,
        "shares_buyable": shares_buyable,
        "signal_score": round(signal_score, 1),
        "name": (quote.raw or {}).get("name") if isinstance(quote.raw, dict) else None,
        "sector": (quote.raw or {}).get("sector") if isinstance(quote.raw, dict) else None,
    }
