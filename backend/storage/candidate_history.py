"""Persist discovered candidates across runs for exclusion / export."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from backend.storage.database import Database

VALID_LANES = frozenset({"invest", "daytrade", "swing"})


def normalize_lane(lane: str | None) -> str:
    value = (lane or "invest").strip().lower()
    return value if value in VALID_LANES else "invest"


class CandidateHistoryStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_many(
        self,
        research_run_id: str,
        candidates: list[dict[str, Any]],
        *,
        output_limit: int | None = None,
        lane: str = "invest",
    ) -> None:
        """Upsert scored names - one row per (lane, ticker), latest wins."""
        if not candidates:
            return
        lane_key = normalize_lane(lane)
        seen_at = datetime.now(timezone.utc).isoformat()
        for index, candidate in enumerate(candidates):
            ticker = str(candidate["ticker"]).upper()
            rank = index + 1
            in_output = 1 if output_limit is None or rank <= output_limit else 0
            # Drop any prior rows for this lane+ticker (including older run ids).
            await self._db.conn.execute(
                "DELETE FROM candidate_sightings WHERE lane = ? AND ticker = ?",
                (lane_key, ticker),
            )
            metrics = candidate.get("metrics")
            metrics_json = (
                json.dumps(metrics)
                if isinstance(metrics, dict)
                else (metrics if isinstance(metrics, str) else None)
            )
            await self._db.conn.execute(
                """
                INSERT INTO candidate_sightings (
                    ticker, research_run_id, score, signal, price,
                    shares_buyable, panel_score, seen_at, name, sector,
                    confidence, rank, in_output, lane, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker,
                    research_run_id,
                    candidate.get("score"),
                    candidate.get("signal"),
                    candidate.get("price"),
                    candidate.get("shares_buyable"),
                    candidate.get("panel_score"),
                    seen_at,
                    candidate.get("name"),
                    candidate.get("sector"),
                    candidate.get("confidence"),
                    rank,
                    in_output,
                    lane_key,
                    metrics_json,
                ),
            )
        await self._db.conn.commit()

    async def known_tickers(self, lane: str | None = None) -> set[str]:
        lane_key = normalize_lane(lane) if lane is not None else None
        if lane_key is None:
            cursor = await self._db.conn.execute(
                "SELECT DISTINCT ticker FROM candidate_sightings"
            )
        else:
            cursor = await self._db.conn.execute(
                "SELECT DISTINCT ticker FROM candidate_sightings WHERE lane = ?",
                (lane_key,),
            )
        rows = await cursor.fetchall()
        return {str(row["ticker"]).upper() for row in rows}

    async def list_all(
        self,
        limit: int = 500,
        *,
        lane: str | None = None,
    ) -> list[dict[str, Any]]:
        lane_key = normalize_lane(lane) if lane is not None else None
        if lane_key is None:
            cursor = await self._db.conn.execute(
                """
                SELECT ticker, research_run_id, score, signal, price,
                       shares_buyable, panel_score, seen_at, name, sector,
                       confidence, rank, in_output, lane, metrics_json
                FROM candidate_sightings
                ORDER BY seen_at DESC, rank ASC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            cursor = await self._db.conn.execute(
                """
                SELECT ticker, research_run_id, score, signal, price,
                       shares_buyable, panel_score, seen_at, name, sector,
                       confidence, rank, in_output, lane, metrics_json
                FROM candidate_sightings
                WHERE lane = ?
                ORDER BY seen_at DESC, rank ASC
                LIMIT ?
                """,
                (lane_key, limit),
            )
        return [dict(row) for row in await cursor.fetchall()]

    async def latest_for_ticker(self, ticker: str) -> dict[str, Any] | None:
        """Best sighting for a ticker (prefer highest score across lanes)."""
        symbol = ticker.upper().strip()
        cursor = await self._db.conn.execute(
            """
            SELECT ticker, research_run_id, score, signal, price,
                   shares_buyable, panel_score, seen_at, name, sector,
                   confidence, rank, in_output, lane, metrics_json
            FROM candidate_sightings
            WHERE UPPER(ticker) = ?
            ORDER BY COALESCE(score, -1) DESC, seen_at DESC
            LIMIT 1
            """,
            (symbol,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def peer_metrics_for_lane(
        self,
        lane: str,
        *,
        exclude_ticker: str | None = None,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        """Load stored metrics for optional peer blend on reexamine."""
        lane_key = normalize_lane(lane)
        cursor = await self._db.conn.execute(
            """
            SELECT ticker, metrics_json
            FROM candidate_sightings
            WHERE lane = ?
              AND metrics_json IS NOT NULL
              AND (? IS NULL OR UPPER(ticker) != UPPER(?))
            ORDER BY seen_at DESC
            LIMIT ?
            """,
            (lane_key, exclude_ticker, exclude_ticker, limit),
        )
        peers: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            raw = row["metrics_json"]
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                peers.append(parsed)
        return peers

    async def export_json(self, *, lane: str | None = None) -> str:
        rows = await self.list_all(limit=5000, lane=lane)
        return json.dumps(rows, indent=2)

    async def export_csv(self, *, lane: str | None = None) -> str:
        rows = await self.list_all(limit=5000, lane=lane)
        buffer = io.StringIO()
        fieldnames = [
            "ticker",
            "research_run_id",
            "lane",
            "score",
            "signal",
            "price",
            "shares_buyable",
            "panel_score",
            "seen_at",
            "name",
            "sector",
            "confidence",
            "rank",
            "in_output",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()

    async def clear(self, *, lane: str | None = None) -> int:
        if lane is None:
            cursor = await self._db.conn.execute(
                "SELECT COUNT(*) AS n FROM candidate_sightings"
            )
            row = await cursor.fetchone()
            count = int(row["n"] if row else 0)
            await self._db.conn.execute("DELETE FROM candidate_sightings")
        else:
            lane_key = normalize_lane(lane)
            cursor = await self._db.conn.execute(
                "SELECT COUNT(*) AS n FROM candidate_sightings WHERE lane = ?",
                (lane_key,),
            )
            row = await cursor.fetchone()
            count = int(row["n"] if row else 0)
            await self._db.conn.execute(
                "DELETE FROM candidate_sightings WHERE lane = ?",
                (lane_key,),
            )
        await self._db.conn.commit()
        return count
