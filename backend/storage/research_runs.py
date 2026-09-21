"""Research run persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.storage.database import Database


class ResearchRunStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        run_id: str,
        module: str,
        input_payload: dict[str, Any],
    ) -> None:
        await self._db.conn.execute(
            """
            INSERT INTO research_runs (id, module, status, input_json, result_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                module,
                "running",
                json.dumps(input_payload),
                json.dumps(
                    {
                        "stages": [],
                        "candidates": [],
                        "error": None,
                    }
                ),
            ),
        )
        await self._db.conn.commit()

    async def get(self, run_id: str) -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM research_runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        data = dict(row)
        input_json = {}
        result_json: dict[str, Any] = {}
        try:
            input_json = json.loads(data.get("input_json") or "{}")
        except json.JSONDecodeError:
            input_json = {}
        try:
            result_json = json.loads(data.get("result_json") or "{}")
        except json.JSONDecodeError:
            result_json = {}
        return {
            "id": data["id"],
            "module": data["module"],
            "status": data["status"],
            "input": input_json,
            "result": result_json,
            "created_at": data.get("created_at"),
            "completed_at": data.get("completed_at"),
        }

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        complete: bool = False,
    ) -> None:
        completed_at = (
            datetime.now(timezone.utc).isoformat() if complete else None
        )
        # Never resurrect a run the user already stopped.
        cursor = await self._db.conn.execute(
            "SELECT status FROM research_runs WHERE id = ?",
            (run_id,),
        )
        row = await cursor.fetchone()
        existing = str(row["status"]) if row else None
        if existing == "cancelled" and status not in ("cancelled",):
            status = "cancelled"

        if result is not None:
            await self._db.conn.execute(
                """
                UPDATE research_runs
                SET status = ?, result_json = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status, json.dumps(result), completed_at, run_id),
            )
        else:
            await self._db.conn.execute(
                """
                UPDATE research_runs
                SET status = ?, completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (status, completed_at, run_id),
            )
        await self._db.conn.commit()

    async def mark_cancelled(self, run_id: str) -> dict[str, Any] | None:
        """Flip status to cancelled immediately (used by Stop)."""
        current = await self.get(run_id)
        if current is None:
            return None
        if current["status"] != "running":
            return current
        result = dict(current.get("result") or {})
        stats = dict(result.get("stats") or {})
        stats["cancelled"] = True
        result["stats"] = stats
        stages = list(result.get("stages") or [])
        for stage in stages:
            if stage.get("status") == "active":
                stage["status"] = "complete"
                stage["detail"] = "Stopped"
        result["stages"] = stages
        await self.update_status(
            run_id,
            "cancelled",
            result=result,
            complete=True,
        )
        return await self.get(run_id)

    async def patch_result(self, run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = await self.get(run_id)
        if current is None:
            raise KeyError(run_id)
        result = dict(current.get("result") or {})
        result.update(patch)
        await self._db.conn.execute(
            "UPDATE research_runs SET result_json = ? WHERE id = ?",
            (json.dumps(result), run_id),
        )
        await self._db.conn.commit()
        return result

    async def latest(self, module: str = "discovery") -> dict[str, Any] | None:
        cursor = await self._db.conn.execute(
            """
            SELECT id FROM research_runs
            WHERE module = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (module,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return await self.get(str(row["id"]))
