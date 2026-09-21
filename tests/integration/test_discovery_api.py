"""Discovery API integration tests with mocked market + Ollama."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import get_app_config, get_settings
from backend.main import app
from backend.providers.base import HistoryBar, LLMResponse, NewsItem, Quote
from backend.providers.ollama import OllamaProvider
from backend.research.discovery.pipeline import DiscoveryPipeline
from backend.storage.database import Database


class FakeMarket:
    name = "fake"

    async def get_quote(self, ticker: str) -> Quote:
        return Quote(ticker=ticker, price=12.0, currency="USD")

    async def get_history(self, ticker: str, period: str = "1y") -> list[HistoryBar]:
        start = date(2026, 1, 2)
        return [
            HistoryBar(
                date=(start + timedelta(days=i)).isoformat(),
                open=12,
                high=12.5,
                low=11.5,
                close=12 + i * 0.05,
                volume=2_000_000,
            )
            for i in range(60)
        ]

    async def get_financials(self, ticker: str) -> dict[str, Any]:
        return {
            "ticker": ticker,
            "metrics": {
                "returnOnEquity": 0.18,
                "profitMargins": 0.12,
                "revenueGrowth": 0.08,
                "debtToEquity": 45,
                "currentRatio": 1.6,
                "trailingPE": 22,
                "marketCap": 8e9,
                "averageVolume": 3_000_000,
                "sector": "Technology",
                "shortName": ticker,
                "beta": 1.05,
            },
        }

    async def get_news(self, ticker: str) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{ticker} announces product update",
                url=f"https://example.com/{ticker}",
                published_at="2026-09-01T00:00:00Z",
                source="Example Wire",
            )
        ]


class FakeOllama(OllamaProvider):
    def __init__(self) -> None:
        super().__init__(base_url="http://127.0.0.1:9")

    async def health(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    async def generate(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools=None,
        response_schema=None,
    ) -> LLMResponse:
        return LLMResponse(
            content=(
                '{"ticker":"AAPL","summary":"Evidence-backed overview.",'
                '"catalysts":["product"],"risks":["competition"],'
                '"evidence_ids":[],"confidence":0.4}'
            ),
            model=model,
            provider="ollama",
            prompt_tokens=10,
            completion_tokens=20,
        )


@pytest.fixture(autouse=True)
def clear_settings_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_COUNSEL_DB_PATH", str(tmp_path / "discovery.db"))
    get_settings.cache_clear()
    get_app_config.cache_clear()
    yield
    get_settings.cache_clear()
    get_app_config.cache_clear()


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = Database(tmp_path / "discovery.db")
    await db.connect()
    await db.migrate()
    app.state.db = db
    app.state.settings = get_settings()

    original_run = DiscoveryPipeline.run

    async def _run_with_fakes(self, run_id: str, params: dict[str, Any]) -> None:
        self.market = FakeMarket()
        self.ollama = FakeOllama()
        params = {
            **params,
            "screen_from_universe": 5,
            "candidate_pool_size": 3,
            "output_count": 2,
        }
        from backend.research.discovery import pipeline as pipe_mod

        monkeypatch.setattr(
            pipe_mod,
            "get_universe",
            lambda limit=None, sector=None, shuffle_seed=None: [
                "SOFI",
                "PLTR",
                "HOOD",
                "UPST",
                "RIVN",
            ][: (limit or 5)],
        )
        await original_run(self, run_id, params)

    monkeypatch.setattr(DiscoveryPipeline, "run", _run_with_fakes)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await db.close()


@pytest.mark.asyncio
async def test_discovery_run_end_to_end(client: AsyncClient):
    import asyncio

    created = await client.post(
        "/discovery/runs",
        json={
            "output_count": 2,
            "universe": "US Equities",
            "market_cap": "Any",
            "sector": "Any",
            "risk_tolerance": "Moderate",
            "time_horizon": "1-3 years",
            "investable_amount": 100,
            "min_whole_shares": 5,
            "candidate_pool_size": 5,
            "screen_from_universe": 10,
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]

    payload = None
    for _ in range(80):
        response = await client.get(f"/discovery/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"complete", "error"}:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail(f"run did not complete: {payload}")

    assert payload is not None
    assert payload["status"] == "complete", payload
    assert len(payload["candidates"]) >= 1
    ticker = payload["candidates"][0]["ticker"]
    assert isinstance(payload["candidates"][0]["score"], (int, float))
    # output_count was 2; UI may also list extra below-criteria rows
    assert payload["stats"]["output_count"] <= 2

    detail = await client.get(f"/discovery/runs/{run_id}/candidates/{ticker}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["ticker"] == ticker
    assert body["components"]
    assert body["evidence"]
    assert body["calculation"]
