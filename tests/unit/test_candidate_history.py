"""Candidate history store tests."""

from pathlib import Path

import pytest

from backend.storage.candidate_history import CandidateHistoryStore
from backend.storage.database import Database


@pytest.fixture
async def store(tmp_path: Path):
    db = Database(tmp_path / "hist.db")
    await db.connect()
    await db.migrate()
    yield CandidateHistoryStore(db)
    await db.close()


@pytest.mark.asyncio
async def test_record_export_and_known(store: CandidateHistoryStore):
    await store.record_many(
        "dr-1",
        [
            {"ticker": "SOFI", "score": 70.1, "signal": "Interesting", "price": 12.0},
            {"ticker": "WEAK", "score": 22.0, "signal": "Pass", "price": 4.0},
        ],
        output_limit=1,
    )
    known = await store.known_tickers()
    assert "SOFI" in known
    assert "WEAK" in known
    rows = await store.list_all()
    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["SOFI"]["in_output"] == 1
    assert by_ticker["WEAK"]["in_output"] == 0
    assert by_ticker["SOFI"]["seen_at"]
    csv_body = await store.export_csv()
    assert "SOFI" in csv_body
    assert "WEAK" in csv_body
    json_body = await store.export_json()
    assert "SOFI" in json_body
    await store.clear()
    assert await store.known_tickers() == set()
