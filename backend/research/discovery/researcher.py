"""Single Ollama discovery researcher."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.evidence.models import EvidenceItem
from backend.providers.ollama import OllamaProvider
from backend.storage.llm_cache import LlmCache, fingerprint
from backend.storage.usage import UsageStore


ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = ROOT / "prompts" / "discovery" / "researcher.md"

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "summary": {"type": "string"},
        "catalysts": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["ticker", "summary", "evidence_ids", "confidence"],
}


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "Cite only provided evidence IDs. Return JSON."


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class DiscoveryResearcher:
    def __init__(
        self,
        ollama: OllamaProvider,
        *,
        model_name: str,
        model_id: str = "local-fast",
        usage_store: UsageStore | None = None,
        cache: LlmCache | None = None,
    ) -> None:
        self.ollama = ollama
        self.model_name = model_name
        self.model_id = model_id
        self.usage_store = usage_store
        self.cache = cache
        self.prompt = _load_prompt()

    async def research(
        self,
        ticker: str,
        evidence: list[EvidenceItem],
        metrics: dict[str, Any],
        *,
        use_cache: bool = True,
    ) -> dict[str, Any] | None:
        allowed_ids = {e.id for e in evidence}
        evidence_payload = [
            {
                "id": e.id,
                "claim": e.claim,
                "source_name": e.source_name,
                "source_type": e.source_type,
                "data_points": e.data_points,
                "reliability": e.reliability,
            }
            for e in evidence
        ]
        cache_payload = {
            "claims": [e.claim for e in evidence],
            "metrics": {
                key: metrics.get(key)
                for key in (
                    "price",
                    "market_cap",
                    "roe",
                    "profit_margin",
                    "revenue_growth",
                    "pe",
                    "momentum_20d",
                    "volatility",
                )
            },
        }
        cache_key = (
            fingerprint("research", self.model_name, ticker, cache_payload)
            if self.cache is not None
            else None
        )
        if use_cache and cache_key and self.cache is not None:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                parsed = dict(cached)
                parsed["cached"] = True
                parsed["ticker"] = ticker.upper()
                return parsed
        user_content = json.dumps(
            {
                "ticker": ticker,
                "metrics_keys": list(metrics.keys()),
                "evidence": evidence_payload,
            },
            default=str,
        )
        messages = [
            {"role": "system", "content": self.prompt},
            {
                "role": "user",
                "content": (
                    "Research this candidate using ONLY the evidence list. "
                    f"Input JSON:\n{user_content}"
                ),
            },
        ]
        try:
            response = await self.ollama.generate(
                self.model_name,
                messages,
                response_schema=RESPONSE_SCHEMA,
            )
        except Exception:
            return None

        if self.usage_store is not None:
            await self.usage_store.record_usage(
                self.model_id,
                "ollama",
                self.model_name,
                prompt_tokens=response.prompt_tokens or 0,
                completion_tokens=response.completion_tokens or 0,
            )

        parsed = _extract_json(response.content)
        if not parsed:
            return None

        cited = [eid for eid in parsed.get("evidence_ids") or [] if eid in allowed_ids]
        parsed["evidence_ids"] = cited
        parsed["ticker"] = ticker.upper()
        parsed["summary"] = str(parsed.get("summary") or "")
        try:
            parsed["confidence"] = float(parsed.get("confidence") or 0)
        except (TypeError, ValueError):
            parsed["confidence"] = 0.0
        if cache_key and self.cache is not None:
            await self.cache.put(
                cache_key,
                parsed,
                kind="research",
                ticker=ticker,
                model=self.model_name,
            )
        return parsed
