"""Local paper-trading ledger. Never sends orders to a broker."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.storage.database import Database


class PaperPositionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def open_position(
        self,
        ticker: str,
        shares: float,
        cost_basis: float,
        *,
        source_run_id: str | None = None,
        notes: str | None = None,
    ) -> dict:
        position_id = f"pp-{uuid.uuid4().hex[:10]}"
        opened_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """
            INSERT INTO paper_positions (
                id, ticker, shares, cost_basis, opened_at, status, source_run_id, notes
            ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                position_id,
                ticker.upper(),
                shares,
                cost_basis,
                opened_at,
                source_run_id,
                notes,
            ),
        )
        await self._db.conn.commit()
        row = await self.get(position_id)
        assert row is not None
        return row

    async def close_position(self, position_id: str) -> dict | None:
        closed_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """
            UPDATE paper_positions
            SET status = 'closed', closed_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (closed_at, position_id),
        )
        await self._db.conn.commit()
        return await self.get(position_id)

    async def get(self, position_id: str) -> dict | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM paper_positions WHERE id = ?",
            (position_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_positions(self, status: str | None = "open") -> list[dict]:
        if status:
            cursor = await self._db.conn.execute(
                """
                SELECT * FROM paper_positions
                WHERE status = ?
                ORDER BY opened_at DESC
                """,
                (status,),
            )
        else:
            cursor = await self._db.conn.execute(
                "SELECT * FROM paper_positions ORDER BY opened_at DESC"
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
