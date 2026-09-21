"""Settings / secrets / trading mode routes. Secrets are never echoed back."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.schemas import SecretsUpdateRequest
from backend.compliance.kill_switch import KillSwitch
from backend.compliance.market_hours import session_status
from backend.compliance.risk_gates import trading_config, today_realized_pnl, today_trade_count
from backend.config.secrets import (
    load_secrets,
    save_secrets,
    secrets_status,
)
from backend.providers.alpaca import AlpacaClient, active_trading_backend

settings_router = APIRouter(prefix="/settings", tags=["settings"])


class KillSwitchRequest(BaseModel):
    trading_disabled: bool
    notes: str | None = Field(default=None, max_length=500)


@settings_router.get("/secrets/status")
async def get_secrets_status(request: Request) -> dict:
    status = secrets_status()
    status["active_backend"] = active_trading_backend()
    kill = await KillSwitch(request.app.state.db).status()
    status["kill_switch"] = kill
    status["market_session"] = session_status(
        allow_extended_hours=trading_config()["allow_extended_hours"]
    )
    status["trading_config"] = trading_config()
    return status


@settings_router.put("/secrets")
async def update_secrets(body: SecretsUpdateRequest) -> dict:
    current = load_secrets()
    data = current.model_dump()

    for field in body.clear_fields:
        if field in data:
            if field == "live_trading_confirmed":
                data[field] = False
            elif field == "trading_mode":
                data[field] = "paper_local"
            else:
                data[field] = None

    updates = body.model_dump(exclude_unset=True)
    updates.pop("clear_fields", None)
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        data[key] = value

    mode = data.get("trading_mode") or "paper_local"
    if mode not in {"paper_local", "paper_alpaca", "live_alpaca"}:
        raise HTTPException(status_code=400, detail="Invalid trading_mode")

    if mode == "live_alpaca":
        if not data.get("live_trading_confirmed"):
            raise HTTPException(
                status_code=400,
                detail="Live trading requires live_trading_confirmed=true",
            )
        if not (data.get("alpaca_live_key") and data.get("alpaca_live_secret")):
            raise HTTPException(
                status_code=400,
                detail="Live trading requires Alpaca live key and secret",
            )

    if mode == "paper_alpaca" and not (
        data.get("alpaca_paper_key") and data.get("alpaca_paper_secret")
    ):
        raise HTTPException(
            status_code=400,
            detail="Alpaca paper mode requires paper key and secret",
        )

    from backend.config.secrets import SecretsFile

    save_secrets(SecretsFile.model_validate(data))
    status = secrets_status()
    status["active_backend"] = active_trading_backend()
    return status


@settings_router.get("/trading/account")
async def trading_account_probe() -> dict:
    backend = active_trading_backend()
    if backend == "paper_local":
        return {
            "backend": backend,
            "message": "Using free local paper ledger (no broker key)",
        }
    client = AlpacaClient(live=backend == "live_alpaca")
    account = await client.get_account()
    return {"backend": backend, "account": account}


@settings_router.get("/trading/session")
async def trading_session() -> dict:
    tcfg = trading_config()
    return {
        "session": session_status(allow_extended_hours=tcfg["allow_extended_hours"]),
        "trading_config": tcfg,
        "note": "All risk gates are free/local. Paid APIs are never required.",
    }


@settings_router.get("/trading/kill-switch")
async def get_kill_switch(request: Request) -> dict:
    return await KillSwitch(request.app.state.db).status()


@settings_router.post("/trading/kill-switch")
async def set_kill_switch(body: KillSwitchRequest, request: Request) -> dict:
    kill = KillSwitch(request.app.state.db)
    result = await kill.set_disabled(
        body.trading_disabled,
        notes=body.notes
        or ("Emergency disable" if body.trading_disabled else "Re-enabled"),
    )
    # Stop Autopilot new cycles when killing
    if body.trading_disabled:
        try:
            from backend.autopilot.loop import is_loop_running, stop_loop

            if is_loop_running():
                await stop_loop(request.app.state.db)
                result["autopilot_stopped"] = True
        except Exception as exc:
            result["autopilot_stop_error"] = str(exc)
    return result


@settings_router.get("/trading/risk-snapshot")
async def risk_snapshot(request: Request) -> dict:
    db = request.app.state.db
    return {
        "trades_today": await today_trade_count(db),
        "day_realized_pnl": await today_realized_pnl(db),
        "kill_switch": await KillSwitch(db).status(),
        "session": session_status(
            allow_extended_hours=trading_config()["allow_extended_hours"]
        ),
        "trading_config": trading_config(),
    }
