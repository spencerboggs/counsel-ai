"""Usage tracking for LLM providers."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.storage.database import Database


class UsageStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_usage(
        self,
        model_id: str,
        provider: str,
        model_name: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        requests: int = 1,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """
            INSERT INTO models_usage (
                model_id, provider, model_name, request_count,
                prompt_tokens, completion_tokens, last_used_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
                request_count = request_count + excluded.request_count,
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens,
                last_used_at = excluded.last_used_at,
                updated_at = excluded.updated_at,
                provider = excluded.provider,
                model_name = excluded.model_name
            """,
            (
                model_id,
                provider,
                model_name,
                requests,
                prompt_tokens,
                completion_tokens,
                now,
                now,
            ),
        )
        await self._db.conn.commit()

    async def list_usage(self) -> list[dict]:
        cursor = await self._db.conn.execute(
            """
            SELECT model_id, provider, model_name, request_count,
                   prompt_tokens, completion_tokens, last_used_at, updated_at
            FROM models_usage
            ORDER BY updated_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_usage(self, model_id: str) -> dict | None:
        cursor = await self._db.conn.execute(
            """
            SELECT model_id, provider, model_name, request_count,
                   prompt_tokens, completion_tokens, last_used_at, updated_at
            FROM models_usage
            WHERE model_id = ?
            """,
            (model_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
