"""Persisted autopilot singleton state + decision log."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.storage.database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class AutopilotStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def ensure_row(self) -> None:
        cursor = await self._db.conn.execute(
            "SELECT id FROM autopilot_state WHERE id = 'singleton'"
        )
        if await cursor.fetchone() is None:
            await self._db.conn.execute(
                """
                INSERT INTO autopilot_state (id, running, updated_at)
                VALUES ('singleton', 0, ?)
                """,
                (_now(),),
            )
            await self._db.conn.commit()

    async def get(self) -> dict[str, Any]:
        await self.ensure_row()
        cursor = await self._db.conn.execute(
            "SELECT * FROM autopilot_state WHERE id = 'singleton'"
        )
        row = await cursor.fetchone()
        data = dict(row) if row else {}
        cfg = {}
        wake = {}
        if data.get("config_json"):
            try:
                cfg = json.loads(data["config_json"])
            except json.JSONDecodeError:
                cfg = {}
        if data.get("last_wake_json"):
            try:
                wake = json.loads(data["last_wake_json"])
            except json.JSONDecodeError:
                wake = {}
        data["config"] = cfg
        data["last_wake"] = wake
        data["running"] = bool(data.get("running"))
        return data

    async def set_running(
        self,
        running: bool,
        *,
        config: dict[str, Any] | None = None,
        wake: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure_row()
        now = _now()
        current = await self.get()
        asleep_since = current.get("asleep_since")
        if running:
            # Capture how long we were stopped before this start.
            if not current.get("running") and current.get("stopped_at"):
                asleep_since = current["stopped_at"]
            started_at = now
            stopped_at = None
        else:
            started_at = current.get("started_at")
            stopped_at = now
            asleep_since = now
        await self._db.conn.execute(
            """
            UPDATE autopilot_state SET
                running = ?,
                started_at = COALESCE(?, started_at),
                stopped_at = ?,
                asleep_since = ?,
                config_json = COALESCE(?, config_json),
                last_wake_json = COALESCE(?, last_wake_json),
                last_error = ?,
                updated_at = ?
            WHERE id = 'singleton'
            """,
            (
                1 if running else 0,
                started_at if running else None,
                stopped_at,
                asleep_since,
                json.dumps(config) if config is not None else None,
                json.dumps(wake) if wake is not None else None,
                error,
                now,
            ),
        )
        await self._db.conn.commit()
        return await self.get()

    async def mark_cycle(
        self,
        *,
        error: str | None = None,
    ) -> None:
        await self.ensure_row()
        await self._db.conn.execute(
            """
            UPDATE autopilot_state SET
                last_cycle_at = ?,
                cycle_count = cycle_count + 1,
                last_error = ?,
                asleep_since = NULL,
                updated_at = ?
            WHERE id = 'singleton'
            """,
            (_now(), error, _now()),
        )
        await self._db.conn.commit()

    async def record_decision(
        self,
        *,
        cycle_id: str,
        action: str,
        status: str,
        symbol: str | None = None,
        proposal: dict[str, Any] | None = None,
        votes: list[dict[str, Any]] | None = None,
        consensus: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> str:
        decision_id = _uid("apd")
        await self._db.conn.execute(
            """
            INSERT INTO autopilot_decisions (
                id, cycle_id, created_at, symbol, action, status,
                proposal_json, votes_json, consensus_json, execution_json, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                cycle_id,
                _now(),
                symbol,
                action,
                status,
                json.dumps(proposal) if proposal else None,
                json.dumps(votes) if votes else None,
                json.dumps(consensus) if consensus else None,
                json.dumps(execution) if execution else None,
                notes,
            ),
        )
        await self._db.conn.commit()
        return decision_id

    async def list_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM autopilot_decisions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        out = []
        for row in await cursor.fetchall():
            item = dict(row)
            for key in ("proposal_json", "votes_json", "consensus_json", "execution_json"):
                raw = item.pop(key, None)
                name = key.replace("_json", "")
                if raw:
                    try:
                        item[name] = json.loads(raw)
                    except json.JSONDecodeError:
                        item[name] = None
                else:
                    item[name] = None
            out.append(item)
        return out
