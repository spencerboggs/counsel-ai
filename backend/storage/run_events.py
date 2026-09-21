"""Append-only run event log for operator visibility."""

from __future__ import annotations

from backend.storage.database import Database


class RunEventStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        research_run_id: str,
        message: str,
        *,
        stage: str | None = None,
        level: str = "info",
    ) -> None:
        await self._db.conn.execute(
            """
            INSERT INTO run_events (research_run_id, level, stage, message)
            VALUES (?, ?, ?, ?)
            """,
            (research_run_id, level, stage, message),
        )
        await self._db.conn.commit()

    async def list_for_run(self, research_run_id: str, limit: int = 100) -> list[dict]:
        cursor = await self._db.conn.execute(
            """
            SELECT id, research_run_id, level, stage, message, created_at
            FROM run_events
            WHERE research_run_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (research_run_id, limit),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        rows.reverse()
        return rows
