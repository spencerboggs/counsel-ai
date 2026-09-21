"""Run one Autopilot cycle: signals, crew, consensus, gated execute."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Awaitable

from backend.autopilot.consensus import evaluate_consensus
from backend.autopilot.crew import AutopilotCrew
from backend.autopilot.signals import gather_cycle_context
from backend.autopilot.state import AutopilotStore
from backend.config.settings import get_app_config
from backend.portfolio.capital_gate import CapitalGateError
from backend.portfolio.executor import TradeExecutor
from backend.portfolio.store import PaperPositionStore
from backend.providers.ollama import OllamaProvider
from backend.storage.database import Database
from backend.storage.llm_cache import LlmCache
from backend.storage.run_events import RunEventStore
from backend.storage.usage import UsageStore


ProgressFn = Callable[[str, str], Awaitable[None] | None]


async def run_cycle(
    db: Database,
    *,
    ollama: OllamaProvider,
    run_id: str,
    config: dict[str, Any],
    on_event: ProgressFn | None = None,
) -> dict[str, Any]:
    store = AutopilotStore(db)
    events = RunEventStore(db)
    cycle_id = f"apc-{uuid.uuid4().hex[:10]}"

    async def log(message: str, stage: str = "cycle") -> None:
        await events.add(run_id, message, stage=stage)
        if on_event:
            maybe = on_event(stage, message)
            if maybe is not None:
                await maybe

    await log("Gathering capital, positions, and quantitative signals...", "signals")

    # Mid-run reconcile every cycle when broker-backed (cheap REST, free paper keys).
    try:
        from backend.autopilot.wake import wake_reconcile
        from backend.compliance.kill_switch import KillSwitch
        from backend.compliance.market_hours import session_status
        from backend.compliance.risk_gates import trading_config

        wake = await wake_reconcile(db, asleep_since=None)
        if wake.get("trading_halted_for_mismatch"):
            config = {**config, "halt_trading": True, "halt_reason": wake.get("mismatches")}
            await log(
                "Broker/local mismatch - trading halted this cycle: "
                + "; ".join(wake.get("mismatches") or []),
                "wake",
            )
        session = session_status(
            allow_extended_hours=trading_config()["allow_extended_hours"]
        )
        await log(
            f"Market session: {session.get('phase')} | "
            f"open_for_orders={session.get('open_for_market_orders')} | "
            f"ET {session.get('local_et')}",
            "session",
        )
        if await KillSwitch(db).is_disabled():
            await log("Kill switch ON - deliberation only, no execution.", "risk")
            config = {**config, "halt_trading": True, "halt_reason": "kill_switch"}
        if not session.get("open_for_market_orders"):
            await log(
                "Outside RTH - Autopilot may deliberate but CapitalGate blocks fills.",
                "session",
            )
    except Exception as exc:
        await log(f"Pre-cycle safety check warning: {exc}", "risk")

    context = await gather_cycle_context(
        db,
        max_new_candidates=int(config.get("max_new_candidates") or 6),
    )
    await log(
        (
            f"BP={context.get('buying_power')} | "
            f"watching {len(context.get('watched') or [])} | "
            f"candidates {len(context.get('candidates') or [])} | "
            f"wash blocks {len(context.get('wash_blocks') or [])}"
        ),
        "signals",
    )

    # Choose focus: open position needing review, else top candidate.
    focus = None
    watched = context.get("watched") or []
    candidates = context.get("candidates") or []
    if watched:
        focus = watched[0]
        focus["_intent"] = "review_open"
    elif candidates:
        focus = candidates[0]
        focus["_intent"] = "consider_buy"

    if focus is None:
        await store.record_decision(
            cycle_id=cycle_id,
            action="none",
            status="skipped",
            notes="No watchlist or candidates this cycle.",
        )
        await store.mark_cycle()
        await log("Nothing to deliberate - idle cycle.", "cycle")
        return {"cycle_id": cycle_id, "status": "idle", "context": context}

    cfg = get_app_config()
    crew = AutopilotCrew(
        ollama,
        usage_store=UsageStore(db),
        cache=LlmCache(db),
        model_registry=list(cfg.models),
    )
    await log(f"Crew deliberating on {focus.get('ticker')}...", "crew")
    votes = await crew.deliberate(context, focus=focus, use_cache=False)
    trader = next((v for v in votes if v.get("role") == "trader"), {})
    proposal = trader.get("proposal") if isinstance(trader.get("proposal"), dict) else None

    wash_blocked = {str(s).upper() for s in (context.get("wash_blocks") or [])}
    consensus = evaluate_consensus(
        votes,
        proposal=proposal,
        allowlist=list(context.get("allowlist") or []),
        wash_blocked=wash_blocked,
    )
    await log(
        (
            f"Consensus: approved={consensus.get('approved')} "
            f"action={consensus.get('action')} - "
            f"{'; '.join(consensus.get('reasons') or [])}"
        ),
        "consensus",
    )

    execution: dict[str, Any] | None = None
    status = "rejected"
    if config.get("halt_trading"):
        status = "halted"
        await log(
            f"Execution skipped - halt: {config.get('halt_reason')}",
            "execute",
        )
    elif consensus.get("approved") and consensus.get("action") in {"buy", "sell"}:
        executor = TradeExecutor(db)
        symbol = str(consensus.get("symbol") or "").upper()
        try:
            if consensus["action"] == "buy":
                from backend.portfolio.kelly import size_notional
                from backend.compliance.risk_gates import trading_config

                tcfg = trading_config()
                max_bet = float(tcfg.get("max_bet_pct") or 0.06)
                notional = float(consensus.get("notional") or 0)
                shares = float(consensus.get("shares") or 0)
                price = focus.get("price")
                if notional <= 0 and shares > 0 and price:
                    notional = shares * float(price)
                # Prefer Kelly / 6% cap over trader-proposed size
                bp = float(context.get("buying_power") or 0)
                equity = float(
                    (context.get("capital") or {}).get("equity")
                    or (context.get("capital") or {}).get("cash")
                    or bp
                )
                capital_base = min(bp, equity) if equity else bp
                conf = float(trader.get("confidence") or 0.7)
                sized = size_notional(
                    equity_or_bp=capital_base,
                    probe=focus.get("historical_probe"),
                    confidence=conf,
                )
                kelly_notional = float(sized.get("notional") or 0)
                hard_cap = capital_base * max_bet
                if kelly_notional > 0:
                    notional = min(kelly_notional, hard_cap)
                elif notional <= 0:
                    notional = hard_cap * 0.5
                else:
                    notional = min(notional, hard_cap)
                await log(
                    (
                        f"Sizing {symbol}: notional=${notional:.2f} "
                        f"({sized.get('bet_pct', 0):.1%} of capital, "
                        f"max_bet={max_bet:.0%}) - {sized.get('kelly', {}).get('reason', '')}"
                    ),
                    "risk",
                )
                # Cap positions
                open_n = len(context.get("open_positions") or [])
                max_pos = int(config.get("max_positions") or tcfg.get("max_positions") or 8)
                if open_n >= max_pos:
                    raise CapitalGateError(
                        "max_positions",
                        f"Already at max_positions={max_pos}",
                    )
                live_armed = bool(config.get("arm_live_confirmed"))
                result = await executor.buy(
                    ticker=symbol,
                    shares=0,
                    price=float(price) if price else None,
                    notional=notional,
                    source_run_id=run_id,
                    notes=f"Autopilot cycle {cycle_id} kelly={sized.get('bet_pct')}",
                    wash_override_phrase=None,  # never override from autopilot
                    live_confirmed=live_armed,
                )
                execution = {
                    "side": "buy",
                    "symbol": symbol,
                    "order_id": (result.get("order") or {}).get("id"),
                    "fill": result.get("fill"),
                    "sizing": sized,
                    "notional": notional,
                }
                status = "executed"
                await log(f"Executed BUY {symbol} ${notional:.2f}", "execute")
            else:
                # Sell matching open paper position
                pos_rows = await PaperPositionStore(db).list_positions("open")
                match = next(
                    (p for p in pos_rows if str(p["ticker"]).upper() == symbol),
                    None,
                )
                if not match:
                    raise CapitalGateError("position", f"No open position for {symbol}")
                shares = float(consensus.get("shares") or match["shares"])
                result = await executor.sell(
                    position_id=match["id"],
                    shares=shares,
                    price=float(focus["price"]) if focus.get("price") else None,
                    notes=f"Autopilot cycle {cycle_id}",
                )
                execution = {
                    "side": "sell",
                    "symbol": symbol,
                    "realized_gain": result.get("realized_gain"),
                    "order_id": (result.get("order") or {}).get("id"),
                }
                status = "executed"
                await log(
                    f"Executed SELL {symbol} realized={result.get('realized_gain')}",
                    "execute",
                )
        except CapitalGateError as exc:
            status = "blocked"
            execution = {"error": exc.message, "code": exc.code}
            await log(f"Blocked by capital/law gate: {exc.message}", "execute")
        except Exception as exc:
            status = "error"
            execution = {"error": str(exc)}
            await log(f"Execution error: {exc}", "execute")
    else:
        status = "held" if consensus.get("action") == "hold" else "rejected"

    await store.record_decision(
        cycle_id=cycle_id,
        action=str(consensus.get("action") or "none"),
        status=status,
        symbol=consensus.get("symbol") or focus.get("ticker"),
        proposal=proposal,
        votes=votes,
        consensus=consensus,
        execution=execution,
        notes="; ".join(consensus.get("reasons") or []),
    )
    await store.mark_cycle(error=None if status != "error" else str((execution or {}).get("error")))
    return {
        "cycle_id": cycle_id,
        "status": status,
        "focus": focus.get("ticker"),
        "consensus": consensus,
        "votes": votes,
        "execution": execution,
        "context_summary": {
            "buying_power": context.get("buying_power"),
            "candidates": [c.get("ticker") for c in candidates[:5]],
            "watched": [w.get("ticker") for w in watched[:5]],
        },
    }
