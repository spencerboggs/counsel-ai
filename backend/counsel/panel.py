"""Multi-role counsel panel. Python aggregates scores; models do not set the final number."""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from backend.evidence.models import EvidenceItem
from backend.providers.ollama import OllamaProvider
from backend.scoring.discovery import DEFAULT_WEIGHTS
from backend.storage.llm_cache import LlmCache, fingerprint
from backend.storage.usage import UsageStore


ROOT = Path(__file__).resolve().parents[2]
PROMPTS = {
    "fundamental": ROOT / "prompts" / "system" / "fundamental.md",
    "skeptic": ROOT / "prompts" / "system" / "skeptic.md",
    "counsel": ROOT / "prompts" / "system" / "counsel.md",
}

# Bump when prompts change so cached counsel responses are not reused.
PROMPT_CACHE_VERSION = "panel-v2"

DIMENSIONS = list(DEFAULT_WEIGHTS.keys())

ROLE_REGISTRY_HINTS = {
    "fundamental": ("fundamental", "discovery", "extraction"),
    "discovery": ("discovery", "extraction", "fundamental"),
    "extraction": ("extraction", "discovery"),
    "skeptic": ("skeptic",),
    "counsel": ("counsel",),
}


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def normalize_dimension_scores(raw: dict[str, Any]) -> dict[str, float]:
    """Clamp to 0-100. If the model used a 0-1 scale, rescale to 0-100."""
    parsed: dict[str, float] = {}
    for key, value in (raw or {}).items():
        try:
            parsed[key] = float(value)
        except (TypeError, ValueError):
            continue
    if not parsed:
        return {}
    values = list(parsed.values())
    # Typical bug: model returns 0.0-1.0 while UI expects 0-100.
    if max(values) <= 1.0 and min(values) >= 0.0:
        parsed = {k: v * 100.0 for k, v in parsed.items()}
    return {k: max(0.0, min(100.0, v)) for k, v in parsed.items()}


def resolve_role_model(
    role: str,
    registry: list[Any],
    installed: list[str],
) -> tuple[str, str] | None:
    """Return (registry_id, ollama model name) for a role.

    Falls back to any enabled Ollama model so a single installed model can
    still play every role with a different prompt.
    """
    if not installed:
        return None
    hints = ROLE_REGISTRY_HINTS.get(role, ())
    for entry in registry:
        if not getattr(entry, "enabled", True):
            continue
        if getattr(entry, "provider", "") != "ollama":
            continue
        roles = set(getattr(entry, "roles", []) or [])
        if not roles.intersection(hints):
            continue
        model = getattr(entry, "model", "auto")
        resolved = installed[0] if model == "auto" else (
            model if model in installed else installed[0]
        )
        return entry.id, resolved
    return "local-fast", installed[0]


def weighted_from_dimensions(
    dimension_scores: dict[str, float],
    weights: dict[str, float],
) -> float | None:
    used = 0.0
    total_w = 0.0
    for name, weight in weights.items():
        if name not in dimension_scores:
            continue
        used += float(dimension_scores[name]) * weight
        total_w += weight
    if total_w <= 0:
        return None
    return round(max(0.0, min(100.0, used / total_w)), 1)


def aggregate_panel(
    findings: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Robust panel score: median of role scores (one harsh role cannot nuke the panel)."""
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    total = sum(weights.values()) or 1.0
    weights = {k: v / total for k, v in weights.items()}

    agent_scores: list[dict[str, Any]] = []
    numeric: list[float] = []
    for finding in findings:
        dims = normalize_dimension_scores(finding.get("dimension_scores") or {})
        dims = {k: v for k, v in dims.items() if k in weights}
        score = weighted_from_dimensions(dims, weights)
        agent_scores.append(
            {
                "role": finding.get("role"),
                "model": finding.get("model"),
                "score": score,
                "confidence": finding.get("confidence"),
                "summary": finding.get("summary"),
                "risks": finding.get("risks") or [],
                "evidence_ids": finding.get("evidence_ids") or [],
                "dimension_scores": dims,
            }
        )
        if score is not None:
            numeric.append(score)

    if not numeric:
        panel_score = None
        spread = 0.0
    elif len(numeric) == 1:
        panel_score = round(numeric[0], 1)
        spread = 0.0
    else:
        panel_score = round(float(statistics.median(numeric)), 1)
        spread = round(max(numeric) - min(numeric), 1)
    return {
        "panel_score": panel_score,
        "panel_spread": spread,
        "agents": agent_scores,
    }


class CounselPanel:
    def __init__(
        self,
        ollama: OllamaProvider,
        *,
        usage_store: UsageStore | None = None,
        cache: LlmCache | None = None,
    ) -> None:
        self.ollama = ollama
        self.usage_store = usage_store
        self.cache = cache

    async def review(
        self,
        ticker: str,
        evidence: list[EvidenceItem],
        metrics: dict[str, Any],
        *,
        roles: list[tuple[str, str, str]],
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """roles: list of (role, registry_id, model_name)."""
        allowed = {item.id for item in evidence}
        payload = json.dumps(
            {
                "ticker": ticker,
                "metrics": {
                    k: metrics.get(k)
                    for k in (
                        "price",
                        "shares_buyable",
                        "investable_amount",
                        "market_cap",
                        "roe",
                        "profit_margin",
                        "revenue_growth",
                        "pe",
                        "momentum_20d",
                        "volatility",
                        "news_count",
                    )
                },
                "evidence": [
                    {
                        "id": item.id,
                        "claim": item.claim,
                        "source_type": item.source_type,
                        "data_points": item.data_points,
                    }
                    for item in evidence
                ],
            },
            default=str,
        )
        findings: list[dict[str, Any]] = []
        for role, registry_id, model_name in roles:
            prompt_path = PROMPTS.get(role)
            prompt = (
                prompt_path.read_text(encoding="utf-8")
                if prompt_path and prompt_path.exists()
                else f"You are the {role}. Cite evidence IDs only. Return JSON."
            )
            cache_payload = {
                "role": role,
                "prompt_version": PROMPT_CACHE_VERSION,
                "claims": [item.claim for item in evidence],
                "metrics": {
                    k: metrics.get(k)
                    for k in (
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
                fingerprint(
                    f"counsel:{role}:{PROMPT_CACHE_VERSION}",
                    model_name,
                    ticker,
                    cache_payload,
                )
                if self.cache is not None
                else None
            )
            if use_cache and cache_key and self.cache is not None:
                cached = await self.cache.get(cache_key)
                if cached is not None:
                    finding = dict(cached)
                    finding["cached"] = True
                    findings.append(finding)
                    continue
            try:
                response = await self.ollama.generate(
                    model_name,
                    [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": (
                                f"Review {ticker}. Score every dimension from 0 to 100 "
                                f"(not 0 to 1). Input:\n{payload}"
                            ),
                        },
                    ],
                )
            except Exception:
                continue
            if self.usage_store is not None:
                await self.usage_store.record_usage(
                    registry_id,
                    "ollama",
                    model_name,
                    prompt_tokens=response.prompt_tokens or 0,
                    completion_tokens=response.completion_tokens or 0,
                )
            parsed = _extract_json(response.content)
            if not parsed:
                continue
            cited = [eid for eid in parsed.get("evidence_ids") or [] if eid in allowed]
            try:
                confidence = float(parsed.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            # Confidence is 0-1; if model returned 0-100, normalize.
            if confidence > 1.0:
                confidence = confidence / 100.0
            finding = {
                "role": role,
                "model": model_name,
                "registry_id": registry_id,
                "summary": str(parsed.get("summary") or ""),
                "dimension_scores": normalize_dimension_scores(
                    parsed.get("dimension_scores") or {}
                ),
                "risks": parsed.get("risks") or [],
                "evidence_ids": cited,
                "confidence": max(0.0, min(1.0, confidence)),
            }
            if cache_key and self.cache is not None:
                await self.cache.put(
                    cache_key,
                    finding,
                    kind=f"counsel:{role}",
                    ticker=ticker,
                    model=model_name,
                )
            findings.append(finding)
        return findings
