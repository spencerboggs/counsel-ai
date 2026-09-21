"""Wash-sale detection and hard-block repurchase guards (same ticker, v1)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.storage.database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _parse_date(value: str) -> date:
    text = value.strip()
    if "T" in text:
        text = text.replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone(timezone.utc).date()
    return date.fromisoformat(text[:10])


WASH_WINDOW_DAYS = 30


class WashSaleService:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_loss_sale(
        self,
        *,
        symbol: str,
        disposition_id: str,
        loss_amount: float,
        disposed_at: str,
    ) -> dict[str, Any]:
        day = _parse_date(disposed_at)
        start = (day - timedelta(days=WASH_WINDOW_DAYS)).isoformat()
        end = (day + timedelta(days=WASH_WINDOW_DAYS)).isoformat()
        event_id = _uid("wash")
        await self._db.conn.execute(
            """
            INSERT INTO wash_sale_events (
                id, symbol, disposition_id, loss_amount, window_start, window_end,
                event_type, disallowed_loss, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'loss_sale', ?, ?)
            """,
            (
                event_id,
                symbol.upper(),
                disposition_id,
                float(loss_amount),
                start,
                end,
                float(loss_amount),
                _now(),
            ),
        )
        return {
            "id": event_id,
            "symbol": symbol.upper(),
            "window_start": start,
            "window_end": end,
            "loss_amount": loss_amount,
        }

    async def record_replacement(
        self,
        *,
        symbol: str,
        lot_id: str,
        fill_id: str,
        disposition_id: str | None,
        disallowed_loss: float,
        basis_adjustment: float,
        override_confirmed: bool,
    ) -> None:
        # Find active window for symbol
        block = await self.block_status(symbol)
        start = block["window_start"] if block else date.today().isoformat()
        end = block["window_end"] if block else (
            date.today() + timedelta(days=WASH_WINDOW_DAYS)
        ).isoformat()
        await self._db.conn.execute(
            """
            INSERT INTO wash_sale_events (
                id, symbol, disposition_id, loss_amount, window_start, window_end,
                event_type, related_fill_id, related_lot_id, disallowed_loss,
                basis_adjustment, override_confirmed, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'replacement_buy', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _uid("wash"),
                symbol.upper(),
                disposition_id,
                float(disallowed_loss),
                start,
                end,
                fill_id,
                lot_id,
                float(disallowed_loss),
                float(basis_adjustment),
                1 if override_confirmed else 0,
                "Replacement purchase during wash window; basis adjusted.",
                _now(),
            ),
        )

    async def pending_disallowed_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Latest loss_sale still inside wash window for this symbol."""
        today = date.today().isoformat()
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM wash_sale_events
            WHERE symbol = ?
              AND event_type = 'loss_sale'
              AND soft_deleted = 0
              AND window_start <= ?
              AND window_end >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (symbol.upper(), today, today),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def block_status(self, symbol: str) -> dict[str, Any] | None:
        """If repurchase should be hard-blocked, return window info."""
        pending = await self.pending_disallowed_for_symbol(symbol)
        if not pending:
            return None
        return {
            "blocked": True,
            "symbol": symbol.upper(),
            "window_start": pending["window_start"],
            "window_end": pending["window_end"],
            "loss_amount": float(pending["loss_amount"]),
            "disposition_id": pending.get("disposition_id"),
            "message": (
                f"{symbol.upper()} is in a wash-sale window until {pending['window_end']}. "
                "Buying again would disallow the prior loss for tax purposes. "
                f"Override requires typing: BUY {symbol.upper()} WASH OVERRIDE"
            ),
            "override_phrase": f"BUY {symbol.upper()} WASH OVERRIDE",
            "note": (
                "v1 treats same ticker as substantially identical. "
                "Brokers may not see all accounts; you remain responsible for IRS reporting."
            ),
        }

    async def assert_buy_allowed(
        self,
        symbol: str,
        *,
        wash_override_phrase: str | None = None,
    ) -> dict[str, Any]:
        status = await self.block_status(symbol)
        if status is None:
            return {"allowed": True, "override": False}
        expected = status["override_phrase"]
        if wash_override_phrase and wash_override_phrase.strip() == expected:
            return {"allowed": True, "override": True, "block": status}
        return {"allowed": False, "override": False, "block": status}

    async def active_blocks(self) -> list[dict[str, Any]]:
        today = date.today().isoformat()
        cursor = await self._db.conn.execute(
            """
            SELECT symbol, MAX(window_end) AS window_end, MAX(window_start) AS window_start,
                   SUM(loss_amount) AS loss_amount
            FROM wash_sale_events
            WHERE event_type = 'loss_sale'
              AND soft_deleted = 0
              AND window_start <= ?
              AND window_end >= ?
            GROUP BY symbol
            ORDER BY window_end ASC
            """,
            (today, today),
        )
        rows = []
        for row in await cursor.fetchall():
            sym = str(row["symbol"])
            rows.append(
                {
                    "symbol": sym,
                    "window_start": row["window_start"],
                    "window_end": row["window_end"],
                    "loss_amount": float(row["loss_amount"] or 0),
                    "override_phrase": f"BUY {sym} WASH OVERRIDE",
                }
            )
        return rows
