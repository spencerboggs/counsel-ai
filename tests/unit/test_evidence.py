"""Evidence store and universe tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data.universe_us import get_universe, load_us_equity_tickers
from backend.evidence.models import EvidenceItem
from backend.evidence.store import EvidenceStore
from backend.storage.database import Database


def test_universe_loads_unique_tickers():
    tickers = load_us_equity_tickers()
    assert len(tickers) >= 50
    assert len(tickers) == len(set(tickers))
    assert get_universe(limit=10) == list(tickers[:10])


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "ev.db")
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_evidence_round_trip(db: Database):
    store = EvidenceStore(db)
    item = EvidenceItem(
        id="EV-TEST-0001",
        ticker="MSFT",
        claim="Price observed",
        source_name="Yahoo Finance (yfinance)",
        source_type="secondary",
        retrieved_at="2026-09-20T00:00:00Z",
        data_points={"price": 100.0},
        reliability=0.85,
        research_run_id="dr-abc",
    )
    await store.save_many([item])
    rows = await store.list_for_run("dr-abc", "MSFT")
    assert len(rows) == 1
    assert rows[0].data_points["price"] == 100.0
    assert rows[0].claim == "Price observed"
