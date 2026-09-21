"""LLM response cache."""

from pathlib import Path

import pytest

from backend.storage.database import Database
from backend.storage.llm_cache import LlmCache, fingerprint


@pytest.fixture
async def cache(tmp_path: Path):
    db = Database(tmp_path / "cache.db")
    await db.connect()
    await db.migrate()
    yield LlmCache(db)
    await db.close()


@pytest.mark.asyncio
async def test_cache_round_trip(cache: LlmCache):
    key = fingerprint("research", "fake", "SOFI", {"claims": ["price is 12"]})
    assert await cache.get(key) is None
    await cache.put(key, {"summary": "cached"}, kind="research", ticker="SOFI", model="fake")
    hit = await cache.get(key)
    assert hit is not None
    assert hit["summary"] == "cached"


def test_fingerprint_ignores_tiny_float_noise():
    left = fingerprint("research", "m", "SOFI", {"price": 12.00001})
    right = fingerprint("research", "m", "SOFI", {"price": 12.00002})
    assert left == right
