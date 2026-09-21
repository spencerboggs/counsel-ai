"""Immutable trade ledger: orders, fills, tax lots, dispositions, audit."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.storage.database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _parse_date(value: str) -> date:
    """Parse ISO timestamp or date to calendar date (UTC)."""
    text = value.strip()
    if "T" in text:
        text = text.replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone(timezone.utc).date()
    return date.fromisoformat(text[:10])


def next_settle_date(trade_day: date) -> date:
    """US equity T+1: next weekday after trade date (holidays ignored v1)."""
    settle = trade_day + timedelta(days=1)
    while settle.weekday() >= 5:
        settle += timedelta(days=1)
    return settle


class TradeLedger:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def audit(
        self,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "system",
    ) -> None:
        await self._db.conn.execute(
            """
            INSERT INTO audit_log (created_at, action, entity_type, entity_id, payload_json, actor)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                action,
                entity_type,
                entity_id,
                json.dumps(payload) if payload is not None else None,
                actor,
            ),
        )

    async def paper_cash_balance(self) -> float:
        cursor = await self._db.conn.execute(
            "SELECT balance_after FROM paper_cash_ledger ORDER BY created_at DESC, rowid DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return float(row["balance_after"]) if row else 0.0

    async def _append_cash(
        self,
        kind: str,
        amount: float,
        *,
        fill_id: str | None = None,
        notes: str | None = None,
    ) -> float:
        balance = await self.paper_cash_balance()
        new_balance = round(balance + amount, 4)
        await self._db.conn.execute(
            """
            INSERT INTO paper_cash_ledger (id, created_at, kind, amount, balance_after, fill_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_uid("cash"), _now(), kind, amount, new_balance, fill_id, notes),
        )
        return new_balance

    async def create_order(
        self,
        *,
        venue: str,
        symbol: str,
        side: str,
        qty: float,
        status: str = "submitted",
        order_type: str = "market",
        time_in_force: str = "day",
        broker_order_id: str | None = None,
        source_run_id: str | None = None,
        notes: str | None = None,
        raw: dict[str, Any] | None = None,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        order_id = _uid("ord")
        client_id = client_order_id or _uid("clid")
        now = _now()
        await self._db.conn.execute(
            """
            INSERT INTO trade_orders (
                id, client_order_id, broker_order_id, venue, symbol, side, qty,
                order_type, time_in_force, status, submitted_at, updated_at,
                source_run_id, notes, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                client_id,
                broker_order_id,
                venue,
                symbol.upper(),
                side.lower(),
                float(qty),
                order_type,
                time_in_force,
                status,
                now,
                now,
                source_run_id,
                notes,
                json.dumps(raw) if raw else None,
            ),
        )
        await self.audit(
            "order_created",
            "trade_order",
            order_id,
            {"symbol": symbol.upper(), "side": side, "qty": qty, "venue": venue},
        )
        await self._db.conn.commit()
        return await self.get_order(order_id)  # type: ignore[return-value]

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM trade_orders WHERE id = ? AND soft_deleted = 0",
            (order_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_order_status(
        self,
        order_id: str,
        status: str,
        *,
        broker_order_id: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        await self._db.conn.execute(
            """
            UPDATE trade_orders
            SET status = ?, updated_at = ?,
                broker_order_id = COALESCE(?, broker_order_id),
                raw_json = COALESCE(?, raw_json)
            WHERE id = ?
            """,
            (
                status,
                _now(),
                broker_order_id,
                json.dumps(raw) if raw else None,
                order_id,
            ),
        )
        await self.audit("order_status", "trade_order", order_id, {"status": status})
        await self._db.conn.commit()

    async def record_fill(
        self,
        *,
        order_id: str,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fees: float = 0.0,
        executed_at: str | None = None,
        broker_fill_id: str | None = None,
        raw: dict[str, Any] | None = None,
        adjust_paper_cash: bool = True,
        wash_override: bool = False,
    ) -> dict[str, Any]:
        """Record a fill and update lots / dispositions / settlement / cash."""
        fill_id = _uid("fill")
        when = executed_at or _now()
        symbol_u = symbol.upper()
        side_l = side.lower()
        qty_f = float(qty)
        price_f = float(price)
        fees_f = float(fees)

        await self._db.conn.execute(
            """
            INSERT INTO trade_fills (
                id, order_id, broker_fill_id, symbol, side, qty, price, fees,
                executed_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_id,
                order_id,
                broker_fill_id,
                symbol_u,
                side_l,
                qty_f,
                price_f,
                fees_f,
                when,
                json.dumps(raw) if raw else None,
            ),
        )
        await self.audit(
            "fill_recorded",
            "trade_fill",
            fill_id,
            {"symbol": symbol_u, "side": side_l, "qty": qty_f, "price": price_f},
        )

        trade_day = _parse_date(when)
        settle_day = next_settle_date(trade_day)
        if side_l == "buy":
            cash_delta = -(qty_f * price_f + fees_f)
        else:
            cash_delta = qty_f * price_f - fees_f

        await self._db.conn.execute(
            """
            INSERT INTO settlement_events (
                id, fill_id, symbol, trade_date, settle_date, cash_delta, settled, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                _uid("setl"),
                fill_id,
                symbol_u,
                trade_day.isoformat(),
                settle_day.isoformat(),
                cash_delta,
                _now(),
            ),
        )

        if adjust_paper_cash:
            await self._append_cash(
                f"fill_{side_l}",
                cash_delta,
                fill_id=fill_id,
                notes=f"{side_l} {qty_f} {symbol_u} @ {price_f}",
            )

        result: dict[str, Any] = {"fill_id": fill_id, "order_id": order_id}

        if side_l == "buy":
            lot = await self._open_lot(
                symbol_u,
                qty_f,
                price_f,
                when,
                fill_id,
                wash_override=wash_override,
            )
            result["lot_id"] = lot["id"]
        else:
            dispositions = await self._dispose_fifo(
                symbol_u, qty_f, price_f, fees_f, when, fill_id
            )
            result["dispositions"] = dispositions

        await self.update_order_status(order_id, "filled")
        await self._db.conn.commit()
        return result

    async def _open_lot(
        self,
        symbol: str,
        qty: float,
        price: float,
        acquired_at: str,
        fill_id: str,
        *,
        wash_override: bool = False,
    ) -> dict[str, Any]:
        from backend.portfolio.wash_sales import WashSaleService

        lot_id = _uid("lot")
        basis = float(price)
        adjusted = basis
        wash_adjusted = 0
        wash = WashSaleService(self._db)
        pending = await wash.pending_disallowed_for_symbol(symbol)
        if pending and wash_override:
            # Attach disallowed loss to replacement lot basis.
            adj = float(pending.get("disallowed_loss") or 0)
            if adj > 0 and qty > 0:
                adjusted = round(basis + (adj / qty), 6)
                wash_adjusted = 1
                await wash.record_replacement(
                    symbol=symbol,
                    lot_id=lot_id,
                    fill_id=fill_id,
                    disposition_id=pending.get("disposition_id"),
                    disallowed_loss=adj,
                    basis_adjustment=adj,
                    override_confirmed=True,
                )

        await self._db.conn.execute(
            """
            INSERT INTO tax_lots (
                id, symbol, qty_open, qty_original, cost_basis_per_share,
                adjusted_basis_per_share, acquired_at, source_fill_id, status, wash_adjusted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                lot_id,
                symbol,
                qty,
                qty,
                basis,
                adjusted,
                acquired_at,
                fill_id,
                wash_adjusted,
            ),
        )
        await self.audit("lot_opened", "tax_lot", lot_id, {"symbol": symbol, "qty": qty})
        return {
            "id": lot_id,
            "symbol": symbol,
            "qty": qty,
            "basis": adjusted,
        }

    async def _dispose_fifo(
        self,
        symbol: str,
        qty: float,
        price: float,
        fees: float,
        disposed_at: str,
        sell_fill_id: str,
    ) -> list[dict[str, Any]]:
        from backend.portfolio.wash_sales import WashSaleService

        remaining = float(qty)
        fee_per_share = float(fees) / qty if qty else 0.0
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM tax_lots
            WHERE symbol = ? AND status IN ('open', 'partial') AND qty_open > 0
              AND soft_deleted = 0
            ORDER BY acquired_at ASC, rowid ASC
            """,
            (symbol,),
        )
        lots = [dict(r) for r in await cursor.fetchall()]
        out: list[dict[str, Any]] = []
        wash = WashSaleService(self._db)

        for lot in lots:
            if remaining <= 1e-9:
                break
            take = min(float(lot["qty_open"]), remaining)
            basis_ps = float(
                lot["adjusted_basis_per_share"]
                if lot.get("adjusted_basis_per_share") is not None
                else lot["cost_basis_per_share"]
            )
            proceeds = round(take * price, 4)
            cost = round(take * basis_ps, 4)
            alloc_fees = round(take * fee_per_share, 4)
            realized = round(proceeds - cost - alloc_fees, 4)
            acquired = lot["acquired_at"]
            holding = (_parse_date(disposed_at) - _parse_date(acquired)).days
            disp_id = _uid("disp")
            wash_disallowed = 0.0
            if realized < 0:
                wash_disallowed = abs(realized)

            await self._db.conn.execute(
                """
                INSERT INTO dispositions (
                    id, sell_fill_id, lot_id, symbol, qty, proceeds, cost, fees,
                    realized_gain, holding_days, acquired_at, disposed_at,
                    wash_disallowed_loss
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    disp_id,
                    sell_fill_id,
                    lot["id"],
                    symbol,
                    take,
                    proceeds,
                    cost,
                    alloc_fees,
                    realized,
                    holding,
                    acquired,
                    disposed_at,
                    wash_disallowed if realized < 0 else 0.0,
                ),
            )

            new_open = round(float(lot["qty_open"]) - take, 6)
            status = "closed" if new_open <= 1e-9 else "partial"
            await self._db.conn.execute(
                "UPDATE tax_lots SET qty_open = ?, status = ? WHERE id = ?",
                (max(0.0, new_open), status, lot["id"]),
            )

            if realized < 0:
                await wash.record_loss_sale(
                    symbol=symbol,
                    disposition_id=disp_id,
                    loss_amount=abs(realized),
                    disposed_at=disposed_at,
                )

            await self.audit(
                "disposition",
                "disposition",
                disp_id,
                {
                    "symbol": symbol,
                    "qty": take,
                    "realized_gain": realized,
                    "holding_days": holding,
                },
            )
            out.append(
                {
                    "id": disp_id,
                    "lot_id": lot["id"],
                    "qty": take,
                    "realized_gain": realized,
                    "holding_days": holding,
                }
            )
            remaining = round(remaining - take, 6)

        if remaining > 1e-6:
            raise ValueError(
                f"Insufficient lots to sell {qty} {symbol}; short by {remaining}"
            )
        return out

    async def open_lots(self) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM tax_lots
            WHERE status IN ('open', 'partial') AND qty_open > 0 AND soft_deleted = 0
            ORDER BY symbol, acquired_at
            """
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_dispositions(self, limit: int = 500) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM dispositions
            WHERE soft_deleted = 0
            ORDER BY disposed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_fills(self, limit: int = 500) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM trade_fills
            WHERE soft_deleted = 0
            ORDER BY executed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def list_orders(self, limit: int = 500) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM trade_orders
            WHERE soft_deleted = 0
            ORDER BY submitted_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def realized_summary(self) -> dict[str, Any]:
        cursor = await self._db.conn.execute(
            """
            SELECT
                COALESCE(SUM(realized_gain), 0) AS total_realized,
                COALESCE(SUM(CASE WHEN realized_gain > 0 THEN realized_gain ELSE 0 END), 0) AS gains,
                COALESCE(SUM(CASE WHEN realized_gain < 0 THEN realized_gain ELSE 0 END), 0) AS losses,
                COALESCE(SUM(wash_disallowed_loss), 0) AS wash_disallowed,
                COUNT(*) AS disposition_count
            FROM dispositions
            WHERE soft_deleted = 0
            """
        )
        row = await cursor.fetchone()
        year = datetime.now(timezone.utc).year
        ytd = await self._db.conn.execute(
            """
            SELECT COALESCE(SUM(realized_gain), 0) AS ytd
            FROM dispositions
            WHERE soft_deleted = 0 AND disposed_at >= ?
            """,
            (f"{year}-01-01",),
        )
        ytd_row = await ytd.fetchone()
        return {
            "total_realized": round(float(row["total_realized"]), 2),
            "gains": round(float(row["gains"]), 2),
            "losses": round(float(row["losses"]), 2),
            "wash_disallowed": round(float(row["wash_disallowed"]), 2),
            "disposition_count": int(row["disposition_count"]),
            "ytd_realized": round(float(ytd_row["ytd"]), 2),
            "note": "Tax is on profit (realized gain), not sale proceeds. Not tax advice.",
        }

    async def request_purge(
        self,
        entity_type: str,
        entity_id: str,
        reason: str,
        confirmation_phrase: str,
    ) -> dict[str, Any]:
        """Soft-flag only. Never hard-deletes ledger rows."""
        expected = f"PURGE {entity_type.upper()} {entity_id}"
        if confirmation_phrase.strip() != expected:
            raise ValueError(
                f"Confirmation must exactly match: {expected}"
            )
        if len(reason.strip()) < 20:
            raise ValueError("Reason must be at least 20 characters")

        req_id = _uid("purge")
        now = _now()
        await self._db.conn.execute(
            """
            INSERT INTO deletion_requests (
                id, entity_type, entity_id, reason, confirmation_phrase,
                status, requested_at, notes
            ) VALUES (?, ?, ?, ?, ?, 'soft_flagged', ?, ?)
            """,
            (
                req_id,
                entity_type,
                entity_id,
                reason.strip(),
                confirmation_phrase.strip(),
                now,
                "Soft-flag only; historical rows retained for tax/audit.",
            ),
        )
        table_map = {
            "trade_order": "trade_orders",
            "trade_fill": "trade_fills",
            "tax_lot": "tax_lots",
            "disposition": "dispositions",
            "wash_sale_event": "wash_sale_events",
            "settlement_event": "settlement_events",
        }
        table = table_map.get(entity_type)
        if table:
            await self._db.conn.execute(
                f"UPDATE {table} SET soft_deleted = 1 WHERE id = ?",
                (entity_id,),
            )
        await self.audit(
            "purge_requested",
            entity_type,
            entity_id,
            {"request_id": req_id, "reason": reason},
            actor="user",
        )
        await self._db.conn.commit()
        return {
            "id": req_id,
            "status": "soft_flagged",
            "note": "Row soft-flagged only. Hard delete of tax/trade history is not supported.",
        }

    async def symbol_open_qty(self, symbol: str) -> float:
        cursor = await self._db.conn.execute(
            """
            SELECT COALESCE(SUM(qty_open), 0) AS q
            FROM tax_lots
            WHERE symbol = ? AND soft_deleted = 0 AND qty_open > 0
            """,
            (symbol.upper(),),
        )
        row = await cursor.fetchone()
        return float(row["q"]) if row else 0.0
