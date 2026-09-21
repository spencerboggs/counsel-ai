"""Config endpoint tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import get_app_config, get_settings
from backend.main import app
from backend.storage.database import Database


@pytest.fixture(autouse=True)
def clear_settings_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_COUNSEL_DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    get_app_config.cache_clear()
    yield
    get_settings.cache_clear()
    get_app_config.cache_clear()


@pytest.fixture
async def client(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    await db.migrate()
    app.state.db = db
    app.state.settings = get_settings()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await db.close()


@pytest.mark.asyncio
async def test_config_sanitized(client: AsyncClient):
    response = await client.get("/config")
    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    assert data["providers"]["ollama"]["enabled"] is True
    assert data["providers"]["openrouter"]["enabled"] is False
    assert isinstance(data["models"], list)
