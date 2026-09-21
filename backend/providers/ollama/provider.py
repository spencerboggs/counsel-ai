"""Ollama LLM provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from backend.providers.base import LLMResponse, QuotaInfo, UsageInfo


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")
        self._request_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._last_used_at: str | None = None

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, OSError, ValueError):
            return []

        models = payload.get("models") or []
        names: list[str] = []
        for item in models:
            name = item.get("name") or item.get("model")
            if name:
                names.append(name)
        return names

    async def generate(
        self,
        model: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
        if response_schema:
            body["format"] = response_schema

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=body)
            response.raise_for_status()
            data = response.json()

        message = data.get("message") or {}
        content = message.get("content") or ""
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")

        self._request_count += 1
        if isinstance(prompt_tokens, int):
            self._prompt_tokens += prompt_tokens
        if isinstance(completion_tokens, int):
            self._completion_tokens += completion_tokens

        self._last_used_at = datetime.now(timezone.utc).isoformat()

        return LLMResponse(
            content=content,
            model=model,
            provider=self.name,
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            completion_tokens=(
                completion_tokens if isinstance(completion_tokens, int) else None
            ),
            raw=data,
        )

    async def get_usage(self) -> UsageInfo:
        return UsageInfo(
            request_count=self._request_count,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            last_used_at=self._last_used_at,
        )

    async def get_quota(self) -> QuotaInfo:
        return QuotaInfo(
            known=False,
            note="Local Ollama has no remote quota",
        )
