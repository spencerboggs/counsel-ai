"""Background Autopilot loop with cooperative cancel and wake reconcile."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from backend.autopilot.cycle import run_cycle
from backend.autopilot.state import AutopilotStore
from backend.autopilot.wake import wake_reconcile
from backend.config.settings import get_app_config, get_settings
from backend.config.secrets import load_secrets
from backend.providers.alpaca import active_trading_backend
from backend.providers.ollama import OllamaProvider
from backend.storage.database import Database
from backend.storage.research_runs import ResearchRunStore
from backend.storage.run_events import RunEventStore


_task: asyncio.Task[None] | None = None
_cancel = asyncio.Event()
_run_id: str | None = None


def is_loop_running() -> bool:
    return _task is not None and not _task.done()


def current_run_id() -> str | None:
    return _run_id


async def stop_loop(db: Database) -> dict[str, Any]:
    global _task, _run_id
    _cancel.set()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None
    store = AutopilotStore(db)
    state = await store.set_running(False)
    if _run_id:
        runs = ResearchRunStore(db)
        await runs.patch_result(_run_id, {"status_note": "stopped"})
        await runs.update_status(_run_id, "cancelled", complete=True)
    _run_id = None
    return state


async def start_loop(
    db: Database,
    *,
    config: dict[str, Any],
    arm_live_confirmed: bool = False,
    app_background_tasks: set[asyncio.Task[Any]] | None = None,
) -> dict[str, Any]:
    global _task, _run_id, _cancel

    backend = active_trading_backend()
    if backend == "live_alpaca" and not arm_live_confirmed:
        raise ValueError(
            "Live Autopilot requires arm_live_confirmed=true "
            "(type ARM LIVE AUTOPILOT in the UI)."
        )

    if is_loop_running():
        raise ValueError("Autopilot is already running")

    store = AutopilotStore(db)
    prior = await store.get()
    asleep_since = prior.get("asleep_since") or prior.get("stopped_at")

    # Reset cancel flag without stomping asleep_since when already stopped.
    _cancel = asyncio.Event()
    wake = await wake_reconcile(db, asleep_since=asleep_since)
    if wake.get("trading_halted_for_mismatch"):
        # Halt trading until local and broker positions match.
        config = {**config, "halt_trading": True, "halt_reason": wake.get("mismatches")}

    run_id = f"ap-{uuid.uuid4().hex[:12]}"
    _run_id = run_id
    runs = ResearchRunStore(db)
    await runs.create(run_id, "autopilot", {**config, "venue": backend})
    events = RunEventStore(db)
    await events.add(
        run_id,
        wake.get("asleep_note") or "Autopilot starting.",
        stage="wake",
    )
    if wake.get("mismatches"):
        await events.add(
            run_id,
            "Position mismatch vs broker: " + "; ".join(wake["mismatches"]),
            stage="wake",
            level="warn",
        )

    await store.set_running(True, config=config, wake=wake, error=None)

    async def _runner() -> None:
        settings = get_settings()
        secrets = load_secrets()
        cfg = get_app_config()
        base = (
            secrets.ollama_base_url
            or cfg.providers.ollama.base_url
            or settings.ollama_base_url
        )
        ollama = OllamaProvider(base_url=base)
        cycle_seconds = max(30, int(config.get("cycle_seconds") or 120))
        try:
            while not _cancel.is_set():
                if wake.get("trading_halted_for_mismatch") and config.get("halt_trading"):
                    await events.add(
                        run_id,
                        "Trading halted until local/broker positions match. Research-only cycle.",
                        stage="wake",
                        level="warn",
                    )
                try:
                    # Re-fetch wake halt only first cycle; subsequent cycles trade if not halted
                    cycle_cfg = dict(config)
                    if cycle_cfg.get("halt_trading"):
                        # Block buys while halted by setting max_positions to 0.
                        cycle_cfg["max_positions"] = 0
                    await run_cycle(db, ollama=ollama, run_id=run_id, config=cycle_cfg)
                except Exception as exc:
                    await events.add(run_id, f"Cycle error: {exc}", stage="error", level="error")
                    await AutopilotStore(db).mark_cycle(error=str(exc))
                try:
                    await asyncio.wait_for(_cancel.wait(), timeout=cycle_seconds)
                    break
                except asyncio.TimeoutError:
                    continue
        finally:
            await AutopilotStore(db).set_running(False)
            try:
                await runs.update_status(
                    run_id,
                    "cancelled" if _cancel.is_set() else "complete",
                    complete=True,
                )
            except Exception:
                pass

    _task = asyncio.create_task(_runner())
    if app_background_tasks is not None:
        app_background_tasks.add(_task)
        _task.add_done_callback(app_background_tasks.discard)
    return {
        "run_id": run_id,
        "running": True,
        "venue": backend,
        "wake": wake,
        "config": config,
    }
