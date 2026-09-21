"""Emergency trading disable. Blocks new orders; does not liquidate."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.storage.database import Database

KILL_KEY = "trading_disabled"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KillSwitch:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def is_disabled(self) -> bool:
        cursor = await self._db.conn.execute(
            "SELECT status FROM compliance_flags WHERE key = ?",
            (KILL_KEY,),
        )
        row = await cursor.fetchone()
        if row is None:
            return False
        return str(row["status"]).lower() in {"1", "true", "disabled", "on"}

    async def status(self) -> dict[str, Any]:
        cursor = await self._db.conn.execute(
            "SELECT status, updated_at, notes FROM compliance_flags WHERE key = ?",
            (KILL_KEY,),
        )
        row = await cursor.fetchone()
        disabled = False
        notes = None
        updated_at = None
        if row:
            disabled = str(row["status"]).lower() in {"1", "true", "disabled", "on"}
            notes = row["notes"]
            updated_at = row["updated_at"]
        return {
            "trading_disabled": disabled,
            "updated_at": updated_at,
            "notes": notes,
            "effect": (
                "NEW orders blocked. Open positions are not auto-liquidated. "
                "Autopilot will not execute trades while disabled."
            ),
        }

    async def set_disabled(self, disabled: bool, *, notes: str | None = None) -> dict[str, Any]:
        status = "disabled" if disabled else "enabled"
        await self._db.conn.execute(
            """
            INSERT INTO compliance_flags (key, status, updated_at, notes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                notes = excluded.notes
            """,
            (KILL_KEY, status, _now(), notes),
        )
        await self._db.conn.commit()
        return await self.status()
