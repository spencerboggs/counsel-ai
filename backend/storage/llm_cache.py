"""Cache model outputs so identical research is not paid for twice."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.storage.database import Database


def _stable(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {str(k): _stable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def fingerprint(kind: str, model: str, ticker: str, payload: dict[str, Any]) -> str:
    blob = json.dumps(
        {
            "kind": kind,
            "model": model,
            "ticker": ticker.upper(),
            "payload": _stable(payload),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


class LlmCache:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, cache_key: str) -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            "SELECT payload_json FROM llm_cache WHERE cache_key = ?",
            (cache_key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            parsed = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    async def put(
        self,
        cache_key: str,
        payload: dict[str, Any],
        *,
        kind: str,
        ticker: str,
        model: str,
    ) -> None:
        await self._db.conn.execute(
            """
            INSERT OR REPLACE INTO llm_cache (
                cache_key, kind, ticker, model, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                cache_key,
                kind,
                ticker.upper(),
                model,
                json.dumps(payload),
            ),
        )
        await self._db.conn.commit()
