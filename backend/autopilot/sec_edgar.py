"""Public SEC EDGAR helpers (fair-access HTTP, no login)."""

from __future__ import annotations

from typing import Any

import httpx

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

# SEC fair-access requires a descriptive User-Agent with contact.
DEFAULT_UA = "AICounselAutopilot/0.1 (local research; contact: local-user@localhost)"


def _user_agent(override: str | None = None) -> str:
    if override:
        return override
    try:
        from backend.config.settings import get_app_config

        cfg = get_app_config()
        ap = getattr(cfg, "autopilot", None) or {}
        if isinstance(ap, dict) and ap.get("sec_user_agent"):
            return str(ap["sec_user_agent"])
        raw = cfg.model_dump() if hasattr(cfg, "model_dump") else {}
        ua = (raw.get("autopilot") or {}).get("sec_user_agent")
        if ua:
            return str(ua)
    except Exception:
        pass
    return DEFAULT_UA


async def lookup_cik(ticker: str, *, user_agent: str | None = None) -> str | None:
    user_agent = _user_agent(user_agent)
    symbol = ticker.upper().strip()
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": user_agent}) as client:
            response = await client.get(SEC_TICKERS_URL)
            if response.status_code >= 400:
                return None
            data = response.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for row in data.values():
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").upper() == symbol:
            cik = str(row.get("cik_str") or "").zfill(10)
            return cik
    return None


async def recent_filings(
    ticker: str,
    *,
    limit: int = 8,
    user_agent: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent filing titles/forms for a ticker (public data)."""
    user_agent = _user_agent(user_agent)
    cik = await lookup_cik(ticker, user_agent=user_agent)
    if not cik:
        return []
    url = SEC_SUBMISSIONS.format(cik=cik)
    try:
        async with httpx.AsyncClient(timeout=25.0, headers={"User-Agent": user_agent}) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                return []
            payload = response.json()
    except Exception:
        return []
    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    descs = recent.get("primaryDocDescription") or []
    out: list[dict[str, Any]] = []
    for i in range(min(limit, len(forms))):
        out.append(
            {
                "form": forms[i] if i < len(forms) else None,
                "filing_date": dates[i] if i < len(dates) else None,
                "description": descs[i] if i < len(descs) else None,
            }
        )
    return out
