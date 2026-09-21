"""Paper portfolio routes. Local paper is default; Alpaca is optional and gated."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import (
    PaperPositionCreate,
    PaperPositionOut,
    PortfolioStatsOut,
    TradeOrderRequest,
)
from backend.portfolio.capital_gate import CapitalGateError
from backend.portfolio.executor import TradeExecutor
from backend.portfolio.ledger import TradeLedger
from backend.portfolio.settlement import SettlementService
from backend.portfolio.store import PaperPositionStore
from backend.providers.alpaca import AlpacaClient, active_trading_backend
from backend.providers.yfinance_provider import YFinanceProvider
from backend.storage.candidate_history import CandidateHistoryStore
from backend.autopilot.learning import DecisionJournal

portfolio_router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if number != number:
            return None
        return number
    except (TypeError, ValueError):
        return None


def _to_out(
    row: dict,
    *,
    last_price: float | None = None,
    quote_raw: dict[str, Any] | None = None,
    quote_currency: str | None = None,
    quote_as_of: str | None = None,
    sighting: dict[str, Any] | None = None,
    realized_gain: float | None = None,
) -> PaperPositionOut:
    shares = float(row["shares"])
    basis = float(row["cost_basis"])
    cost_total = round(basis * shares, 2)
    market_value = None
    pnl = None
    pnl_pct = None
    if last_price is not None and row["status"] == "open":
        market_value = round(last_price * shares, 2)
        pnl = round((last_price - basis) * shares, 2)
        if cost_total:
            pnl_pct = round((pnl / cost_total) * 100, 2)

    raw = quote_raw or {}
    return PaperPositionOut(
        id=row["id"],
        ticker=row["ticker"],
        shares=shares,
        cost_basis=basis,
        opened_at=row["opened_at"],
        closed_at=row.get("closed_at"),
        status=row["status"],
        source_run_id=row.get("source_run_id"),
        notes=row.get("notes"),
        last_price=last_price,
        market_value=market_value,
        unrealized_pnl=pnl,
        cost_total=cost_total,
        unrealized_pnl_pct=pnl_pct,
        name=(raw.get("name") or (sighting or {}).get("name")),
        currency=quote_currency,
        change=_safe_float(raw.get("change")),
        change_pct=_safe_float(raw.get("change_pct")),
        previous_close=_safe_float(raw.get("previous_close")),
        day_open=_safe_float(raw.get("day_open")),
        day_high=_safe_float(raw.get("day_high")),
        day_low=_safe_float(raw.get("day_low")),
        market_cap=_safe_float(raw.get("market_cap") or raw.get("marketCap")),
        pe=_safe_float(raw.get("pe") or raw.get("trailingPE")),
        sector=raw.get("sector") or (sighting or {}).get("sector"),
        industry=raw.get("industry"),
        beta=_safe_float(raw.get("beta")),
        avg_volume=_safe_float(raw.get("avg_volume") or raw.get("averageVolume")),
        fifty_two_week_high=_safe_float(
            raw.get("fifty_two_week_high") or raw.get("fiftyTwoWeekHigh")
        ),
        fifty_two_week_low=_safe_float(
            raw.get("fifty_two_week_low") or raw.get("fiftyTwoWeekLow")
        ),
        score=_safe_float((sighting or {}).get("score")),
        signal=(sighting or {}).get("signal"),
        lane=(sighting or {}).get("lane"),
        quote_as_of=quote_as_of,
        realized_gain=realized_gain,
    )


def _gate_http(exc: CapitalGateError) -> HTTPException:
    status = 409 if exc.code == "wash_sale" else 400
    msg = exc.message
    if exc.code == "wash_sale" and exc.details.get("override_phrase"):
        msg = f"{exc.message} [override: {exc.details['override_phrase']}]"
    return HTTPException(status_code=status, detail=msg)


@portfolio_router.get("/mode")
async def portfolio_mode() -> dict:
    backend = active_trading_backend()
    return {
        "backend": backend,
        "is_paper": backend.startswith("paper"),
        "is_live": backend == "live_alpaca",
        "label": {
            "paper_local": "PAPER (local free ledger)",
            "paper_alpaca": "PAPER (Alpaca paper account)",
            "live_alpaca": "LIVE (Alpaca - real money)",
        }.get(backend, backend),
    }


@portfolio_router.get("/stats", response_model=PortfolioStatsOut)
async def portfolio_stats(request: Request) -> PortfolioStatsOut:
    store = PaperPositionStore(request.app.state.db)
    ledger = TradeLedger(request.app.state.db)
    open_rows = await store.list_positions("open")
    closed_rows = await store.list_positions("closed")
    market = YFinanceProvider()
    invested = 0.0
    market_value = 0.0
    unrealized = 0.0
    for row in open_rows:
        cost = float(row["cost_basis"]) * float(row["shares"])
        invested += cost
        try:
            quote = await market.get_quote(row["ticker"])
            price = quote.price or float(row["cost_basis"])
        except Exception:
            price = float(row["cost_basis"])
        value = price * float(row["shares"])
        market_value += value
        unrealized += value - cost
    realized = await ledger.realized_summary()
    avg = (invested / len(open_rows)) if open_rows else None
    return PortfolioStatsOut(
        trading_mode=active_trading_backend(),
        open_positions=len(open_rows),
        closed_positions=len(closed_rows),
        invested_cost=round(invested, 2),
        market_value=round(market_value, 2),
        unrealized_pnl=round(unrealized, 2),
        realized_closed=len(closed_rows),
        avg_position_size=round(avg, 2) if avg is not None else None,
        win_count=None,
    )


@portfolio_router.get("/capital")
async def portfolio_capital(request: Request) -> dict:
    return await SettlementService(request.app.state.db).account_snapshot()


@portfolio_router.get("/positions", response_model=list[PaperPositionOut])
async def list_positions(request: Request, status: str = "open") -> list[PaperPositionOut]:
    store = PaperPositionStore(request.app.state.db)
    history = CandidateHistoryStore(request.app.state.db)
    rows = await store.list_positions(status=status if status != "all" else None)
    market = YFinanceProvider()
    out: list[PaperPositionOut] = []
    for row in rows:
        last_price = None
        quote_raw: dict[str, Any] = {}
        currency = None
        as_of = None
        if row["status"] == "open":
            try:
                quote = await market.get_quote(row["ticker"])
                last_price = quote.price
                quote_raw = dict(quote.raw or {})
                currency = quote.currency
                as_of = quote.as_of
            except Exception:
                last_price = None
        sighting = await history.latest_for_ticker(row["ticker"])
        out.append(
            _to_out(
                row,
                last_price=last_price,
                quote_raw=quote_raw,
                quote_currency=currency,
                quote_as_of=as_of,
                sighting=sighting,
            )
        )
    return out


@portfolio_router.post("/positions", response_model=PaperPositionOut)
async def open_position(
    body: PaperPositionCreate,
    request: Request,
) -> PaperPositionOut:
    executor = TradeExecutor(request.app.state.db)
    try:
        result = await executor.buy(
            ticker=body.ticker,
            shares=body.shares,
            price=body.cost_basis,
            source_run_id=body.source_run_id,
            notes=body.notes,
            wash_override_phrase=body.wash_override_phrase,
        )
    except CapitalGateError as exc:
        raise _gate_http(exc) from exc
    return _to_out(result["position"], last_price=body.cost_basis)


@portfolio_router.post("/orders", response_model=PaperPositionOut)
async def place_order(body: TradeOrderRequest, request: Request) -> PaperPositionOut:
    executor = TradeExecutor(request.app.state.db)
    try:
        result = await executor.buy(
            ticker=body.ticker,
            shares=0,
            price=body.price,
            notional=body.notional,
            source_run_id=body.source_run_id,
            wash_override_phrase=body.wash_override_phrase,
            venue=body.venue,
            live_confirmed=body.live_confirmed,
        )
    except CapitalGateError as exc:
        raise _gate_http(exc) from exc
    pos = result["position"]
    return _to_out(pos, last_price=float(pos["cost_basis"]))


@portfolio_router.post("/positions/{position_id}/close", response_model=PaperPositionOut)
async def close_position(position_id: str, request: Request) -> PaperPositionOut:
    executor = TradeExecutor(request.app.state.db)
    try:
        result = await executor.sell(position_id=position_id)
    except CapitalGateError as exc:
        raise _gate_http(exc) from exc
    row = result["position"]
    if row is None:
        raise HTTPException(status_code=404, detail="Open paper position not found")
    return _to_out(row, realized_gain=result.get("realized_gain"))


@portfolio_router.get("/broker/monitor")
async def broker_monitor(request: Request) -> dict[str, Any]:
    """Alpaca paper/live account + positions + open orders (free with user keys)."""
    backend = active_trading_backend()
    local = await SettlementService(request.app.state.db).account_snapshot()
    journal = await DecisionJournal(request.app.state.db).digest(limit=25)
    if backend == "paper_local":
        return {
            "venue": backend,
            "broker": None,
            "local_capital": local,
            "learning_journal": journal,
            "note": (
                "Local paper ledger active. Add free Alpaca paper keys and set "
                "mode to paper_alpaca to monitor broker positions/equity curve."
            ),
        }
    client = AlpacaClient(live=backend == "live_alpaca")
    snap = await client.monitor_snapshot()
    return {
        "venue": backend,
        "broker": snap,
        "local_capital": local,
        "learning_journal": journal,
    }
