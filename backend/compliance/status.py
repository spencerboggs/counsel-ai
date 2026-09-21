"""Alpaca.md checklist status reflected in the app."""

from __future__ import annotations

from typing import Any

from backend.compliance.market_hours import session_status
from backend.compliance.risk_gates import trading_config


# status: done | partial | todo
CHECKLIST: list[dict[str, Any]] = [
    {
        "section": 1,
        "title": "Account / buying power",
        "status": "done",
        "notes": (
            "Settled BP for paper_local; Alpaca account cash/BP/equity when "
            "paper_alpaca or live. Orders blocked when notional > BP."
        ),
    },
    {
        "section": 2,
        "title": "Orders",
        "status": "partial",
        "notes": (
            "Immutable trade_orders + client_order_id. Local/paper fills recorded "
            "immediately. Broker open-order streaming still light (wake polls open orders)."
        ),
    },
    {
        "section": 3,
        "title": "Fills / executions",
        "status": "partial",
        "notes": (
            "Every local fill stored separately with price/qty/fees. "
            "Broker multi-partial sync TBD for live Alpaca."
        ),
    },
    {
        "section": 4,
        "title": "Positions",
        "status": "done",
        "notes": (
            "Tax lots + paper_positions. Wake/startup reconcile compares local vs "
            "Alpaca and can halt trading on mismatch."
        ),
    },
    {
        "section": 5,
        "title": "Market hours",
        "status": "done",
        "notes": (
            "America/New_York RTH gate + curated NYSE holidays/early closes. "
            "Extended hours off by default. CapitalGate blocks market orders when closed."
        ),
    },
    {
        "section": 6,
        "title": "Order execution",
        "status": "done",
        "notes": (
            "Market orders only; max order notional; duplicate open-order block; "
            "abnormal price vs quote rejected. Slippage assumed in paper marks."
        ),
    },
    {
        "section": 7,
        "title": "Rate limits / API reliability",
        "status": "partial",
        "notes": "Yahoo throttle exists; Alpaca submit is single-shot (no blind retry).",
    },
    {
        "section": 8,
        "title": "Real-time data",
        "status": "partial",
        "notes": (
            "REST quotes (Yahoo, free) with max-age gate - no paid websocket required. "
            "Stale quotes cannot trade."
        ),
    },
    {
        "section": 9,
        "title": "Strategy / risk",
        "status": "done",
        "notes": (
            "Capital gate, wash block, Autopilot lawyer/broker veto, max positions, "
            "half-Kelly sizing capped at ~6% per bet, max trades/day, daily loss, kill switch."
        ),
    },
    {
        "section": 10,
        "title": "Day trading",
        "status": "partial",
        "notes": (
            "Daytrade research lane; Alpaca PDT/account flags when present. "
            "No forced PDT math beyond broker restrictions."
        ),
    },
    {
        "section": 11,
        "title": "Settlement",
        "status": "done",
        "notes": "T+1 settlement_events; buying power uses settled cash only.",
    },
    {
        "section": 12,
        "title": "Tax / trade ledger",
        "status": "done",
        "notes": "Permanent orders/fills/lots/dispositions/audit.",
    },
    {
        "section": 13,
        "title": "Tax lots",
        "status": "done",
        "notes": "FIFO lots with adjusted basis support.",
    },
    {
        "section": 14,
        "title": "Wash sales",
        "status": "done",
        "notes": (
            "30-day hard block; typed override on Trade page only. "
            "Autopilot never wash-overrides."
        ),
    },
    {
        "section": 15,
        "title": "Tax documents",
        "status": "todo",
        "notes": (
            "No 1099 download (broker portal). We never generate substitute 1099-B. "
            "Not required to run paper Autopilot."
        ),
    },
    {
        "section": 16,
        "title": "Dividends / corporate actions",
        "status": "todo",
        "notes": (
            "Not implemented. Positions may need manual reconcile after corp actions. "
            "Mismatch halt protects until resolved."
        ),
    },
    {
        "section": 17,
        "title": "Short selling",
        "status": "done",
        "notes": "Long-only; shorts not supported.",
    },
    {
        "section": 18,
        "title": "Options",
        "status": "done",
        "notes": "Options orders not supported.",
    },
    {
        "section": 19,
        "title": "Logging / audit trail",
        "status": "done",
        "notes": "audit_log append-only; soft-flag purge only; Autopilot decision log.",
    },
    {
        "section": 20,
        "title": "Reconciliation",
        "status": "done",
        "notes": (
            "Startup wake + Autopilot start wake + per-cycle broker/local compare; "
            "halt on mismatch before new trades."
        ),
    },
    {
        "section": 21,
        "title": "Crash recovery",
        "status": "done",
        "notes": (
            "SQLite ledger is source for restart; Autopilot wake on resume; "
            "no in-memory-only positions."
        ),
    },
    {
        "section": 22,
        "title": "Paper vs live",
        "status": "done",
        "notes": (
            "Separate keys/modes; live requires Settings confirm + Autopilot "
            "ARM LIVE AUTOPILOT. Default is free paper_local."
        ),
    },
    {
        "section": 23,
        "title": "Secrets",
        "status": "done",
        "notes": (
            "Local secrets file; optional free FRED key; paid LLM keys optional. "
            "Core Autopilot path works with Ollama + Yahoo + public SEC."
        ),
    },
    {
        "section": 24,
        "title": "Shutdown / kill switch",
        "status": "done",
        "notes": (
            "Settings/API kill switch blocks NEW orders and stops Autopilot. "
            "Does not auto-liquidate or cancel broker orders."
        ),
    },
    {
        "section": 25,
        "title": "Monitoring",
        "status": "done",
        "notes": (
            "Capital strip, Autopilot status, market session, kill switch, "
            "tax ledger, paper book, decision votes."
        ),
    },
    {
        "section": 26,
        "title": "Backtesting vs live",
        "status": "partial",
        "notes": (
            "In-sample historical probe on bars (free). Full OOS labs TBD - "
            "not required for paper execution readiness."
        ),
    },
    {
        "section": 27,
        "title": "Data / signal safety",
        "status": "done",
        "notes": (
            "Quote failures fail closed; stale quote age gate; abnormal price reject; "
            "ToS-safe SEC/FRED/Yahoo only."
        ),
    },
    {
        "section": 28,
        "title": "Configuration",
        "status": "done",
        "notes": (
            "config.yaml trading risk limits + Autopilot caps + secrets modes. "
            "All defaults are free-tier."
        ),
    },
    {
        "section": 29,
        "title": "Database",
        "status": "done",
        "notes": "Persistent SQLite ledger with unique IDs + autopilot_state/decisions.",
    },
    {
        "section": 30,
        "title": "Accounting principle",
        "status": "done",
        "notes": (
            "Broker = execution truth when used; local = tax/audit mirror. "
            "Mismatch -> STOP -> reconcile -> resume."
        ),
    },
    {
        "section": 31,
        "title": "Autopilot law-enforced consensus",
        "status": "done",
        "notes": (
            "Lawyer + broker/accountant hard veto; Python consensus; "
            "trades only via TradeExecutor CapitalGate/wash/ledger."
        ),
    },
    {
        "section": 32,
        "title": "Autopilot live arm",
        "status": "done",
        "notes": (
            "Live mode requires Settings trading_mode=live_alpaca plus "
            "explicit Autopilot arm confirm; capital from Alpaca BP."
        ),
    },
    {
        "section": 33,
        "title": "Free-tier default path",
        "status": "done",
        "notes": (
            "paper_local + Ollama + Yahoo + public SEC work with $0. "
            "Alpaca paper keys and FRED are optional free add-ons. "
            "Paid keys only if you add them in Settings."
        ),
    },
]


def compliance_checklist() -> dict[str, Any]:
    done = sum(1 for i in CHECKLIST if i["status"] == "done")
    partial = sum(1 for i in CHECKLIST if i["status"] == "partial")
    todo = sum(1 for i in CHECKLIST if i["status"] == "todo")
    tcfg = trading_config()
    session = session_status(allow_extended_hours=tcfg["allow_extended_hours"])
    return {
        "items": CHECKLIST,
        "counts": {"done": done, "partial": partial, "todo": todo, "total": len(CHECKLIST)},
        "market_session": session,
        "trading_config": tcfg,
        "readiness": {
            "paper_ready": todo <= 2,
            "live_requires": [
                "Settings live mode + keys",
                "Autopilot ARM LIVE AUTOPILOT",
                "Regular-session open (or explicit extended-hours config)",
                "Kill switch off",
            ],
            "deferred_ok_for_paper": [
                "1099 document download",
                "Corporate actions automation",
                "Paid websocket feeds",
                "Full broker order-stream sync",
            ],
        },
        "disclaimer": (
            "Checklist tracks engineering readiness against alpaca.md. "
            "Not legal advice. Taxpayers retain IRS reporting obligations. "
            "Core path is free unless you add paid API keys."
        ),
    }
