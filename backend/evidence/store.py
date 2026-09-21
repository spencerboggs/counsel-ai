"""Persist and load evidence items."""

from __future__ import annotations

import json
from typing import Any

from backend.evidence.models import EvidenceItem
from backend.storage.database import Database


class EvidenceStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_many(self, items: list[EvidenceItem]) -> None:
        if not items:
            return
        await self._db.conn.executemany(
            """
            INSERT OR REPLACE INTO evidence (
                id, ticker, claim, source_name, source_url, source_type,
                published_at, retrieved_at, supporting_text, data_points_json,
                reliability, freshness, directness, corroboration,
                research_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.id,
                    item.ticker,
                    item.claim,
                    item.source_name,
                    item.source_url,
                    item.source_type,
                    item.published_at,
                    item.retrieved_at,
                    item.supporting_text,
                    json.dumps(item.data_points),
                    item.reliability,
                    item.freshness,
                    item.directness,
                    item.corroboration,
                    item.research_run_id,
                )
                for item in items
            ],
        )
        await self._db.conn.commit()

    async def list_for_run(
        self,
        research_run_id: str,
        ticker: str | None = None,
    ) -> list[EvidenceItem]:
        if ticker:
            cursor = await self._db.conn.execute(
                """
                SELECT * FROM evidence
                WHERE research_run_id = ? AND ticker = ?
                ORDER BY id
                """,
                (research_run_id, ticker.upper()),
            )
        else:
            cursor = await self._db.conn.execute(
                """
                SELECT * FROM evidence
                WHERE research_run_id = ?
                ORDER BY ticker, id
                """,
                (research_run_id,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_item(dict(row)) for row in rows]

    def _row_to_item(self, row: dict[str, Any]) -> EvidenceItem:
        data_points: dict[str, Any] = {}
        raw = row.get("data_points_json")
        if raw:
            try:
                data_points = json.loads(raw)
            except json.JSONDecodeError:
                data_points = {}
        return EvidenceItem(
            id=row["id"],
            ticker=row["ticker"],
            claim=row["claim"],
            source_name=row["source_name"],
            source_url=row.get("source_url"),
            source_type=row["source_type"],
            published_at=row.get("published_at"),
            retrieved_at=row["retrieved_at"],
            supporting_text=row.get("supporting_text"),
            data_points=data_points,
            reliability=row.get("reliability") or 0.7,
            freshness=row.get("freshness") or 0.7,
            directness=row.get("directness") or 0.7,
            corroboration=row.get("corroboration") or 0.5,
            research_run_id=row.get("research_run_id"),
        )
