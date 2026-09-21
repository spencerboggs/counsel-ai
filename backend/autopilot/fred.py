"""Optional FRED macro snapshot (abstain if no API key)."""

from __future__ import annotations

from typing import Any

import httpx

from backend.config.secrets import load_secrets

# Small, high-signal series for regime context.
SERIES = {
    "DGS10": "10Y Treasury",
    "T10Y2Y": "10Y-2Y spread",
    "UNRATE": "Unemployment",
    "CPIAUCSL": "CPI",
    "FEDFUNDS": "Fed funds",
}


async def fred_snapshot() -> dict[str, Any]:
    secrets = load_secrets()
    key = getattr(secrets, "fred_api_key", None) or None
    # Also allow env-style field if added later via secrets dict
    if not key:
        try:
            raw = secrets.model_dump()
            key = raw.get("fred_api_key")
        except Exception:
            key = None
    if not key:
        return {
            "available": False,
            "note": "FRED API key not configured. Macro researcher should abstain.",
            "series": {},
        }

    out: dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for series_id, label in SERIES.items():
                response = await client.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": key,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": 1,
                    },
                )
                if response.status_code >= 400:
                    continue
                obs = (response.json().get("observations") or [])
                if not obs:
                    continue
                out[series_id] = {
                    "label": label,
                    "date": obs[0].get("date"),
                    "value": obs[0].get("value"),
                }
    except Exception as exc:
        return {"available": False, "note": str(exc), "series": {}}

    return {
        "available": bool(out),
        "note": "Public FRED observations for regime context.",
        "series": out,
    }
