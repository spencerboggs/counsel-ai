"""Health endpoint tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import get_app_config, get_settings
from backend.main import app
from backend.storage.database import Database


@pytest.fixture(autouse=True)
def clear_settings_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AI_COUNSEL_DB_PATH", str(db_path))
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
async def test_health_ok(client: AsyncClient, httpx_mock):
    payload = {"models": [{"name": "llama3.2:latest"}]}
    # health() and list_models() each hit /api/tags
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/tags", json=payload)
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/tags", json=payload)
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ollama"]["reachable"] is True
    assert data["ollama"]["model_count"] == 1
