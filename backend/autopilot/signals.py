"""Signal generation for Autopilot cycles."""

from __future__ import annotations

from typing import Any

from backend.autopilot.features import build_features
from backend.autopilot.fred import fred_snapshot
from backend.autopilot.learning import DecisionJournal
from backend.data.universe_us import get_universe
from backend.portfolio.settlement import SettlementService
from backend.portfolio.store import PaperPositionStore
from backend.portfolio.wash_sales import WashSaleService
from backend.providers.alpaca import AlpacaClient, active_trading_backend
from backend.providers.yfinance_provider import YFinanceProvider
from backend.storage.candidate_history import CandidateHistoryStore
from backend.storage.database import Database


async def gather_cycle_context(
    db: Database,
    *,
    max_new_candidates: int = 8,
    universe_sample: int = 40,
) -> dict[str, Any]:
    capital = await SettlementService(db).account_snapshot()
    bp = float(capital.get("buying_power") or 0)
    wash = WashSaleService(db)
    blocked = {b["symbol"].upper() for b in await wash.active_blocks()}
    open_rows = await PaperPositionStore(db).list_positions("open")
    open_tickers = [str(r["ticker"]).upper() for r in open_rows]

    # Prefer recent Found-stock archives, then a shuffled universe sample.
    history = CandidateHistoryStore(db)
    sightings = await history.list_all(limit=80)
    archive = [
        str(s["ticker"]).upper()
        for s in sightings
        if s.get("ticker") and float(s.get("score") or 0) >= 55
    ]
    universe = get_universe(limit=universe_sample, shuffle_seed="autopilot")
    ordered: list[str] = []
    for t in open_tickers + archive + universe:
        u = t.upper()
        if u not in ordered and u not in blocked:
            ordered.append(u)

    market = YFinanceProvider()
    watched: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for symbol in ordered[: max(len(open_tickers) + max_new_candidates, max_new_candidates)]:
        try:
            feat = await build_features(symbol, market=market, buying_power=bp)
        except Exception:
            continue
        feat["wash_blocked"] = symbol in blocked
        if symbol in open_tickers:
            watched.append(feat)
        elif len(candidates) < max_new_candidates and feat.get("signal_score", 0) >= 55:
            if feat.get("shares_buyable") is None or feat["shares_buyable"] >= 1:
                candidates.append(feat)

    candidates.sort(key=lambda f: float(f.get("signal_score") or 0), reverse=True)
    macro = await fred_snapshot()
    allowlist = sorted({*(open_tickers), *(c["ticker"] for c in candidates)})

    journal = await DecisionJournal(db).digest(limit=40)

    broker_monitor = None
    backend = active_trading_backend()
    if backend in {"paper_alpaca", "live_alpaca"}:
        try:
            broker_monitor = await AlpacaClient(live=backend == "live_alpaca").monitor_snapshot()
        except Exception as exc:
            broker_monitor = {"error": str(exc), "venue": backend}

    return {
        "capital": capital,
        "buying_power": bp,
        "wash_blocks": list(blocked),
        "open_positions": open_rows,
        "watched": watched,
        "candidates": candidates[:max_new_candidates],
        "allowlist": allowlist,
        "macro": macro,
        "learning_journal": journal,
        "broker_monitor": broker_monitor,
        "disclaimer": (
            "Signals use quantitative heuristics and in-sample probes. "
            "Kelly sizes are fractional and capped near 6%. "
            "Capital, wash, and market-hours gates still apply. "
            "Data sources: Yahoo, public SEC, optional FRED."
        ),
    }
