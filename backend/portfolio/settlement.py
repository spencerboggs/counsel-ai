"""Settlement-aware cash / buying power (paper T+1 + optional Alpaca snapshot)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from backend.portfolio.ledger import TradeLedger
from backend.providers.alpaca import AlpacaClient, active_trading_backend
from backend.storage.database import Database


def _today() -> date:
    return datetime.now(timezone.utc).date()


class SettlementService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._ledger = TradeLedger(db)

    async def mark_settled_up_to(self, as_of: date | None = None) -> int:
        day = (as_of or _today()).isoformat()
        cursor = await self._db.conn.execute(
            """
            UPDATE settlement_events
            SET settled = 1
            WHERE settled = 0 AND soft_deleted = 0 AND settle_date <= ?
            """,
            (day,),
        )
        await self._db.conn.commit()
        return cursor.rowcount or 0

    async def unsettled_cash_delta(self) -> float:
        """Sum of cash_delta not yet settled (buys negative, sells positive)."""
        await self.mark_settled_up_to()
        cursor = await self._db.conn.execute(
            """
            SELECT COALESCE(SUM(cash_delta), 0) AS s
            FROM settlement_events
            WHERE settled = 0 AND soft_deleted = 0
            """
        )
        row = await cursor.fetchone()
        return float(row["s"]) if row else 0.0

    async def paper_snapshot(self) -> dict[str, Any]:
        await self.mark_settled_up_to()
        cash = await self._ledger.paper_cash_balance()
        # Unsettled sell proceeds are in cash balance already for paper, but not
        # withdrawable / not fully reliable buying power until settle_date.
        cursor = await self._db.conn.execute(
            """
            SELECT COALESCE(SUM(cash_delta), 0) AS s
            FROM settlement_events
            WHERE settled = 0 AND soft_deleted = 0 AND cash_delta > 0
            """
        )
        row = await cursor.fetchone()
        unsettled_proceeds = float(row["s"]) if row else 0.0
        # Unsettled buy obligations already deducted from cash at fill time.
        settled_cash = round(cash - unsettled_proceeds, 2)
        withdrawable = settled_cash
        # Conservative BP: settled cash only (never assume unsettled sells fund new buys).
        buying_power = max(0.0, settled_cash)
        return {
            "venue": "paper_local",
            "cash": round(cash, 2),
            "settled_cash": settled_cash,
            "withdrawable_cash": withdrawable,
            "unsettled_proceeds": round(unsettled_proceeds, 2),
            "buying_power": buying_power,
            "equity": None,
            "note": (
                "Paper simulates T+1 settlement. Displayed cash includes unsettled "
                "sale proceeds; buying power uses settled cash only."
            ),
        }

    async def account_snapshot(self) -> dict[str, Any]:
        backend = active_trading_backend()
        if backend == "paper_local":
            return await self.paper_snapshot()

        client = AlpacaClient(live=backend == "live_alpaca")
        paper = await self.paper_snapshot()
        if not client.configured:
            paper["venue"] = backend
            paper["note"] = "Alpaca not configured; showing local settlement mirror."
            return paper

        acct = await client.get_account()
        if not acct or acct.get("error"):
            paper["venue"] = backend
            paper["alpaca_error"] = (acct or {}).get("error")
            paper["note"] = "Alpaca account fetch failed; using local settlement mirror."
            return paper

        def f(key: str) -> float | None:
            try:
                return float(acct.get(key))
            except (TypeError, ValueError):
                return None

        return {
            "venue": backend,
            "cash": f("cash"),
            "settled_cash": f("cash"),  # Alpaca cash is generally settled for equities BP
            "withdrawable_cash": f("cash_withdrawable") or f("cash"),
            "buying_power": f("buying_power"),
            "equity": f("equity"),
            "regt_buying_power": f("regt_buying_power"),
            "daytrading_buying_power": f("daytrading_buying_power"),
            "pattern_day_trader": acct.get("pattern_day_trader"),
            "trading_blocked": acct.get("trading_blocked"),
            "account_blocked": acct.get("account_blocked"),
            "local_mirror": paper,
            "note": (
                "Alpaca account is broker source of truth for live/paper-alpaca. "
                "Local ledger remains the audit/tax mirror. Never assume all cash "
                "is immediately withdrawable."
            ),
        }
