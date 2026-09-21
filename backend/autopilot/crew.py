"""Multi-character Autopilot crew via Ollama."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.counsel.panel import resolve_role_model
from backend.providers.ollama import OllamaProvider
from backend.storage.llm_cache import LlmCache, fingerprint
from backend.storage.usage import UsageStore

ROOT = Path(__file__).resolve().parents[2]
PROMPT_DIR = ROOT / "prompts" / "autopilot"
PROMPT_VERSION = "autopilot-crew-v1"

ROLES = [
    "client",
    "fundamental_researcher",
    "factor_researcher",
    "macro_researcher",
    "social_scanner",
    "trader",
    "lawyer",
    "broker_accountant",
]

ROLE_HINTS = {
    "client": ("counsel", "discovery"),
    "fundamental_researcher": ("fundamental", "discovery", "extraction"),
    "factor_researcher": ("discovery", "extraction"),
    "macro_researcher": ("discovery", "counsel"),
    "social_scanner": ("discovery", "extraction"),
    "trader": ("counsel", "discovery"),
    "lawyer": ("skeptic", "counsel"),
    "broker_accountant": ("skeptic", "counsel"),
}

VOTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "role": {"type": "string"},
        "stance": {"type": "string"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "proposal": {"type": "object"},
    },
    "required": ["role", "stance", "confidence", "rationale"],
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


def _load_prompt(role: str) -> str:
    path = PROMPT_DIR / f"{role}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"You are {role}. Return JSON vote only."


class AutopilotCrew:
    def __init__(
        self,
        ollama: OllamaProvider,
        *,
        usage_store: UsageStore | None = None,
        cache: LlmCache | None = None,
        model_registry: list[Any] | None = None,
    ) -> None:
        self.ollama = ollama
        self.usage = usage_store
        self.cache = cache
        self.registry = model_registry or []

    async def deliberate(
        self,
        context: dict[str, Any],
        *,
        focus: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        installed = await self.ollama.list_models()
        if not installed:
            return [
                {
                    "role": "system",
                    "stance": "reject",
                    "confidence": 1.0,
                    "rationale": "No Ollama models available. Cannot deliberate.",
                    "risks": ["offline_models"],
                    "evidence_ids": [],
                }
            ]

        payload = {
            "context": context,
            "focus": focus,
            "rules": {
                "law_supreme": True,
                "no_wash_override": True,
                "allowlist_only": True,
                "settled_buying_power_only": True,
            },
        }
        user_blob = json.dumps(payload, default=str)[:12000]
        votes: list[dict[str, Any]] = []

        for role in ROLES:
            resolved = None
            # Prefer role hints via temporary registry search
            for hint in ROLE_HINTS.get(role, ("discovery",)):
                resolved = resolve_role_model(hint, list(self.registry), installed)
                if resolved:
                    break
            model_name = resolved[1] if resolved else installed[0]
            system = _load_prompt(role)
            cache_key = fingerprint(
                "autopilot",
                model_name,
                str((focus or {}).get("ticker") or "CREW"),
                {"role": role, "ver": PROMPT_VERSION, "blob": user_blob[:1500]},
            )
            parsed: dict[str, Any] | None = None
            if use_cache and self.cache is not None:
                hit = await self.cache.get(cache_key)
                if hit and isinstance(hit, dict):
                    parsed = hit
            if parsed is None:
                try:
                    response = await self.ollama.generate(
                        model=model_name,
                        prompt=user_blob,
                        system=system,
                        response_schema=VOTE_SCHEMA,
                    )
                    parsed = _extract_json(response.content) or {
                        "role": role,
                        "stance": "abstain",
                        "confidence": 0.2,
                        "rationale": "Unparseable model output.",
                        "risks": ["parse_error"],
                        "evidence_ids": [],
                    }
                    if self.usage is not None:
                        await self.usage.record_usage(
                            model_id=resolved[0] if resolved else "autopilot",
                            provider="ollama",
                            model_name=model_name,
                            prompt_tokens=response.prompt_tokens or 0,
                            completion_tokens=response.completion_tokens or 0,
                        )
                    if self.cache is not None:
                        await self.cache.put(
                            cache_key,
                            parsed,
                            kind="autopilot",
                            ticker=str((focus or {}).get("ticker") or "CREW"),
                            model=model_name,
                        )
                except Exception as exc:
                    parsed = {
                        "role": role,
                        "stance": "abstain",
                        "confidence": 0.0,
                        "rationale": f"Model error: {exc}",
                        "risks": ["model_error"],
                        "evidence_ids": [],
                    }
            parsed["role"] = role
            parsed["model"] = model_name
            votes.append(parsed)
        return votes
