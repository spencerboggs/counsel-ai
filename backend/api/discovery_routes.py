"""Discovery API routes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import (
    AgentFindingOut,
    CandidateDetailResponse,
    CandidateSummary,
    DiscoveryRunCreated,
    DiscoveryRunRequest,
    DiscoveryRunResponse,
    ProgressStageOut,
    ReexamineRequest,
)
from backend.data.universe_refresh import refresh_universe
from backend.data.universe_us import universe_stats
from backend.evidence.store import EvidenceStore
from backend.research.discovery.pipeline import DiscoveryPipeline
from backend.storage.research_runs import ResearchRunStore
from backend.storage.run_events import RunEventStore

discovery_router = APIRouter(prefix="/discovery", tags=["discovery"])


def _summarize_candidates(raw: list[dict[str, Any]]) -> list[CandidateSummary]:
    out: list[CandidateSummary] = []
    for row in raw:
        out.append(
            CandidateSummary(
                ticker=row["ticker"],
                score=float(row["score"]),
                confidence=float(row.get("confidence") or 0),
                signal=str(row.get("signal") or ""),
                name=row.get("name"),
                sector=row.get("sector"),
                price=_as_float(row.get("price")),
                shares_buyable=_as_int(row.get("shares_buyable")),
                panel_score=_as_float(row.get("panel_score")),
                panel_spread=_as_float(row.get("panel_spread")),
                meets_criteria=(
                    bool(row["meets_criteria"])
                    if row.get("meets_criteria") is not None
                    else None
                ),
                miss_reason=row.get("miss_reason"),
            )
        )
    return out


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


@discovery_router.post("/runs", response_model=DiscoveryRunCreated)
async def start_discovery_run(
    body: DiscoveryRunRequest,
    request: Request,
) -> DiscoveryRunCreated:
    run_id = f"dr-{uuid.uuid4().hex[:12]}"
    params = body.model_dump()
    store = ResearchRunStore(request.app.state.db)
    await store.create(run_id, "discovery", params)

    pipeline = DiscoveryPipeline(request.app.state.db)

    async def _task() -> None:
        await pipeline.run(run_id, params)

    task = asyncio.create_task(_task())
    if not hasattr(request.app.state, "background_tasks"):
        request.app.state.background_tasks = set()
    request.app.state.background_tasks.add(task)
    task.add_done_callback(request.app.state.background_tasks.discard)
    from backend.storage.run_control import register_run_task

    register_run_task(run_id, task)

    return DiscoveryRunCreated(run_id=run_id, status="running")


def _run_response(data: dict[str, Any], events: list[dict[str, Any]]) -> DiscoveryRunResponse:
    result = data.get("result") or {}
    stages_raw = result.get("stages") or []
    stages = [ProgressStageOut(**s) for s in stages_raw]
    candidates = _summarize_candidates(result.get("candidates") or [])
    return DiscoveryRunResponse(
        id=data["id"],
        status=data["status"],
        input=data.get("input") or {},
        stages=stages,
        candidates=candidates,
        error=result.get("error"),
        created_at=data.get("created_at"),
        completed_at=data.get("completed_at"),
        researcher_available=result.get("researcher_available"),
        stats=result.get("stats") or {},
        events=events,
    )


@discovery_router.get("/universe")
async def get_universe_info() -> dict:
    return universe_stats()


@discovery_router.post("/universe/refresh")
async def refresh_stock_universe() -> dict:
    """Pull the free Nasdaq/NYSE symbol directories and rebuild the local universe."""
    try:
        result = await refresh_universe()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not refresh free symbol lists: {exc}",
        ) from exc
    return {**result, **universe_stats()}


@discovery_router.get("/latest", response_model=DiscoveryRunResponse | None)
async def latest_discovery_run(
    request: Request,
    module: str = "discovery",
) -> DiscoveryRunResponse | None:
    store = ResearchRunStore(request.app.state.db)
    data = await store.latest(module)
    if data is None:
        return None
    # After a server restart, in-memory tasks are gone but SQLite may still say
    # "running". Treat those as stopped so reload does not resurrect a zombie.
    from backend.storage.run_control import is_run_task_alive, request_cancel

    if data["status"] == "running" and not is_run_task_alive(data["id"]):
        request_cancel(data["id"])
        data = await store.mark_cancelled(data["id"]) or data
    events = await RunEventStore(request.app.state.db).list_for_run(data["id"])
    return _run_response(data, events)


@discovery_router.post("/reexamine", response_model=DiscoveryRunCreated)
async def start_reexamine(body: ReexamineRequest, request: Request) -> DiscoveryRunCreated:
    run_id = f"rx-{uuid.uuid4().hex[:12]}"
    params = body.model_dump()
    store = ResearchRunStore(request.app.state.db)
    await store.create(run_id, "reexamine", params)
    pipeline = DiscoveryPipeline(request.app.state.db)

    async def _task() -> None:
        await pipeline.reexamine(run_id, body.ticker, params)

    task = asyncio.create_task(_task())
    if not hasattr(request.app.state, "background_tasks"):
        request.app.state.background_tasks = set()
    request.app.state.background_tasks.add(task)
    task.add_done_callback(request.app.state.background_tasks.discard)
    from backend.storage.run_control import register_run_task

    register_run_task(run_id, task)
    return DiscoveryRunCreated(run_id=run_id, status="running")


@discovery_router.post("/runs/{run_id}/cancel")
async def cancel_discovery_run(run_id: str, request: Request) -> dict:
    """Stop a run: flag in memory + mark cancelled in SQLite immediately."""
    from backend.storage.run_control import request_cancel

    # Synchronous flag first so the pipeline can notice without waiting on DB.
    task_known = request_cancel(run_id)

    store = ResearchRunStore(request.app.state.db)
    data = await store.get(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if data["status"] == "running":
        data = await store.mark_cancelled(run_id) or data
        try:
            await RunEventStore(request.app.state.db).add(
                run_id,
                "Stopped by user.",
                stage="screening",
                level="warning",
            )
        except Exception:
            pass

    return {
        "run_id": run_id,
        "status": data["status"] if data else "cancelled",
        "cancel_requested": True,
        "task_known": task_known,
    }


@discovery_router.get("/runs/{run_id}", response_model=DiscoveryRunResponse)
async def get_discovery_run(run_id: str, request: Request) -> DiscoveryRunResponse:
    store = ResearchRunStore(request.app.state.db)
    data = await store.get(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    events = await RunEventStore(request.app.state.db).list_for_run(run_id)
    return _run_response(data, events)


@discovery_router.get(
    "/runs/{run_id}/candidates/{ticker}",
    response_model=CandidateDetailResponse,
)
async def get_candidate_detail(
    run_id: str,
    ticker: str,
    request: Request,
) -> CandidateDetailResponse:
    store = ResearchRunStore(request.app.state.db)
    data = await store.get(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    result = data.get("result") or {}
    candidates = list(result.get("candidates") or []) + list(result.get("all_scored") or [])
    match = next(
        (c for c in candidates if str(c.get("ticker", "")).upper() == ticker.upper()),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Candidate not found in run")

    evidence_store = EvidenceStore(request.app.state.db)
    evidence_items = await evidence_store.list_for_run(run_id, ticker.upper())
    return CandidateDetailResponse(
        ticker=match["ticker"],
        score=float(match["score"]),
        confidence=float(match.get("confidence") or 0),
        signal=str(match.get("signal") or ""),
        calculation=str(match.get("calculation") or ""),
        components=list(match.get("components") or []),
        evidence=[e.model_dump() for e in evidence_items],
        researcher_summary=match.get("researcher_summary"),
        researcher=match.get("researcher"),
        name=match.get("name"),
        sector=match.get("sector"),
        evidence_ids=list(match.get("evidence_ids") or []),
        panel_score=_as_float(match.get("panel_score")),
        panel_spread=_as_float(match.get("panel_spread")),
        agents=[
            AgentFindingOut(
                role=agent.get("role"),
                model=agent.get("model"),
                score=_as_float(agent.get("score")),
                confidence=_as_float(agent.get("confidence")),
                summary=agent.get("summary"),
                risks=list(agent.get("risks") or []),
                evidence_ids=list(agent.get("evidence_ids") or []),
                dimension_scores={
                    str(k): float(v)
                    for k, v in (agent.get("dimension_scores") or {}).items()
                    if isinstance(v, (int, float))
                },
            )
            for agent in (match.get("agents") or [])
        ],
    )
