"""Free-tier risk / freshness checks used by CapitalGate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.compliance.kill_switch import KillSwitch
from backend.compliance.market_hours import session_status
from backend.config.settings import get_app_config
from backend.storage.database import Database


def trading_config() -> dict[str, Any]:
    cfg = get_app_config()
    raw = getattr(cfg, "trading", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "regular_hours_only": bool(raw.get("regular_hours_only", True)),
        "allow_extended_hours": bool(raw.get("allow_extended_hours", False)),
        "quote_max_age_seconds": int(raw.get("quote_max_age_seconds", 120)),
        "max_order_notional": float(raw.get("max_order_notional", 5000)),
        "max_trades_per_day": int(raw.get("max_trades_per_day", 20)),
        "max_daily_realized_loss": float(raw.get("max_daily_realized_loss", 500)),
        "max_positions": int(raw.get("max_positions", 8)),
        "max_symbol_notional_pct": float(raw.get("max_symbol_notional_pct", 0.06)),
        "max_bet_pct": float(raw.get("max_bet_pct", 0.06)),
        "kelly_fraction": float(raw.get("kelly_fraction", 0.5)),
        "kelly_min_edge": float(raw.get("kelly_min_edge", 0.0)),
        "block_duplicate_open_orders": bool(raw.get("block_duplicate_open_orders", True)),
        "reject_abnormal_price_move_pct": float(
            raw.get("reject_abnormal_price_move_pct", 0.35)
        ),
    }


def quote_age_seconds(as_of: str | None) -> float | None:
    if not as_of:
        return None
    try:
        ts = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
    except ValueError:
        return None


async def today_trade_count(db: Database) -> int:
    """Count fills since midnight America/New_York (calendar day for risk caps)."""
    from backend.compliance.market_hours import now_et

    et = now_et()
    start = et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    cursor = await db.conn.execute(
        """
        SELECT COUNT(*) AS n FROM trade_fills
        WHERE soft_deleted = 0 AND executed_at >= ?
        """,
        (start.isoformat(),),
    )
    row = await cursor.fetchone()
    return int(row["n"] if row else 0)


async def today_realized_pnl(db: Database) -> float:
    from backend.compliance.market_hours import now_et

    et = now_et()
    start = et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    cursor = await db.conn.execute(
        """
        SELECT COALESCE(SUM(realized_gain), 0) AS s
        FROM dispositions
        WHERE soft_deleted = 0 AND disposed_at >= ?
        """,
        (start.isoformat(),),
    )
    row = await cursor.fetchone()
    return float(row["s"] if row else 0)


async def open_orders_for_symbol(db: Database, symbol: str) -> list[dict[str, Any]]:
    cursor = await db.conn.execute(
        """
        SELECT * FROM trade_orders
        WHERE soft_deleted = 0
          AND UPPER(symbol) = ?
          AND LOWER(status) IN (
            'new', 'accepted', 'pending', 'submitted',
            'partially_filled', 'pending_new', 'pending_cancel'
          )
        ORDER BY submitted_at DESC
        LIMIT 20
        """,
        (symbol.upper(),),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def assert_execution_allowed(
    db: Database,
    *,
    symbol: str | None = None,
    notional: float | None = None,
    quote_as_of: str | None = None,
    side: str = "buy",
    ignore_hours: bool = False,
) -> dict[str, Any]:
    """Raise CapitalGateError-compatible codes via return or raise from caller.

    Returns a details dict when OK; raises ValueError with (code, message, details).
    """
    from backend.portfolio.capital_gate import CapitalGateError

    tcfg = trading_config()
    kill = KillSwitch(db)
    if await kill.is_disabled():
        st = await kill.status()
        raise CapitalGateError(
            "kill_switch",
            "Trading disabled by emergency kill switch. Re-enable in Settings.",
            st,
        )

    session = session_status(allow_extended_hours=tcfg["allow_extended_hours"])
    if tcfg["regular_hours_only"] and not ignore_hours:
        if not session["open_for_market_orders"]:
            raise CapitalGateError(
                "market_hours",
                "Market closed for new market orders. "
                + (" ".join(session.get("reasons") or []) or session.get("next_hint") or ""),
                session,
            )

    age = quote_age_seconds(quote_as_of)
    max_age = tcfg["quote_max_age_seconds"]
    if quote_as_of is not None and age is not None and age > max_age:
        raise CapitalGateError(
            "stale_quote",
            f"Quote age {int(age)}s exceeds max {max_age}s - refusing to trade on stale data.",
            {"quote_as_of": quote_as_of, "age_seconds": age, "max_age": max_age},
        )

    if notional is not None and notional > tcfg["max_order_notional"] + 0.01:
        raise CapitalGateError(
            "max_order",
            f"Order ${notional:.2f} exceeds max_order_notional ${tcfg['max_order_notional']:.2f}",
            {"notional": notional, "max": tcfg["max_order_notional"]},
        )

    trades = await today_trade_count(db)
    if trades >= tcfg["max_trades_per_day"]:
        raise CapitalGateError(
            "max_trades",
            f"Daily trade cap reached ({trades}/{tcfg['max_trades_per_day']}).",
            {"trades_today": trades, "max": tcfg["max_trades_per_day"]},
        )

    day_pnl = await today_realized_pnl(db)
    if day_pnl <= -abs(tcfg["max_daily_realized_loss"]):
        raise CapitalGateError(
            "daily_loss",
            (
                f"Daily realized loss ${day_pnl:.2f} hit cap "
                f"-${tcfg['max_daily_realized_loss']:.2f}. Trading halted for today."
            ),
            {"day_pnl": day_pnl, "max_loss": tcfg["max_daily_realized_loss"]},
        )

    if symbol and tcfg["block_duplicate_open_orders"] and side == "buy":
        open_orders = await open_orders_for_symbol(db, symbol)
        if open_orders:
            raise CapitalGateError(
                "duplicate_order",
                f"Open/pending order already exists for {symbol.upper()}.",
                {"orders": [{"id": o["id"], "status": o["status"]} for o in open_orders]},
            )

    return {
        "ok": True,
        "session": session,
        "trading_config": tcfg,
        "trades_today": trades,
        "day_realized_pnl": day_pnl,
        "quote_age_seconds": age,
    }
