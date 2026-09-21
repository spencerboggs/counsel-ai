"""Autopilot start/stop/status and decision log routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.autopilot.loop import current_run_id, is_loop_running, start_loop, stop_loop
from backend.autopilot.state import AutopilotStore
from backend.portfolio.settlement import SettlementService
from backend.providers.alpaca import active_trading_backend
from backend.storage.research_runs import ResearchRunStore
from backend.storage.run_events import RunEventStore

autopilot_router = APIRouter(prefix="/autopilot", tags=["autopilot"])


class AutopilotStartRequest(BaseModel):
    arm_live_confirmed: bool = False
    cycle_seconds: int = Field(default=120, ge=30, le=3600)
    max_positions: int = Field(default=8, ge=1, le=50)
    max_notional_pct: float = Field(default=0.08, ge=0.01, le=0.5)
    max_new_candidates: int = Field(default=6, ge=1, le=20)


@autopilot_router.post("/start")
async def autopilot_start(
    body: AutopilotStartRequest,
    request: Request,
) -> dict[str, Any]:
    if not hasattr(request.app.state, "background_tasks"):
        request.app.state.background_tasks = set()
    config = {
        "cycle_seconds": body.cycle_seconds,
        "max_positions": body.max_positions,
        "max_notional_pct": body.max_notional_pct,
        "max_new_candidates": body.max_new_candidates,
        "arm_live_confirmed": body.arm_live_confirmed,
    }
    try:
        result = await start_loop(
            request.app.state.db,
            config=config,
            arm_live_confirmed=body.arm_live_confirmed,
            app_background_tasks=request.app.state.background_tasks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@autopilot_router.post("/stop")
async def autopilot_stop(request: Request) -> dict[str, Any]:
    state = await stop_loop(request.app.state.db)
    return {
        "running": False,
        "state": state,
        "note": "Stopped new cycles. Open positions were not auto-liquidated.",
    }


@autopilot_router.get("/status")
async def autopilot_status(request: Request) -> dict[str, Any]:
    db = request.app.state.db
    store = AutopilotStore(db)
    state = await store.get()
    capital = await SettlementService(db).account_snapshot()
    backend = active_trading_backend()
    run_id = current_run_id()
    events: list[dict[str, Any]] = []
    if run_id:
        events = await RunEventStore(db).list_for_run(run_id, limit=40)
    cfg = state.get("config") or {}
    cycle_seconds = int(cfg.get("cycle_seconds") or 120)
    last_cycle = state.get("last_cycle_at")
    from backend.compliance.kill_switch import KillSwitch
    from backend.compliance.market_hours import session_status
    from backend.compliance.risk_gates import trading_config

    tcfg = trading_config()
    return {
        "running": is_loop_running() or bool(state.get("running")),
        "loop_alive": is_loop_running(),
        "mode": backend,
        "is_live": backend == "live_alpaca",
        "run_id": run_id,
        "started_at": state.get("started_at"),
        "stopped_at": state.get("stopped_at"),
        "asleep_since": state.get("asleep_since"),
        "last_cycle_at": last_cycle,
        "cycle_count": state.get("cycle_count") or 0,
        "last_error": state.get("last_error"),
        "config": cfg,
        "last_wake": state.get("last_wake") or {},
        "startup_wake": getattr(request.app.state, "startup_wake", None),
        "capital": capital,
        "cycle_seconds": cycle_seconds,
        "recent_events": events,
        "kill_switch": await KillSwitch(db).status(),
        "market_session": session_status(
            allow_extended_hours=tcfg["allow_extended_hours"]
        ),
        "trading_config": tcfg,
        "note": (
            "Paper ledger cash is not live equity. "
            "Live/paper-Alpaca capital comes from the broker account. "
            "Orders require regular-session hours unless config allows extended."
        ),
    }


@autopilot_router.get("/runs/latest")
async def autopilot_runs_latest(request: Request) -> dict[str, Any] | None:
    db = request.app.state.db
    run = await ResearchRunStore(db).latest("autopilot")
    if run is None:
        return None
    events = await RunEventStore(db).list_for_run(run["id"], limit=100)
    return {**run, "events": events}


@autopilot_router.get("/decisions")
async def autopilot_decisions(
    request: Request,
    limit: int = 40,
) -> dict[str, Any]:
    items = await AutopilotStore(request.app.state.db).list_decisions(limit=min(limit, 100))
    return {"count": len(items), "items": items}


@autopilot_router.get("/learning")
async def autopilot_learning(request: Request, limit: int = 40) -> dict[str, Any]:
    from backend.autopilot.learning import DecisionJournal

    return await DecisionJournal(request.app.state.db).digest(limit=min(limit, 100))
