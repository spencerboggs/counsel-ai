"""Ollama provider unit tests."""

from __future__ import annotations

import pytest

from backend.providers.ollama import OllamaProvider


@pytest.mark.asyncio
async def test_list_models(httpx_mock):
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/tags",
        json={"models": [{"name": "mistral:latest"}, {"name": "llama3.2:latest"}]},
    )
    provider = OllamaProvider()
    models = await provider.list_models()
    assert models == ["mistral:latest", "llama3.2:latest"]


@pytest.mark.asyncio
async def test_health_unreachable(httpx_mock):
    httpx_mock.add_exception(OSError("connection refused"))
    provider = OllamaProvider()
    assert await provider.health() is False


@pytest.mark.asyncio
async def test_quota_unknown():
    provider = OllamaProvider()
    quota = await provider.get_quota()
    assert quota.known is False
