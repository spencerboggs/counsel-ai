"""Persist Autopilot decisions and summarize outcomes for crew context.

Outcomes are backfilled from dispositions after sells. Digests are stored
in SQLite and passed into later crew prompts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.storage.database import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionJournal:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def backfill_outcomes(self, limit: int = 80) -> int:
        """Attach realized P&L to executed buy decisions when a later sell exists."""
        cursor = await self._db.conn.execute(
            """
            SELECT id, symbol, action, status, execution_json, created_at, notes
            FROM autopilot_decisions
            WHERE action = 'buy' AND status = 'executed'
              AND symbol IS NOT NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in await cursor.fetchall()]
        updated = 0
        for row in rows:
            exec_raw = row.get("execution_json")
            try:
                execution = json.loads(exec_raw) if exec_raw else {}
            except json.JSONDecodeError:
                execution = {}
            if execution.get("outcome_pnl") is not None:
                continue
            symbol = str(row["symbol"]).upper()
            created = row["created_at"]
            disp = await self._db.conn.execute(
                """
                SELECT COALESCE(SUM(realized_gain), 0) AS pnl, COUNT(*) AS n
                FROM dispositions
                WHERE soft_deleted = 0 AND UPPER(symbol) = ?
                  AND disposed_at >= ?
                """,
                (symbol, created),
            )
            drow = await disp.fetchone()
            if not drow or int(drow["n"] or 0) == 0:
                continue
            execution["outcome_pnl"] = round(float(drow["pnl"]), 2)
            execution["outcome_at"] = _now()
            execution["outcome_source"] = "dispositions_after_buy"
            await self._db.conn.execute(
                "UPDATE autopilot_decisions SET execution_json = ? WHERE id = ?",
                (json.dumps(execution), row["id"]),
            )
            updated += 1
        if updated:
            await self._db.conn.commit()
        return updated

    async def digest(self, limit: int = 40) -> dict[str, Any]:
        await self.backfill_outcomes(limit=limit)
        cursor = await self._db.conn.execute(
            """
            SELECT * FROM autopilot_decisions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        items = []
        wins = losses = flat = executed = rejected = 0
        lessons: list[str] = []
        for row in await cursor.fetchall():
            item = dict(row)
            execution = None
            if item.get("execution_json"):
                try:
                    execution = json.loads(item["execution_json"])
                except json.JSONDecodeError:
                    execution = None
            status = str(item.get("status") or "")
            action = str(item.get("action") or "")
            if status == "executed":
                executed += 1
            if status in {"rejected", "blocked", "halted"}:
                rejected += 1
            pnl = None
            if isinstance(execution, dict) and execution.get("outcome_pnl") is not None:
                pnl = float(execution["outcome_pnl"])
            elif isinstance(execution, dict) and execution.get("realized_gain") is not None:
                pnl = float(execution["realized_gain"])
            if pnl is not None:
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
                else:
                    flat += 1
            summary = {
                "created_at": item.get("created_at"),
                "symbol": item.get("symbol"),
                "action": action,
                "status": status,
                "notes": (item.get("notes") or "")[:180],
                "outcome_pnl": pnl,
            }
            items.append(summary)

        total_scored = wins + losses + flat
        win_rate = (wins / total_scored) if total_scored else None
        if win_rate is not None:
            lessons.append(
                f"Paper journal win rate on scored outcomes: {win_rate:.0%} "
                f"({wins}W/{losses}L/{flat} flat of {total_scored})."
            )
        if rejected > executed and executed + rejected > 5:
            lessons.append(
                "Many proposals rejected/blocked - prefer higher-conviction, "
                "allowlisted, wash-safe names within Kelly/6% size."
            )
        # Recent losers
        for it in items:
            if it.get("outcome_pnl") is not None and it["outcome_pnl"] < 0:
                lessons.append(
                    f"Loss lesson: {it['symbol']} {it['action']} "
                    f"pnl={it['outcome_pnl']} - {it['notes'][:100]}"
                )
                if len(lessons) >= 8:
                    break
        for it in items:
            if it.get("outcome_pnl") is not None and it["outcome_pnl"] > 0:
                lessons.append(
                    f"Win pattern: {it['symbol']} {it['action']} "
                    f"pnl={it['outcome_pnl']} - {it['notes'][:100]}"
                )
                if len(lessons) >= 12:
                    break

        return {
            "count": len(items),
            "executed": executed,
            "rejected_or_blocked": rejected,
            "wins": wins,
            "losses": losses,
            "flat": flat,
            "win_rate": round(win_rate, 3) if win_rate is not None else None,
            "lessons": lessons[:12],
            "recent": items[:15],
            "note": (
                "Local paper journal only - free. Outcomes backfilled from tax "
                "dispositions after sells. Not a guarantee of future edge."
            ),
        }
