"""Usage store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.storage.database import Database
from backend.storage.usage import UsageStore


@pytest.fixture
async def usage_store(tmp_path: Path):
    db = Database(tmp_path / "usage.db")
    await db.connect()
    await db.migrate()
    store = UsageStore(db)
    yield store
    await db.close()


@pytest.mark.asyncio
async def test_record_and_list_usage(usage_store: UsageStore):
    await usage_store.record_usage(
        "local-fast",
        "ollama",
        "llama3.2:latest",
        prompt_tokens=10,
        completion_tokens=5,
    )
    await usage_store.record_usage(
        "local-fast",
        "ollama",
        "llama3.2:latest",
        prompt_tokens=3,
        completion_tokens=2,
    )
    items = await usage_store.list_usage()
    assert len(items) == 1
    assert items[0]["request_count"] == 2
    assert items[0]["prompt_tokens"] == 13
    assert items[0]["completion_tokens"] == 7


@pytest.mark.asyncio
async def test_get_usage_missing(usage_store: UsageStore):
    assert await usage_store.get_usage("missing") is None
