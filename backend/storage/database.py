"""SQLite persistence for AI Counsel."""

from __future__ import annotations

from pathlib import Path

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS models_usage (
    model_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    status TEXT NOT NULL,
    input_json TEXT,
    result_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    claim TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT,
    source_type TEXT NOT NULL,
    published_at TEXT,
    retrieved_at TEXT NOT NULL,
    supporting_text TEXT,
    data_points_json TEXT,
    reliability REAL,
    freshness REAL,
    directness REAL,
    corroboration REAL,
    research_run_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_evidence_ticker ON evidence(ticker);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status);

CREATE TABLE IF NOT EXISTS paper_positions (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    shares REAL NOT NULL,
    cost_basis REAL NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    source_run_id TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status);

CREATE TABLE IF NOT EXISTS candidate_sightings (
    ticker TEXT NOT NULL,
    research_run_id TEXT NOT NULL,
    score REAL,
    signal TEXT,
    price REAL,
    shares_buyable INTEGER,
    panel_score REAL,
    seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, research_run_id)
);

CREATE INDEX IF NOT EXISTS idx_candidate_sightings_ticker ON candidate_sightings(ticker);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    research_run_id TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    stage TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(research_run_id);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    ticker TEXT,
    model TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_llm_cache_ticker ON llm_cache(ticker);

CREATE TABLE IF NOT EXISTS trade_orders (
    id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL UNIQUE,
    broker_order_id TEXT,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'market',
    time_in_force TEXT NOT NULL DEFAULT 'day',
    limit_price REAL,
    stop_price REAL,
    status TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_run_id TEXT,
    notes TEXT,
    raw_json TEXT,
    soft_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_trade_orders_symbol ON trade_orders(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_orders_status ON trade_orders(status);

CREATE TABLE IF NOT EXISTS trade_fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    broker_fill_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    executed_at TEXT NOT NULL,
    raw_json TEXT,
    soft_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES trade_orders(id)
);

CREATE INDEX IF NOT EXISTS idx_trade_fills_order ON trade_fills(order_id);
CREATE INDEX IF NOT EXISTS idx_trade_fills_symbol ON trade_fills(symbol);

CREATE TABLE IF NOT EXISTS tax_lots (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    qty_open REAL NOT NULL,
    qty_original REAL NOT NULL,
    cost_basis_per_share REAL NOT NULL,
    adjusted_basis_per_share REAL,
    acquired_at TEXT NOT NULL,
    source_fill_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    wash_adjusted INTEGER NOT NULL DEFAULT 0,
    soft_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_fill_id) REFERENCES trade_fills(id)
);

CREATE INDEX IF NOT EXISTS idx_tax_lots_symbol ON tax_lots(symbol);
CREATE INDEX IF NOT EXISTS idx_tax_lots_status ON tax_lots(status);

CREATE TABLE IF NOT EXISTS dispositions (
    id TEXT PRIMARY KEY,
    sell_fill_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty REAL NOT NULL,
    proceeds REAL NOT NULL,
    cost REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    realized_gain REAL NOT NULL,
    holding_days INTEGER NOT NULL,
    acquired_at TEXT NOT NULL,
    disposed_at TEXT NOT NULL,
    wash_disallowed_loss REAL NOT NULL DEFAULT 0,
    wash_replacement_lot_id TEXT,
    soft_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (sell_fill_id) REFERENCES trade_fills(id),
    FOREIGN KEY (lot_id) REFERENCES tax_lots(id)
);

CREATE INDEX IF NOT EXISTS idx_dispositions_symbol ON dispositions(symbol);
CREATE INDEX IF NOT EXISTS idx_dispositions_disposed ON dispositions(disposed_at);

CREATE TABLE IF NOT EXISTS wash_sale_events (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    disposition_id TEXT,
    loss_amount REAL NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    event_type TEXT NOT NULL,
    related_fill_id TEXT,
    related_lot_id TEXT,
    disallowed_loss REAL NOT NULL DEFAULT 0,
    basis_adjustment REAL NOT NULL DEFAULT 0,
    override_confirmed INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    soft_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_wash_symbol ON wash_sale_events(symbol);
CREATE INDEX IF NOT EXISTS idx_wash_window ON wash_sale_events(window_end);

CREATE TABLE IF NOT EXISTS settlement_events (
    id TEXT PRIMARY KEY,
    fill_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    settle_date TEXT NOT NULL,
    cash_delta REAL NOT NULL,
    settled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    soft_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (fill_id) REFERENCES trade_fills(id)
);

CREATE INDEX IF NOT EXISTS idx_settlement_settle ON settlement_events(settle_date);
CREATE INDEX IF NOT EXISTS idx_settlement_fill ON settlement_events(fill_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    payload_json TEXT,
    actor TEXT NOT NULL DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

CREATE TABLE IF NOT EXISTS deletion_requests (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    confirmation_phrase TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS paper_cash_ledger (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    fill_id TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS compliance_flags (
    key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS autopilot_state (
    id TEXT PRIMARY KEY CHECK (id = 'singleton'),
    running INTEGER NOT NULL DEFAULT 0,
    stopped_at TEXT,
    started_at TEXT,
    asleep_since TEXT,
    last_cycle_at TEXT,
    last_wake_json TEXT,
    config_json TEXT,
    last_error TEXT,
    cycle_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autopilot_decisions (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    symbol TEXT,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    proposal_json TEXT,
    votes_json TEXT,
    consensus_json TEXT,
    execution_json TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_autopilot_decisions_created
    ON autopilot_decisions(created_at DESC);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL lets Stop/poll reads proceed while discovery is writing progress.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def migrate(self) -> None:
        await self.conn.executescript(SCHEMA)
        # Additive columns for databases created before the found-stocks archive.
        existing = await self.conn.execute("PRAGMA table_info(candidate_sightings)")
        columns = {row["name"] for row in await existing.fetchall()}
        additions = {
            "name": "TEXT",
            "sector": "TEXT",
            "confidence": "REAL",
            "rank": "INTEGER",
            "in_output": "INTEGER NOT NULL DEFAULT 1",
            "lane": "TEXT NOT NULL DEFAULT 'invest'",
            "metrics_json": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                await self.conn.execute(
                    f"ALTER TABLE candidate_sightings ADD COLUMN {name} {ddl}"
                )
        # One row per (lane, ticker): keep newest seen_at, drop the rest.
        await self.conn.execute(
            """
            DELETE FROM candidate_sightings
            WHERE rowid IN (
                SELECT c.rowid
                FROM candidate_sightings c
                WHERE EXISTS (
                    SELECT 1
                    FROM candidate_sightings d
                    WHERE COALESCE(d.lane, 'invest') = COALESCE(c.lane, 'invest')
                      AND UPPER(d.ticker) = UPPER(c.ticker)
                      AND (
                        COALESCE(d.seen_at, '') > COALESCE(c.seen_at, '')
                        OR (
                          COALESCE(d.seen_at, '') = COALESCE(c.seen_at, '')
                          AND d.rowid > c.rowid
                        )
                      )
                )
            )
            """
        )
        await self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_sightings_lane_ticker
            ON candidate_sightings(lane, ticker)
            """
        )
        # Seed paper cash once (local simulated account).
        cursor = await self.conn.execute("SELECT COUNT(*) AS n FROM paper_cash_ledger")
        row = await cursor.fetchone()
        if int(row["n"] if row else 0) == 0:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            await self.conn.execute(
                """
                INSERT INTO paper_cash_ledger (id, created_at, kind, amount, balance_after, notes)
                VALUES (?, ?, 'seed', 10000.0, 10000.0, 'Initial paper cash')
                """,
                (f"cash-seed-{now[:10]}", now),
            )
        await self.conn.commit()
