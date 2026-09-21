"""Event-first catalyst scan for the swing (1-7 day) lane.

Find event signals, then associate tickers, rather than screening
stocks first and hoping a catalyst appears.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.providers.base import MarketDataProvider, NewsItem

# Keyword buckets that often precede multi-day moves.
CATALYST_PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    ("earnings", 22.0, re.compile(r"\bearnings\b|\beps\b|\bguidance\b|\bbeat\b|\bmiss\b", re.I)),
    ("fda", 28.0, re.compile(r"\bfda\b|\bapproval\b|\bphase\s*[123]\b|\btrial\b", re.I)),
    ("ma", 26.0, re.compile(r"\bacqui|\bmerger\b|\btakeover\b|\bbuyout\b|\bdeal\b", re.I)),
    ("offering", 18.0, re.compile(r"\boffering\b|\bdilution\b|\batm\b|\braise[sd]?\b", re.I)),
    ("contract", 20.0, re.compile(r"\bcontract\b|\baward\b|\bpentagon\b|\bdoe\b", re.I)),
    ("analyst", 14.0, re.compile(r"\bupgrade\b|\bdowngrade\b|\bprice\s*target\b|\binitiate", re.I)),
    ("lawsuit", 16.0, re.compile(r"\blawsuit\b|\bsec\b|\binvestigat|\bsettlement\b", re.I)),
    ("product", 15.0, re.compile(r"\blaunch\b|\brelease\b|\bunveil|\bpartnership\b", re.I)),
]


@dataclass
class CatalystHit:
    ticker: str
    score: float
    labels: list[str] = field(default_factory=list)
    headline: str | None = None
    news_count: int = 0
    horizon_fit: float = 50.0


def score_news_for_catalysts(
    items: list[NewsItem],
    *,
    hold_days: int = 3,
) -> tuple[float, list[str], str | None, float]:
    """Return (catalyst_score 0-100, labels, best_headline, horizon_fit)."""
    if not items:
        return 10.0, [], None, 35.0

    labels: list[str] = []
    raw = 0.0
    best_headline: str | None = None
    best_hit = 0.0
    for item in items[:12]:
        text = f"{item.title or ''} {item.summary or ''}"
        hit = 0.0
        for label, weight, pattern in CATALYST_PATTERNS:
            if pattern.search(text):
                hit += weight
                if label not in labels:
                    labels.append(label)
        if hit > best_hit:
            best_hit = hit
            best_headline = item.title
        raw += hit

    # Density + strength
    score = min(100.0, 18.0 + raw * 0.85 + min(len(items), 8) * 3.0)

    # Horizon fit: earnings/FDA/MA tend to play out over a few days;
    # very long hold_days slightly lowers urgency score.
    hold = max(1, min(7, int(hold_days)))
    if labels:
        base_fit = 55.0 + min(35.0, len(labels) * 8.0)
    else:
        base_fit = 40.0
    # Prefer 2-4 day windows for event digestion; nudge ends down.
    if hold <= 2:
        base_fit += 8.0
    elif hold <= 4:
        base_fit += 12.0
    elif hold <= 6:
        base_fit += 4.0
    else:
        base_fit -= 4.0
    horizon_fit = max(15.0, min(95.0, base_fit))
    return score, labels, best_headline, horizon_fit


async def scan_tickers_for_catalysts(
    market: MarketDataProvider,
    tickers: list[str],
    *,
    hold_days: int = 3,
    min_score: float = 28.0,
    should_stop: Any | None = None,
) -> list[CatalystHit]:
    """Event-first: news scan -> keep tickers with catalyst signal."""
    hits: list[CatalystHit] = []
    for ticker in tickers:
        if should_stop and should_stop():
            break
        try:
            news = await market.get_news(ticker)
        except Exception:
            continue
        score, labels, headline, horizon = score_news_for_catalysts(
            news, hold_days=hold_days
        )
        if score < min_score and not labels:
            continue
        if score < min_score:
            continue
        hits.append(
            CatalystHit(
                ticker=ticker.upper(),
                score=score,
                labels=labels,
                headline=headline,
                news_count=len(news),
                horizon_fit=horizon,
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits
