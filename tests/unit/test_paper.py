"""Paper position store tests."""

from pathlib import Path

import pytest

from backend.portfolio.store import PaperPositionStore
from backend.storage.database import Database


@pytest.fixture
async def store(tmp_path: Path):
    db = Database(tmp_path / "paper.db")
    await db.connect()
    await db.migrate()
    yield PaperPositionStore(db)
    await db.close()


@pytest.mark.asyncio
async def test_open_and_close_paper_position(store: PaperPositionStore):
    opened = await store.open_position("SOFI", 8, 12.5, source_run_id="dr-1")
    assert opened["status"] == "open"
    listed = await store.list_positions("open")
    assert len(listed) == 1
    closed = await store.close_position(opened["id"])
    assert closed is not None
    assert closed["status"] == "closed"
    assert await store.list_positions("open") == []
