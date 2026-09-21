"""Discovery research pipeline orchestrator."""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any

from backend.config.settings import get_app_config, get_settings
from backend.counsel.panel import CounselPanel, aggregate_panel, resolve_role_model
from backend.data.universe_us import get_universe
from backend.evidence.store import EvidenceStore
from backend.providers.ollama import OllamaProvider
from backend.providers.yfinance_provider import YFinanceProvider
from backend.research.discovery.catalysts import scan_tickers_for_catalysts
from backend.research.discovery.gather_evidence import EvidenceGatherer
from backend.research.discovery.researcher import DiscoveryResearcher
from backend.research.discovery.screener import DeterministicScreener
from backend.portfolio.wash_sales import WashSaleService
from backend.scoring.discovery import DiscoveryScorer
from backend.storage.candidate_history import CandidateHistoryStore
from backend.storage.database import Database
from backend.storage.llm_cache import LlmCache
from backend.storage.research_runs import ResearchRunStore
from backend.storage.run_control import clear_cancel, is_cancelled
from backend.storage.run_events import RunEventStore
from backend.storage.usage import UsageStore


StageStatus = str  # pending | active | complete | error | skipped


def _miss_reason(
    row: dict[str, Any],
    *,
    min_score: float,
    min_panel_score: float,
) -> str | None:
    reasons: list[str] = []
    score = float(row.get("score") or 0)
    if min_score > 0 and score < min_score:
        reasons.append(f"score {score:.1f} < {min_score:.0f}")
    if min_panel_score > 0:
        panel = row.get("panel_score")
        if panel is None:
            reasons.append(f"panel missing (need >={min_panel_score:.0f})")
        elif float(panel) < min_panel_score:
            reasons.append(f"panel {float(panel):.1f} < {min_panel_score:.0f}")
    return "; ".join(reasons) if reasons else None


def _annotate_threshold(
    row: dict[str, Any],
    *,
    min_score: float,
    min_panel_score: float,
    threshold_mode: bool,
) -> dict[str, Any]:
    out = dict(row)
    if not threshold_mode:
        out["meets_criteria"] = True
        out["miss_reason"] = None
        return out
    reason = _miss_reason(out, min_score=min_score, min_panel_score=min_panel_score)
    out["meets_criteria"] = reason is None
    out["miss_reason"] = reason
    return out


def _default_stages() -> list[dict[str, Any]]:
    labels = [
        ("universe", "Universe"),
        ("screening", "Screening"),
        ("evidence", "Evidence"),
        ("research", "Research"),
        ("scoring", "Scoring"),
        ("counsel", "Counsel"),
    ]
    return [
        {"id": sid, "label": label, "status": "pending", "detail": None}
        for sid, label in labels
    ]


class DiscoveryPipeline:
    def __init__(
        self,
        db: Database,
        *,
        market: YFinanceProvider | None = None,
        ollama: OllamaProvider | None = None,
    ) -> None:
        self.db = db
        self.runs = ResearchRunStore(db)
        self.evidence = EvidenceStore(db)
        self.usage = UsageStore(db)
        self.history = CandidateHistoryStore(db)
        self.cache = LlmCache(db)
        self.events = RunEventStore(db)
        self.market = market or YFinanceProvider()
        settings = get_settings()
        config = get_app_config()
        base = config.providers.ollama.base_url or settings.ollama_base_url
        self.ollama = ollama or OllamaProvider(base_url=base)

    async def _set_stage(
        self,
        run_id: str,
        stages: list[dict[str, Any]],
        stage_id: str,
        status: StageStatus,
        detail: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
        log_event: bool = True,
    ) -> None:
        for stage in stages:
            if stage["id"] == stage_id:
                stage["status"] = status
                if detail is not None:
                    stage["detail"] = detail
            elif status == "active" and stage["status"] == "active":
                stage["status"] = "complete"
        patch: dict[str, Any] = {"stages": stages}
        if extra:
            patch.update(extra)
        await self.runs.patch_result(run_id, patch)
        if detail and log_event:
            await self.events.add(
                run_id,
                detail,
                stage=stage_id,
                level="info" if status != "error" else "error",
            )

    async def _finalize_cancelled(
        self,
        run_id: str,
        stages: list[dict[str, Any]],
    ) -> None:
        """Persist whatever progress exists and mark the run cancelled."""
        current = await self.runs.get(run_id)
        prior = (current or {}).get("result") or {}
        saved_stages = list(prior.get("stages") or stages)
        for stage in saved_stages:
            if stage.get("status") == "active":
                stage["status"] = "complete"
                stage["detail"] = "Stopped"
        stats = dict(prior.get("stats") or {})
        stats["cancelled"] = True
        try:
            await self.events.add(
                run_id,
                "Stopped immediately by user.",
                stage="screening",
                level="warning",
            )
        except Exception:
            pass
        await self.runs.update_status(
            run_id,
            "cancelled",
            result={
                "stages": saved_stages,
                "candidates": prior.get("candidates") or [],
                "all_scored": prior.get("all_scored") or [],
                "error": None,
                "researcher_available": prior.get("researcher_available"),
                "stats": stats,
            },
            complete=True,
        )
        clear_cancel(run_id)

    async def run(self, run_id: str, params: dict[str, Any]) -> None:
        stages = _default_stages()
        clear_cancel(run_id)
        await self.runs.patch_result(run_id, {"stages": stages, "candidates": [], "error": None})

        try:
            config = get_app_config()
            screen_from = int(
                params.get("screen_from_universe")
                or config.discovery.get("screen_from_universe")
                or 100
            )
            pool_size = int(
                params.get("candidate_pool_size")
                or config.discovery.get("candidate_pool_size")
                or 25
            )
            output_count = int(
                params.get("output_count")
                or config.discovery.get("output_count")
                or 10
            )
            output_count = max(1, min(output_count, 25))
            # Batch size = how many tickers we affordability-screen before
            # researching that slice. Keep it modest so results appear early.
            pool_size = max(10, min(pool_size, 20))
            min_score = float(params.get("min_score") or 0)
            min_panel_score = float(params.get("min_panel_score") or 0)
            threshold_mode = min_score > 0 or min_panel_score > 0
            lane_raw = str(params.get("lane") or "invest").strip().lower()
            if lane_raw == "daytrade":
                lane = "daytrade"
            elif lane_raw == "swing":
                lane = "swing"
            else:
                lane = "invest"
            hold_days = int(params.get("hold_days") or 3)
            hold_days = max(1, min(7, hold_days))
            if lane == "daytrade":
                # Daytrade overrides horizon/risk inputs - same-session scalp intent.
                params = {
                    **params,
                    "lane": lane,
                    "risk_tolerance": "Aggressive",
                    "time_horizon": "Intraday",
                }
            elif lane == "swing":
                params = {
                    **params,
                    "lane": lane,
                    "hold_days": hold_days,
                    "risk_tolerance": params.get("risk_tolerance") or "Aggressive",
                    "time_horizon": f"{hold_days}-day swing",
                }
            else:
                params = {**params, "lane": lane}

            investable_amount = float(
                params.get("investable_amount")
                if params.get("investable_amount") is not None
                else config.discovery.get("investable_amount", 100)
            )
            min_whole_shares = int(
                params.get("min_whole_shares")
                if params.get("min_whole_shares") is not None
                else config.discovery.get("min_whole_shares", 5)
            )
            max_market_cap = float(config.discovery.get("max_market_cap", 40_000_000_000))
            min_price = float(config.discovery.get("min_price", 1.0))
            # Daytrade / swing need liquidity; invest is lighter.
            if lane == "daytrade":
                min_avg_volume = float(
                    config.discovery.get("daytrade_min_avg_volume", 750_000)
                )
            elif lane == "swing":
                min_avg_volume = float(
                    config.discovery.get("swing_min_avg_volume", 300_000)
                )
            else:
                min_avg_volume = float(config.discovery.get("min_avg_volume", 150_000))

            # Universe is shuffled; we walk it in batches until we have enough
            # keepers (or the user stops). Threshold mode may need a larger
            # list to find enough names that clear floors.
            await self._set_stage(run_id, stages, "universe", "active")
            universe_limit = None if threshold_mode else screen_from
            tickers = get_universe(
                limit=universe_limit,
                sector=params.get("sector") if params.get("sector") not in (None, "Any") else None,
                shuffle_seed=run_id,
            )
            exclude_seen = bool(params.get("exclude_seen", True))
            skipped = 0
            universe_before_exclude = len(tickers)
            if exclude_seen:
                known = await self.history.known_tickers(lane)
                before = len(tickers)
                tickers = [t for t in tickers if t not in known]
                skipped = before - len(tickers)
            if not tickers:
                raise RuntimeError(
                    "No unseen tickers left in the universe. "
                    "Clear saved stocks or uncheck Skip previously found tickers."
                )
            await self._set_stage(
                run_id,
                stages,
                "universe",
                "complete",
                detail=(
                    f"{len(tickers)} tickers ready of {universe_before_exclude} loaded"
                    f" | budget ${investable_amount:.0f} "
                    f"(>={min_whole_shares} shares)"
                    + (
                        f" | skipped {skipped} previously saved"
                        if skipped
                        else " | skipped 0 previously saved"
                    )
                    + (
                        f" | seek >={min_score:.0f} score / >={min_panel_score:.0f} panel "
                        f"until {output_count} matches"
                        if threshold_mode
                        else ""
                    )
                ),
            )
            lane_label = (
                "Swing"
                if lane == "swing"
                else ("Daytrade" if lane == "daytrade" else "Invest")
            )
            await self.events.add(
                run_id,
                (
                    f"{lane_label} lane | "
                    f"Universe ready: {len(tickers)} fresh tickers to try"
                    + (
                        f" (skipped {skipped} already saved in this lane)"
                        if skipped
                        else ""
                    )
                    + f". Working in batches of up to {pool_size}: screen a slice, "
                    f"analyze the affordable ones, then decide whether another batch "
                    f"is needed. Stop anytime once you like what you see."
                ),
                stage="universe",
            )
            if lane == "daytrade":
                await self.events.add(
                    run_id,
                    (
                        "Daytrade mode: risk/horizon locked to Aggressive / Intraday. "
                        "Scoring favors momentum, catalysts, liquidity, and tradable "
                        "volatility. Results save under Found -> Day trade (separate "
                        "from invest finds)."
                    ),
                    stage="universe",
                )
            if lane == "swing":
                await self.events.add(
                    run_id,
                    (
                        f"Swing mode ({hold_days}-day hold): event-first catalyst scan "
                        f"(news/events -> tickers), then affordability + scoring. "
                        f"Wash-blocked and undersized names are skipped. "
                        f"Results save under Found -> Swing."
                    ),
                    stage="universe",
                )
            if threshold_mode:
                await self.events.add(
                    run_id,
                    (
                        f"Criteria search: after each batch, keep names that clear "
                        f">={min_score:.0f}"
                        + (
                            f" score and >={min_panel_score:.0f} panel"
                            if min_panel_score > 0
                            else " score"
                        )
                        + f". Stop as soon as {output_count} matches land - "
                        f"no full-universe bake-off."
                    ),
                    stage="universe",
                )
            else:
                await self.events.add(
                    run_id,
                    (
                        f"Open search: analyze up to {output_count} names across "
                        f"batches of {pool_size}. Hit Stop when you have enough to work with."
                    ),
                    stage="universe",
                )

            screener = DeterministicScreener(
                self.market,
                investable_amount=investable_amount,
                min_whole_shares=min_whole_shares,
                min_price=min_price,
                max_market_cap=max_market_cap,
                min_avg_volume=min_avg_volume,
            )
            gatherer = EvidenceGatherer(self.market)
            # Daytrade/swing use fixed profiles; ignore invest config weights.
            score_weights = (
                None
                if lane in {"daytrade", "swing"}
                else (dict(config.discovery_score) if config.discovery_score else None)
            )
            scorer = DiscoveryScorer(
                weights=score_weights,
                decimals=int(config.scoring.get("decimals", 1)),
                profile=lane,
            )

            ollama_ok = False
            model_name = None
            if config.providers.ollama.enabled:
                ollama_ok = await self.ollama.health()
                if ollama_ok:
                    models = await self.ollama.list_models()
                    for entry in config.models:
                        if entry.enabled and entry.provider == "ollama" and "discovery" in entry.roles:
                            model_name = models[0] if entry.model == "auto" and models else (
                                entry.model if entry.model in models else (models[0] if models else None)
                            )
                            break
                    if model_name is None and models:
                        model_name = models[0]
            if min_panel_score > 0 and not ollama_ok:
                raise RuntimeError(
                    "Min panel score requires a reachable Ollama server. "
                    "Start Ollama or set Min panel to 0."
                )

            researcher = (
                DiscoveryResearcher(
                    self.ollama,
                    model_name=model_name,
                    usage_store=self.usage,
                    cache=self.cache,
                )
                if ollama_ok and model_name
                else None
            )
            role_assignments: list[tuple[str, str, str]] = []
            panel: CounselPanel | None = None
            if ollama_ok:
                installed = await self.ollama.list_models()
                for role in ("fundamental", "skeptic", "counsel"):
                    resolved = resolve_role_model(role, list(config.models), installed)
                    if resolved:
                        role_assignments.append((role, resolved[0], resolved[1]))
                if role_assignments:
                    panel = CounselPanel(
                        self.ollama, usage_store=self.usage, cache=self.cache
                    )
            if min_panel_score > 0 and panel is None:
                raise RuntimeError(
                    "Min panel score requires local counsel models. "
                    "Install an Ollama model or set Min panel to 0."
                )

            matched: list[dict[str, Any]] = []
            all_scored: list[dict[str, Any]] = []
            evidence_by_ticker: dict[str, list] = {}
            metrics_by_ticker: dict[str, dict[str, Any]] = {}
            screened_total = 0
            cursor = 0
            batch_num = 0
            batch_size = pool_size
            researcher_available = False
            panel_reviews = 0
            cancelled = False
            need_panel_filter = threshold_mode and min_panel_score > 0
            panel_weights = (
                dict(config.discovery_score) if config.discovery_score else None
            )

            if researcher is None:
                await self._set_stage(
                    run_id,
                    stages,
                    "research",
                    "skipped",
                    detail="Ollama unavailable - scoring from market evidence only",
                )
            if panel is None:
                await self._set_stage(
                    run_id,
                    stages,
                    "counsel",
                    "skipped",
                    detail="Counsel unavailable - deterministic score only",
                )

            async def publish_candidates() -> list[dict[str, Any]]:
                annotated = [
                    _annotate_threshold(
                        {k: v for k, v in row.items() if not str(k).startswith("_")},
                        min_score=min_score,
                        min_panel_score=min_panel_score,
                        threshold_mode=threshold_mode,
                    )
                    for row in all_scored
                ]
                annotated.sort(
                    key=lambda row: (
                        0 if row.get("meets_criteria") else 1,
                        -float(row.get("score") or 0),
                    )
                )
                # Keep matches + under-threshold so the UI can show progress.
                visible = annotated[: max(output_count * 4, 40)]
                await self.runs.patch_result(
                    run_id,
                    {"candidates": visible, "all_scored": annotated},
                )
                return visible

            async def run_panel_on(
                row: dict[str, Any],
                *,
                use_cache: bool = True,
                force: bool = False,
            ) -> None:
                nonlocal panel_reviews, cancelled
                if panel is None:
                    return
                if row.get("_panelled") and not force:
                    return
                ticker = row["ticker"]
                await self.events.add(
                    run_id,
                    (
                        f"Panel: reviewing {ticker} "
                        f"(score {float(row.get('score') or 0):.1f}) with "
                        f"{len(role_assignments)} roles..."
                    ),
                    stage="counsel",
                )
                await self._set_stage(
                    run_id,
                    stages,
                    "counsel",
                    "active",
                    detail=f"Panel: {ticker}",
                    log_event=False,
                )
                one_started = time.monotonic()
                findings = await panel.review(
                    ticker,
                    evidence_by_ticker.get(ticker, []),
                    metrics_by_ticker.get(ticker, {}),
                    roles=role_assignments,
                    use_cache=use_cache,
                )
                summary = aggregate_panel(findings, panel_weights)
                row["panel_score"] = summary["panel_score"]
                row["panel_spread"] = summary["panel_spread"]
                row["agents"] = summary["agents"]
                row["_panelled"] = True
                if summary["panel_score"] is not None:
                    panel_reviews += 1
                cached_roles = sum(1 for f in findings if f.get("cached"))
                role_bits = []
                for f in findings:
                    role = f.get("role") or "?"
                    conf = f.get("confidence")
                    conf_s = f"{float(conf):.2f}" if conf is not None else "-"
                    tag = "cache" if f.get("cached") else "model"
                    role_bits.append(f"{role} {conf_s} ({tag})")
                await self.events.add(
                    run_id,
                    (
                        f"Panel: {ticker} -> "
                        f"{summary['panel_score'] if summary['panel_score'] is not None else 'n/a'}/100 "
                        f"(spread {summary.get('panel_spread') or 0}; "
                        f"{cached_roles}/{len(findings)} roles cached; "
                        f"{time.monotonic() - one_started:.1f}s"
                        + (f"; {', '.join(role_bits)}" if role_bits else "")
                        + ")"
                    ),
                    stage="counsel",
                )

            async def select_best_matches(*, allow_panel: bool) -> list[dict[str, Any]]:
                """Rank by deterministic score first; floors are a filter, not a target."""
                nonlocal cancelled
                ranked = sorted(
                    all_scored,
                    key=lambda row: float(row.get("score") or 0),
                    reverse=True,
                )
                selected: list[dict[str, Any]] = []
                for row in ranked:
                    if is_cancelled(run_id):
                        cancelled = True
                        break
                    if len(selected) >= output_count:
                        break
                    score_val = float(row.get("score") or 0)
                    if min_score > 0 and score_val < min_score:
                        # Sorted descending - nothing below can match.
                        break
                    if allow_panel and need_panel_filter:
                        await run_panel_on(row)
                        panel_value = row.get("panel_score")
                        if panel_value is None or float(panel_value) < min_panel_score:
                            continue
                    selected.append(row)
                return selected

            while cursor < len(tickers):
                if threshold_mode and len(matched) >= output_count:
                    break
                if not threshold_mode and len(all_scored) >= output_count:
                    break
                if is_cancelled(run_id):
                    cancelled = True
                    await self._finalize_cancelled(run_id, stages)
                    return

                batch = tickers[cursor : cursor + batch_size]
                cursor += len(batch)
                batch_num += 1
                remaining = max(0, len(tickers) - cursor)
                catalyst_map: dict[str, Any] = {}

                # Never recommend wash-blocked tickers for repurchase.
                try:
                    wash = WashSaleService(self.db)
                    blocked = {
                        b["symbol"].upper() for b in await wash.active_blocks()
                    }
                    if blocked:
                        before = len(batch)
                        batch = [t for t in batch if t.upper() not in blocked]
                        dropped = before - len(batch)
                        if dropped:
                            await self.events.add(
                                run_id,
                                f"Wash-sale guard: skipped {dropped} blocked ticker(s) in batch.",
                                stage="screening",
                            )
                except Exception:
                    pass

                if lane == "swing" and batch:
                    await self.events.add(
                        run_id,
                        (
                            f"Swing event-first: scanning news/catalysts on {len(batch)} "
                            f"tickers for ~{hold_days}-day moves..."
                        ),
                        stage="screening",
                    )
                    hits = await scan_tickers_for_catalysts(
                        self.market,
                        batch,
                        hold_days=hold_days,
                        should_stop=lambda: is_cancelled(run_id),
                    )
                    catalyst_map = {h.ticker: h for h in hits}
                    if hits:
                        hit_tickers = [h.ticker for h in hits]
                        await self.events.add(
                            run_id,
                            (
                                f"Catalyst hits: {len(hits)} - prioritizing event names "
                                f"(top: {', '.join(hit_tickers[:5])})"
                            ),
                            stage="screening",
                        )
                        # Prefer catalyst names; keep a few non-hits only if scarce.
                        if len(hits) >= max(3, min(pool_size, len(batch)) // 2):
                            batch = hit_tickers[:batch_size]
                        else:
                            rest = [
                                t
                                for t in batch
                                if t.upper() not in catalyst_map
                            ]
                            batch = (hit_tickers + rest)[:batch_size]
                    else:
                        await self.events.add(
                            run_id,
                            "No strong catalyst headlines in this slice - screening anyway.",
                            stage="screening",
                        )

                if not batch:
                    continue

                if batch_num > 1:
                    if threshold_mode:
                        await self.events.add(
                            run_id,
                            (
                                f"Need more matches ({len(matched)}/{output_count}). "
                                f"Batch {batch_num}: screening {len(batch)} new tickers "
                                f"({remaining} left after this batch)."
                            ),
                            stage="screening",
                        )
                    else:
                        await self.events.add(
                            run_id,
                            (
                                f"Need more names ({len(all_scored)}/{output_count} analyzed). "
                                f"Batch {batch_num}: screening {len(batch)} new tickers "
                                f"({remaining} left after this batch)."
                            ),
                            stage="screening",
                        )

                await self._set_stage(
                    run_id,
                    stages,
                    "screening",
                    "active",
                    detail=f"Batch {batch_num}: screening {len(batch)} | {remaining} left",
                )
                await self.events.add(
                    run_id,
                    (
                        f"Batch {batch_num}: screening up to {len(batch)} tickers "
                        f"(stop early once {pool_size} are affordable, then analyze them)."
                    ),
                    stage="screening",
                )
                screen_started = time.monotonic()
                screen_checked = 0
                screen_passed = 0

                async def _screen_progress(
                    index: int, total: int, ticker: str, status: str
                ) -> None:
                    nonlocal screen_checked, screen_passed
                    screen_checked = index
                    if status == "pass":
                        screen_passed += 1
                    elapsed = time.monotonic() - screen_started
                    rate = index / elapsed if elapsed > 0 else 0
                    eta = (
                        f" | ~{(total - index) / rate:.0f}s left in batch"
                        if rate > 0 and index < total
                        else ""
                    )
                    # Heartbeat often enough to feel alive without flooding SQLite.
                    is_pass = status == "pass"
                    should_log = is_pass or (
                        index == 1 or index == total or index % 3 == 0
                    )
                    detail = (
                        f"Screen {index}/{total}: {ticker} {status} | "
                        f"{screen_passed} affordable so far | {elapsed:.0f}s{eta}"
                    )
                    await self._set_stage(
                        run_id,
                        stages,
                        "screening",
                        "active",
                        detail=detail,
                        log_event=should_log and not is_pass,
                    )
                    if is_pass:
                        await self.events.add(
                            run_id,
                            (
                                f"Affordable: {ticker} ({screen_passed} kept | "
                                f"{index}/{total} checked | {elapsed:.0f}s{eta})"
                            ),
                            stage="screening",
                        )

                screened = await screener.screen(
                    batch,
                    pool_size=pool_size,
                    should_stop=lambda: is_cancelled(run_id),
                    on_progress=_screen_progress,
                )
                if is_cancelled(run_id):
                    cancelled = True
                    await self._finalize_cancelled(run_id, stages)
                    return
                screened_total += len(screened)
                for cand in screened:
                    hit = catalyst_map.get(cand.ticker.upper())
                    if hit is not None:
                        cand.metrics["catalyst_score"] = hit.score
                        cand.metrics["horizon_fit"] = hit.horizon_fit
                        cand.metrics["hold_days"] = hold_days
                        cand.metrics["catalyst_headline"] = hit.headline
                        cand.metrics["catalyst_labels"] = hit.labels
                        cand.metrics["news_count"] = max(
                            int(cand.metrics.get("news_count") or 0),
                            int(hit.news_count),
                        )
                    elif lane == "swing":
                        cand.metrics["hold_days"] = hold_days
                    metrics_by_ticker[cand.ticker] = cand.metrics
                await self._set_stage(
                    run_id,
                    stages,
                    "screening",
                    "complete",
                    detail=(
                        f"{screened_total} affordable total | batch {batch_num} kept {len(screened)}"
                        + (f" | {remaining} tickers still untried" if remaining else "")
                    ),
                )
                if not screened:
                    await self.events.add(
                        run_id,
                        (
                            f"Batch {batch_num}: none of {len(batch)} passed the budget screen. "
                            + (
                                f"Continuing with the next batch ({remaining} left)."
                                if remaining
                                else "No more tickers left to try."
                            )
                        ),
                        stage="screening",
                    )
                    continue

                # Open search: only analyze as many as we still need.
                if not threshold_mode:
                    still_need = max(0, output_count - len(all_scored))
                    if still_need <= 0:
                        break
                    if len(screened) > still_need:
                        await self.events.add(
                            run_id,
                            (
                                f"Batch {batch_num}: keeping {still_need} of "
                                f"{len(screened)} affordable for analysis "
                                f"(need {output_count} total)."
                            ),
                            stage="screening",
                        )
                        screened = screened[:still_need]

                await self.events.add(
                    run_id,
                    (
                        f"Batch {batch_num}: {len(screened)} passed screening "
                        f"({', '.join(c.ticker for c in screened[:8])}"
                        f"{'...' if len(screened) > 8 else ''}). Gathering evidence."
                    ),
                    stage="evidence",
                )
                await self._set_stage(run_id, stages, "evidence", "active")
                evidence_started = time.monotonic()
                for ev_i, cand in enumerate(screened, start=1):
                    if is_cancelled(run_id):
                        cancelled = True
                        break
                    await self.events.add(
                        run_id,
                        f"Evidence {ev_i}/{len(screened)}: gathering {cand.ticker}...",
                        stage="evidence",
                    )
                    await self._set_stage(
                        run_id,
                        stages,
                        "evidence",
                        "active",
                        detail=f"Evidence {ev_i}/{len(screened)}: {cand.ticker}",
                        log_event=False,
                    )
                    items = await gatherer.gather_for_candidate(cand, run_id)
                    evidence_by_ticker[cand.ticker] = items
                    await self.evidence.save_many(items)
                    await self.events.add(
                        run_id,
                        (
                            f"Evidence {ev_i}/{len(screened)}: {cand.ticker} "
                            f"saved {len(items)} items "
                            f"({time.monotonic() - evidence_started:.0f}s batch)"
                        ),
                        stage="evidence",
                    )
                if cancelled or is_cancelled(run_id):
                    await self._finalize_cancelled(run_id, stages)
                    return
                await self._set_stage(
                    run_id,
                    stages,
                    "evidence",
                    "complete",
                    detail=f"{sum(len(v) for v in evidence_by_ticker.values())} evidence items",
                )

                researcher_notes: dict[str, dict[str, Any]] = {}
                if researcher is not None:
                    await self._set_stage(run_id, stages, "research", "active")
                    # Analyze every affordable name from this batch (already capped).
                    research_limit = len(screened)
                    await self.events.add(
                        run_id,
                        (
                            f"Batch {batch_num}: researching {research_limit} names "
                            f"with the local model (each may take a while; cache hits are faster)."
                        ),
                        stage="research",
                    )
                    research_started = time.monotonic()
                    for res_i, cand in enumerate(screened[:research_limit], start=1):
                        if is_cancelled(run_id):
                            cancelled = True
                            break
                        remaining_r = research_limit - res_i + 1
                        await self.events.add(
                            run_id,
                            (
                                f"Research {res_i}/{research_limit}: {cand.ticker} "
                                f"starting ({remaining_r} left in batch)..."
                            ),
                            stage="research",
                        )
                        await self._set_stage(
                            run_id,
                            stages,
                            "research",
                            "active",
                            detail=f"Research {res_i}/{research_limit}: {cand.ticker}",
                            log_event=False,
                        )
                        one_started = time.monotonic()
                        note = await researcher.research(
                            cand.ticker,
                            evidence_by_ticker.get(cand.ticker, []),
                            cand.metrics,
                        )
                        one_elapsed = time.monotonic() - one_started
                        batch_elapsed = time.monotonic() - research_started
                        avg = batch_elapsed / res_i
                        eta_r = (
                            f" | ~{avg * (research_limit - res_i):.0f}s left"
                            if res_i < research_limit
                            else ""
                        )
                        if note:
                            researcher_notes[cand.ticker] = note
                            source = "cache" if note.get("cached") else "model"
                            await self.events.add(
                                run_id,
                                (
                                    f"Research {res_i}/{research_limit}: {cand.ticker} "
                                    f"done via {source} in {one_elapsed:.1f}s "
                                    f"(batch {batch_elapsed:.0f}s{eta_r})"
                                ),
                                stage="research",
                            )
                        else:
                            await self.events.add(
                                run_id,
                                (
                                    f"Research {res_i}/{research_limit}: {cand.ticker} "
                                    f"returned no note after {one_elapsed:.1f}s{eta_r}"
                                ),
                                stage="research",
                                level="warning",
                            )
                    if cancelled or is_cancelled(run_id):
                        await self._finalize_cancelled(run_id, stages)
                        return
                    researcher_available = True
                    await self._set_stage(
                        run_id,
                        stages,
                        "research",
                        "complete",
                        detail=f"Researched {len(researcher_notes)} names",
                    )

                await self._set_stage(run_id, stages, "scoring", "active")
                peer_metrics = [c.metrics for c in screened]
                batch_scored: list[dict[str, Any]] = []
                score_started = time.monotonic()
                await self.events.add(
                    run_id,
                    f"Scoring {len(screened)} affordable names in batch {batch_num}...",
                    stage="scoring",
                )
                for score_i, cand in enumerate(screened, start=1):
                    result = scorer.score_candidate(
                        cand.ticker,
                        cand.metrics,
                        peer_metrics,
                        evidence_by_ticker.get(cand.ticker, []),
                        researcher_summary=(researcher_notes.get(cand.ticker) or {}).get(
                            "summary"
                        ),
                        researcher_available=researcher_available
                        and cand.ticker in researcher_notes,
                    )
                    payload = result.to_dict()
                    payload["name"] = cand.metrics.get("name")
                    payload["sector"] = cand.metrics.get("sector")
                    payload["price"] = cand.metrics.get("price")
                    payload["shares_buyable"] = cand.metrics.get("shares_buyable")
                    payload["metrics"] = cand.metrics
                    payload["researcher"] = researcher_notes.get(cand.ticker)
                    batch_scored.append(payload)
                    if score_i == 1 or score_i == len(screened) or score_i % 5 == 0:
                        await self.events.add(
                            run_id,
                            (
                                f"Score {score_i}/{len(screened)}: {cand.ticker} "
                                f"{float(payload['score']):.1f}"
                            ),
                            stage="scoring",
                        )
                        await self._set_stage(
                            run_id,
                            stages,
                            "scoring",
                            "active",
                            detail=(
                                f"Score {score_i}/{len(screened)}: {cand.ticker} "
                                f"{float(payload['score']):.1f}"
                            ),
                            log_event=False,
                        )
                batch_scored.sort(key=lambda row: row["score"], reverse=True)
                all_scored.extend(batch_scored)
                top_preview = ", ".join(
                    f"{r['ticker']} {float(r['score']):.0f}" for r in batch_scored[:5]
                )
                await self._set_stage(
                    run_id,
                    stages,
                    "scoring",
                    "active",
                    detail=(
                        f"{len(all_scored)} scored this run | selecting matches..."
                        f" | batch top: {top_preview or 'none'} "
                        f"({time.monotonic() - score_started:.1f}s)"
                    ),
                    log_event=False,
                )
                await publish_candidates()

                if threshold_mode:
                    under = [
                        row
                        for row in batch_scored
                        if min_score > 0 and float(row["score"]) < min_score
                    ]
                    score_ok = [
                        row
                        for row in all_scored
                        if min_score <= 0 or float(row["score"]) >= min_score
                    ]
                    if under:
                        sample = ", ".join(
                            f"{r['ticker']} {float(r['score']):.0f}" for r in under[:5]
                        )
                        await self.events.add(
                            run_id,
                            (
                                f"Batch {batch_num}: {len(under)} under score floor "
                                f"(e.g. {sample}{'...' if len(under) > 5 else ''}). "
                                "Kept in results; ranking still prefers higher scores."
                            ),
                            stage="scoring",
                        )
                    await self.events.add(
                        run_id,
                        (
                            f"Batch {batch_num}: {len(all_scored)} scored total, "
                            f"{len(score_ok)} at/above score floor >={min_score:.0f}. "
                            "Selecting best scores first"
                            + (
                                f", then applying panel floor >={min_panel_score:.0f}."
                                if min_panel_score > 0
                                else "."
                            )
                        ),
                        stage="scoring",
                    )

                    # Floors filter selection; panel still runs on kept matches
                    # even when min panel is 0 so Found stocks get panel scores.
                    matched = await select_best_matches(allow_panel=need_panel_filter)
                    if cancelled:
                        break
                    if panel is not None and matched:
                        await self._set_stage(run_id, stages, "counsel", "active")
                        for cand_payload in matched[:output_count]:
                            if is_cancelled(run_id):
                                cancelled = True
                                break
                            await run_panel_on(cand_payload)
                            await publish_candidates()
                        if cancelled:
                            break
                        await self._set_stage(
                            run_id,
                            stages,
                            "counsel",
                            "complete",
                            detail=(
                                f"{panel_reviews} panel reviews | "
                                f"{len(matched)}/{output_count} matches"
                            ),
                        )
                    elif panel is None:
                        # Keep earlier skipped detail if already set.
                        for stage in stages:
                            if stage["id"] == "counsel" and stage["status"] == "pending":
                                stage["status"] = "skipped"
                                stage["detail"] = "Counsel unavailable"
                                await self.runs.patch_result(run_id, {"stages": stages})

                    await self._set_stage(
                        run_id,
                        stages,
                        "scoring",
                        "complete",
                        detail=(
                            f"{len(all_scored)} scored | "
                            f"{len(matched)}/{output_count} matches"
                        ),
                    )
                    if matched:
                        preview = ", ".join(
                            (
                                f"{r['ticker']} {float(r['score']):.0f}"
                                + (
                                    f"/{float(r['panel_score']):.0f}p"
                                    if r.get("panel_score") is not None
                                    else ""
                                )
                            )
                            for r in matched[:5]
                        )
                        await self.events.add(
                            run_id,
                            (
                                f"Matches so far ({len(matched)}/{output_count}): {preview}"
                                f"{'...' if len(matched) > 5 else ''}"
                            ),
                            stage="counsel" if panel is not None else "scoring",
                        )
                    await publish_candidates()
                else:
                    counsel_limit = int(config.discovery.get("counsel_top_n", 5))
                    score_passers = batch_scored[
                        : max(1, min(counsel_limit, len(batch_scored)))
                    ]
                    await self._set_stage(
                        run_id,
                        stages,
                        "scoring",
                        "complete",
                        detail=(
                            f"{len(all_scored)} scored | "
                            f"target {output_count}"
                        ),
                    )
                    if panel is not None and score_passers:
                        await self._set_stage(run_id, stages, "counsel", "active")
                        for cand_payload in score_passers:
                            if is_cancelled(run_id):
                                cancelled = True
                                break
                            await run_panel_on(cand_payload)
                            await publish_candidates()
                        if cancelled:
                            break
                        await self._set_stage(
                            run_id,
                            stages,
                            "counsel",
                            "complete",
                            detail=f"{panel_reviews} names reviewed",
                        )

                await self.history.record_many(
                    run_id,
                    all_scored,
                    output_limit=max(len(matched), output_count, 1),
                    lane=lane,
                )

                if threshold_mode:
                    if len(matched) >= output_count:
                        await self.events.add(
                            run_id,
                            (
                                f"Have {len(matched)}/{output_count} matches after "
                                f"{batch_num} batch(es) | {len(all_scored)} scored. Stopping."
                            ),
                            stage="scoring",
                        )
                        break
                    if remaining > 0:
                        await self.events.add(
                            run_id,
                            (
                                f"Criteria not filled yet ({len(matched)}/{output_count}). "
                                f"Will try more stocks - {remaining} tickers remain."
                            ),
                            stage="screening",
                        )
                else:
                    if len(all_scored) >= output_count:
                        await self.events.add(
                            run_id,
                            (
                                f"Analyzed {len(all_scored)}/{output_count} names after "
                                f"{batch_num} batch(es). Stopping - hit Stop earlier next time "
                                f"if you already had enough."
                            ),
                            stage="scoring",
                        )
                        break
                    if remaining > 0:
                        await self.events.add(
                            run_id,
                            (
                                f"Only {len(all_scored)}/{output_count} analyzed so far. "
                                f"Starting another batch ({remaining} tickers remain)."
                            ),
                            stage="screening",
                        )

            if cancelled or is_cancelled(run_id):
                await self._finalize_cancelled(run_id, stages)
                return

            if threshold_mode:
                # Final pass: best scores that clear floors (panel if required).
                if need_panel_filter and panel is not None:
                    matched = await select_best_matches(allow_panel=True)
                else:
                    matched = await select_best_matches(allow_panel=False)
                top_matches = matched[:output_count]
                # Ensure every kept name has a panel score when counsel is up.
                if panel is not None:
                    await self._set_stage(run_id, stages, "counsel", "active")
                    for row in top_matches:
                        if is_cancelled(run_id):
                            cancelled = True
                            break
                        await run_panel_on(row)
                    if not cancelled:
                        await self._set_stage(
                            run_id,
                            stages,
                            "counsel",
                            "complete",
                            detail=(
                                f"{panel_reviews} panel reviews | "
                                f"{len(top_matches)}/{output_count} matches"
                            ),
                        )
                top_matches.sort(key=lambda row: row["score"], reverse=True)
            else:
                all_scored.sort(key=lambda row: row["score"], reverse=True)
                top_matches = all_scored[:output_count]

            visible = await publish_candidates()
            # Prefer matches at the front of the published list.
            if top_matches:
                match_tickers = {r["ticker"] for r in top_matches}
                head = [r for r in visible if r["ticker"] in match_tickers]
                tail = [r for r in visible if r["ticker"] not in match_tickers]
                visible = head + tail

            if cancelled:
                status = "cancelled"
            elif not top_matches and threshold_mode and not all_scored:
                raise RuntimeError(
                    "No candidates passed screening for this budget. "
                    "Try a higher investable amount or lower min whole shares."
                )
            elif not top_matches and threshold_mode:
                status = "complete"
                await self.events.add(
                    run_id,
                    (
                        f"Finished universe without filling criteria "
                        f"({len(matched)}/{output_count} matches after {screened_total} screened). "
                        "Below-criteria names are still listed so you can inspect them."
                    ),
                    stage="scoring",
                    level="warning",
                )
            else:
                status = "complete"

            if not visible and not all_scored:
                raise RuntimeError(
                    "No candidates passed screening for this budget. "
                    "Try a higher investable amount or lower min whole shares."
                )

            for stage in stages:
                if stage["status"] == "active":
                    stage["status"] = "complete"
                elif stage["status"] == "pending":
                    if stage["id"] == "counsel" and panel is None:
                        stage["status"] = "skipped"
                        stage["detail"] = stage.get("detail") or "Counsel unavailable"
                    else:
                        stage["status"] = "complete"
                        if not stage.get("detail"):
                            stage["detail"] = "Done"

            await self._set_stage(
                run_id,
                stages,
                "scoring",
                "complete",
                detail=(
                    f"{len(all_scored)} scored | "
                    f"{len(top_matches)}/{output_count} matches"
                ),
                log_event=False,
            )

            note = (
                f"{'Stopped early' if cancelled else 'Finished'}: "
                f"{len(top_matches)}/{output_count} matches | "
                f"{len(all_scored)} scored | {screened_total} screened | "
                f"{cursor}/{len(tickers)} tickers tried"
            )
            await self.events.add(run_id, note, stage="scoring")
            await self.runs.update_status(
                run_id,
                status,
                result={
                    "stages": stages,
                    "candidates": visible or [
                        _annotate_threshold(
                            r,
                            min_score=min_score,
                            min_panel_score=min_panel_score,
                            threshold_mode=threshold_mode,
                        )
                        for r in top_matches
                    ],
                    "all_scored": [
                        _annotate_threshold(
                            r,
                            min_score=min_score,
                            min_panel_score=min_panel_score,
                            threshold_mode=threshold_mode,
                        )
                        for r in all_scored
                    ],
                    "error": None,
                    "researcher_available": researcher_available,
                    "stats": {
                        "lane": lane,
                        "universe_loaded": universe_before_exclude,
                        "universe_size": len(tickers),
                        "excluded_seen": skipped,
                        "screened": screened_total,
                        "scored": len(all_scored),
                        "output_count": len(top_matches),
                        "target_count": output_count,
                        "min_score": min_score,
                        "min_panel_score": min_panel_score,
                        "matched": len(top_matches),
                        "batches": batch_num,
                        "tickers_tried": cursor,
                        "cancelled": cancelled,
                        "investable_amount": investable_amount,
                        "min_whole_shares": min_whole_shares,
                    },
                },
                complete=True,
            )
            clear_cancel(run_id)
        except asyncio.CancelledError:
            await self._finalize_cancelled(run_id, stages)
            return
        except Exception as exc:
            err = f"{exc}"
            current = await self.runs.get(run_id)
            prior = (current or {}).get("result") or {}
            await self.runs.update_status(
                run_id,
                "error",
                result={
                    "stages": stages,
                    "candidates": prior.get("candidates") or [],
                    "all_scored": prior.get("all_scored") or [],
                    "error": err,
                    "traceback": traceback.format_exc(),
                },
                complete=True,
            )
            clear_cancel(run_id)

    async def reexamine(self, run_id: str, ticker: str, params: dict[str, Any]) -> None:
        """Re-run evidence, research, scoring, and counsel for one saved ticker."""
        stages = [
            {"id": sid, "label": label, "status": "pending", "detail": None}
            for sid, label in (
                ("load", "Load saved ticker"),
                ("evidence", "Evidence"),
                ("research", "Research"),
                ("scoring", "Scoring"),
                ("counsel", "Counsel"),
            )
        ]
        await self.runs.patch_result(
            run_id, {"stages": stages, "candidates": [], "error": None}
        )
        symbol = ticker.upper().strip()
        try:
            config = get_app_config()
            lane_raw = str(params.get("lane") or "invest").strip().lower()
            if lane_raw == "daytrade":
                lane = "daytrade"
            elif lane_raw == "swing":
                lane = "swing"
            else:
                lane = "invest"
            investable_amount = float(
                params.get("investable_amount")
                if params.get("investable_amount") is not None
                else config.discovery.get("investable_amount", 100)
            )
            min_whole_shares = int(
                params.get("min_whole_shares")
                if params.get("min_whole_shares") is not None
                else config.discovery.get("min_whole_shares", 5)
            )
            min_avg_volume = (
                float(config.discovery.get("daytrade_min_avg_volume", 750_000))
                if lane == "daytrade"
                else float(config.discovery.get("min_avg_volume", 150_000))
            )
            await self._set_stage(
                run_id, stages, "load", "active", detail=f"Loading {symbol}"
            )
            await self.events.add(
                run_id, f"Load: fetching market data for {symbol}...", stage="load"
            )
            screener = DeterministicScreener(
                self.market,
                investable_amount=investable_amount,
                min_whole_shares=min_whole_shares,
                min_avg_volume=min_avg_volume,
            )
            candidate = await screener.load_one(symbol)
            await self._set_stage(
                run_id,
                stages,
                "load",
                "complete",
                detail=f"{symbol} @ {candidate.metrics.get('price')}",
            )

            await self._set_stage(run_id, stages, "evidence", "active")
            await self.events.add(
                run_id, f"Evidence: gathering for {symbol}...", stage="evidence"
            )
            gatherer = EvidenceGatherer(self.market)
            items = await gatherer.gather_for_candidate(candidate, run_id)
            await self.evidence.save_many(items)
            await self._set_stage(
                run_id,
                stages,
                "evidence",
                "complete",
                detail=f"{len(items)} evidence items",
            )

            await self._set_stage(run_id, stages, "research", "active")
            researcher_notes: dict[str, Any] | None = None
            ollama_ok = False
            model_name = None
            if config.providers.ollama.enabled:
                ollama_ok = await self.ollama.health()
                if ollama_ok:
                    models = await self.ollama.list_models()
                    model_name = models[0] if models else None
            if ollama_ok and model_name:
                researcher = DiscoveryResearcher(
                    self.ollama,
                    model_name=model_name,
                    usage_store=self.usage,
                    cache=self.cache,
                )
                await self.events.add(
                    run_id,
                    (
                        f"Research: starting {symbol} "
                        "(same cache key as discovery when evidence matches)..."
                    ),
                    stage="research",
                )
                # Match discovery: reuse LLM cache when evidence/metrics fingerprint matches.
                researcher_notes = await researcher.research(
                    symbol, items, candidate.metrics, use_cache=True
                )
                await self._set_stage(
                    run_id,
                    stages,
                    "research",
                    "complete",
                    detail=f"Researched with {model_name}",
                )
                researcher_available = researcher_notes is not None
            else:
                await self._set_stage(
                    run_id,
                    stages,
                    "research",
                    "skipped",
                    detail="Ollama unavailable - scoring from market evidence only",
                )
                researcher_available = False

            await self._set_stage(run_id, stages, "scoring", "active")
            score_weights = (
                None
                if lane in {"daytrade", "swing"}
                else (dict(config.discovery_score) if config.discovery_score else None)
            )
            scorer = DiscoveryScorer(
                weights=score_weights,
                decimals=int(config.scoring.get("decimals", 1)),
                profile=lane,
            )
            # Same absolute-first scorer as discovery; peers only nudge when n>=5.
            peer_metrics = await self.history.peer_metrics_for_lane(
                lane, exclude_ticker=symbol
            )
            await self.events.add(
                run_id,
                (
                    f"Scoring {symbol} with absolute scales"
                    + (
                        f" + {len(peer_metrics)} lane peers"
                        if len(peer_metrics) >= 5
                        else " (peers too few for blend)"
                    )
                    + "..."
                ),
                stage="scoring",
            )
            result = scorer.score_candidate(
                symbol,
                candidate.metrics,
                peer_metrics,
                items,
                researcher_summary=(researcher_notes or {}).get("summary"),
                researcher_available=researcher_available,
            )
            payload = result.to_dict()
            payload["name"] = candidate.metrics.get("name")
            payload["sector"] = candidate.metrics.get("sector")
            payload["price"] = candidate.metrics.get("price")
            payload["shares_buyable"] = candidate.metrics.get("shares_buyable")
            payload["metrics"] = candidate.metrics
            payload["researcher"] = researcher_notes
            await self.history.record_many(
                run_id, [payload], output_limit=1, lane=lane
            )
            await self.runs.patch_result(run_id, {"candidates": [payload]})
            await self._set_stage(
                run_id, stages, "scoring", "complete", detail=f"Score {payload['score']}"
            )

            await self._set_stage(run_id, stages, "counsel", "active")
            if ollama_ok:
                installed = await self.ollama.list_models()
                role_assignments: list[tuple[str, str, str]] = []
                for role in ("fundamental", "skeptic", "counsel"):
                    resolved = resolve_role_model(role, list(config.models), installed)
                    if resolved:
                        role_assignments.append((role, resolved[0], resolved[1]))
                if role_assignments:
                    panel = CounselPanel(
                        self.ollama, usage_store=self.usage, cache=self.cache
                    )
                    await self.events.add(
                        run_id,
                        (
                            f"Panel: reviewing {symbol} with {len(role_assignments)} roles "
                            "(same cache policy as discovery)..."
                        ),
                        stage="counsel",
                    )
                    findings = await panel.review(
                        symbol,
                        items,
                        candidate.metrics,
                        roles=role_assignments,
                        use_cache=True,
                    )
                    summary = aggregate_panel(
                        findings,
                        dict(config.discovery_score) if config.discovery_score else None,
                    )
                    payload["panel_score"] = summary["panel_score"]
                    payload["panel_spread"] = summary["panel_spread"]
                    payload["agents"] = summary["agents"]
                    await self.history.record_many(
                        run_id, [payload], output_limit=1, lane=lane
                    )
                    await self.runs.patch_result(run_id, {"candidates": [payload]})
                    await self._set_stage(
                        run_id,
                        stages,
                        "counsel",
                        "complete",
                        detail=(
                            f"Panel {summary['panel_score']}/100"
                            if summary["panel_score"] is not None
                            else "No counsel output"
                        ),
                    )
                    await self.events.add(
                        run_id,
                        (
                            f"Panel: {symbol} -> "
                            f"{summary['panel_score'] if summary['panel_score'] is not None else 'n/a'}/100 "
                            f"({len(findings)} roles)"
                        ),
                        stage="counsel",
                    )
                else:
                    await self._set_stage(
                        run_id,
                        stages,
                        "counsel",
                        "skipped",
                        detail="No local model available",
                    )
            else:
                await self._set_stage(
                    run_id,
                    stages,
                    "counsel",
                    "skipped",
                    detail="Ollama unavailable",
                )

            for stage in stages:
                if stage["status"] in ("active", "pending"):
                    stage["status"] = "complete"

            await self.runs.update_status(
                run_id,
                "complete",
                result={
                    "stages": stages,
                    "candidates": [payload],
                    "all_scored": [payload],
                    "error": None,
                    "researcher_available": researcher_available,
                    "stats": {
                        "reexamine": symbol,
                        "lane": lane,
                        "score": payload.get("score"),
                        "panel_score": payload.get("panel_score"),
                    },
                },
                complete=True,
            )
        except asyncio.CancelledError:
            await self._finalize_cancelled(run_id, stages)
            return
        except Exception as exc:
            current = await self.runs.get(run_id)
            prior = (current or {}).get("result") or {}
            await self.runs.update_status(
                run_id,
                "error",
                result={
                    "stages": stages,
                    "candidates": prior.get("candidates") or [],
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
                complete=True,
            )
