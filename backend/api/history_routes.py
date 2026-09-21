"""Candidate history export / clear routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from backend.storage.candidate_history import CandidateHistoryStore, normalize_lane

history_router = APIRouter(prefix="/history", tags=["history"])


@history_router.get("/candidates")
async def list_candidate_history(
    request: Request,
    limit: int = 200,
    lane: str | None = Query(default=None, pattern="^(invest|daytrade|swing)$"),
) -> dict:
    store = CandidateHistoryStore(request.app.state.db)
    rows = await store.list_all(limit=limit, lane=lane)
    known = await store.known_tickers(lane)
    return {
        "count": len(rows),
        "items": rows,
        "known_tickers": sorted(known),
        "lane": lane,
    }


@history_router.get("/candidates.json")
async def export_candidates_json(
    request: Request,
    lane: str | None = Query(default=None, pattern="^(invest|daytrade|swing)$"),
) -> Response:
    store = CandidateHistoryStore(request.app.state.db)
    body = await store.export_json(lane=lane)
    suffix = f"-{lane}" if lane else ""
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=candidates{suffix}.json"
        },
    )


@history_router.get("/candidates.csv")
async def export_candidates_csv(
    request: Request,
    lane: str | None = Query(default=None, pattern="^(invest|daytrade|swing)$"),
) -> Response:
    store = CandidateHistoryStore(request.app.state.db)
    body = await store.export_csv(lane=lane)
    suffix = f"-{lane}" if lane else ""
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=candidates{suffix}.csv"
        },
    )


@history_router.delete("/candidates")
async def clear_candidate_history(
    request: Request,
    clear_llm_cache: bool = True,
    lane: str | None = Query(default=None, pattern="^(invest|daytrade|swing)$"),
) -> dict:
    """Wipe saved found stocks so Skip-previously-found starts clean.

    Pass lane=invest|daytrade to clear only that archive. By default also
    clears the local LLM response cache so a fresh search re-runs research.
    """
    store = CandidateHistoryStore(request.app.state.db)
    known_before = await store.known_tickers(lane)
    cleared_n = await store.clear(lane=lane)
    llm_cleared = 0
    if clear_llm_cache:
        cursor = await request.app.state.db.conn.execute(
            "SELECT COUNT(*) AS n FROM llm_cache"
        )
        row = await cursor.fetchone()
        llm_cleared = int(row["n"] if row else 0)
        await request.app.state.db.conn.execute("DELETE FROM llm_cache")
        await request.app.state.db.conn.commit()
    remaining = await store.known_tickers(lane)
    lane_label = normalize_lane(lane) if lane else "all lanes"
    return {
        "cleared": True,
        "lane": lane,
        "stocks_cleared": cleared_n if cleared_n else len(known_before),
        "llm_cache_cleared": llm_cleared,
        "stocks_remaining": len(remaining),
        "note": (
            f"Saved stocks cleared ({lane_label}). Exclude counts on an older Discover run "
            "are historical - the next Run discovery will skip 0 previously seen in that lane."
        ),
    }
