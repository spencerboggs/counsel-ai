"""Local secrets file (gitignored). Never commit. Never echo secrets back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.config.settings import ROOT_DIR


SECRETS_PATH = ROOT_DIR / "backend" / "data" / "secrets.local.json"


class SecretsFile(BaseModel):
    ollama_base_url: str | None = None
    openrouter_api_key: str | None = None
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    # Alpaca - paper is free signup; live requires funded account + explicit enable
    alpaca_paper_key: str | None = None
    alpaca_paper_secret: str | None = None
    alpaca_live_key: str | None = None
    alpaca_live_secret: str | None = None
    trading_mode: str = Field(default="paper_local")  # paper_local | paper_alpaca | live_alpaca
    live_trading_confirmed: bool = False
    fred_api_key: str | None = None


def load_secrets() -> SecretsFile:
    if not SECRETS_PATH.exists():
        return SecretsFile()
    try:
        raw = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        return SecretsFile.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return SecretsFile()


def save_secrets(data: SecretsFile) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_PATH.write_text(
        data.model_dump_json(indent=2),
        encoding="utf-8",
    )


def secrets_status() -> dict[str, Any]:
    secrets = load_secrets()
    mode = secrets.trading_mode
    if mode == "live_alpaca" and not (
        secrets.live_trading_confirmed
        and secrets.alpaca_live_key
        and secrets.alpaca_live_secret
    ):
        mode = "paper_local"
    return {
        "trading_mode": mode,
        "live_trading_enabled": mode == "live_alpaca",
        "live_trading_confirmed": bool(secrets.live_trading_confirmed),
        "paper_is_default": mode.startswith("paper"),
        # Non-secret - safe to echo so the URL field can show the saved value.
        "ollama_base_url": secrets.ollama_base_url,
        "keys": {
            "ollama_base_url": bool(secrets.ollama_base_url),
            "openrouter_api_key": bool(secrets.openrouter_api_key),
            "groq_api_key": bool(secrets.groq_api_key),
            "gemini_api_key": bool(secrets.gemini_api_key),
            "alpaca_paper_key": bool(secrets.alpaca_paper_key),
            "alpaca_paper_secret": bool(secrets.alpaca_paper_secret),
            "alpaca_live_key": bool(secrets.alpaca_live_key),
            "alpaca_live_secret": bool(secrets.alpaca_live_secret),
            # Aggregate helpers (both halves present)
            "alpaca_paper": bool(
                secrets.alpaca_paper_key and secrets.alpaca_paper_secret
            ),
            "alpaca_live": bool(secrets.alpaca_live_key and secrets.alpaca_live_secret),
            "fred_api_key": bool(secrets.fred_api_key),
        },
        "notes": {
            "paper_local": "Built-in free paper ledger - no API key required",
            "paper_alpaca": "Optional free Alpaca paper keys from alpaca.markets (user-supplied)",
            "live_alpaca": "Requires your own Alpaca live keys + explicit confirmation. Never enabled by default.",
            "fred_api_key": "Optional FRED key for macro Autopilot context (api.stlouisfed.org)",
        },
    }
