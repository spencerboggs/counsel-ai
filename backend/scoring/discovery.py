"""Deterministic discovery scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.evidence.models import EvidenceItem


DEFAULT_WEIGHTS: dict[str, float] = {
    "fundamental_quality": 0.15,
    "growth_quality": 0.15,
    "financial_health": 0.10,
    "valuation": 0.10,
    "momentum": 0.15,
    "catalysts": 0.05,
    "risk": 0.08,
    "evidence_quality": 0.05,
    "affordability": 0.17,
}

# Daytrade: favor short-horizon movement, liquidity, and catalysts over
# multi-year fundamentals. "risk" is scored as tradable volatility (see below).
DAYTRADE_WEIGHTS: dict[str, float] = {
    "fundamental_quality": 0.05,
    "growth_quality": 0.08,
    "financial_health": 0.05,
    "valuation": 0.05,
    "momentum": 0.28,
    "catalysts": 0.12,
    "risk": 0.12,
    "evidence_quality": 0.05,
    "affordability": 0.20,
}

# Swing 1-7d: event/catalyst first, momentum second, light fundamentals.
SWING_WEIGHTS: dict[str, float] = {
    "fundamental_quality": 0.06,
    "growth_quality": 0.08,
    "financial_health": 0.05,
    "valuation": 0.06,
    "momentum": 0.20,
    "catalysts": 0.28,
    "risk": 0.10,
    "evidence_quality": 0.07,
    "affordability": 0.10,
}

NEUTRAL = 50.0

# Strongest -> weakest (matches frontend signal hierarchy).
SIGNAL_ORDER = (
    "Strong Interest",
    "Interesting",
    "Watch",
    "Cautious",
    "Avoid / Defer",
)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _pct_rank(value: float, peers: list[float], *, higher_is_better: bool = True) -> float:
    if not peers:
        return NEUTRAL
    sorted_peers = sorted(peers)
    below = sum(1 for p in sorted_peers if p < value)
    equal = sum(1 for p in sorted_peers if p == value)
    rank = (below + 0.5 * equal) / len(sorted_peers)
    score = rank * 100.0
    return score if higher_is_better else 100.0 - score


def _piecewise(value: float, points: list[tuple[float, float]]) -> float:
    """Map value through (x, score) knots; clamp outside the range."""
    ordered = sorted(points, key=lambda p: p[0])
    if value <= ordered[0][0]:
        return _clamp(ordered[0][1])
    if value >= ordered[-1][0]:
        return _clamp(ordered[-1][1])
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return _clamp(y1)
            t = (value - x0) / (x1 - x0)
            return _clamp(y0 + t * (y1 - y0))
    return NEUTRAL


# Prefer absolute scales so discovery and reexamine agree on the same metrics.
# Peer ranks only nudge when the peer set is large enough to be meaningful.
_MIN_PEERS_FOR_BLEND = 5
_PEER_BLEND_WEIGHT = 0.30


def _blend_with_peers(
    absolute: float,
    peer_score: float | None,
    peer_count: int,
) -> tuple[float, str]:
    if peer_score is None or peer_count < _MIN_PEERS_FOR_BLEND:
        return absolute, "absolute scale"
    blended = (1.0 - _PEER_BLEND_WEIGHT) * absolute + _PEER_BLEND_WEIGHT * peer_score
    return (
        _clamp(blended),
        f"absolute + {int(_PEER_BLEND_WEIGHT * 100)}% peer rank (n={peer_count})",
    )


@dataclass
class ComponentScore:
    name: str
    score: float
    weight: float
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    method: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "weight": self.weight,
            "raw_metrics": self.raw_metrics,
            "method": self.method,
            "notes": self.notes,
            "weighted_contribution": round(self.score * self.weight, 2),
        }


@dataclass
class DiscoveryScoreResult:
    ticker: str
    score: float
    confidence: float
    signal: str
    components: list[ComponentScore]
    calculation: str
    evidence_ids: list[str]
    researcher_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 3),
            "signal": self.signal,
            "components": [c.to_dict() for c in self.components],
            "calculation": self.calculation,
            "evidence_ids": self.evidence_ids,
            "researcher_summary": self.researcher_summary,
        }


def _signal_for(score: float) -> str:
    if score >= 80:
        return "Strong Interest"
    if score >= 65:
        return "Interesting"
    if score >= 50:
        return "Watch"
    if score >= 35:
        return "Cautious"
    return "Avoid / Defer"


class DiscoveryScorer:
    def __init__(
        self,
        weights: dict[str, float] | None = None,
        decimals: int = 1,
        *,
        profile: str = "invest",
    ) -> None:
        self.profile = (
            "daytrade"
            if profile == "daytrade"
            else ("swing" if profile == "swing" else "invest")
        )
        if self.profile == "daytrade":
            base = DAYTRADE_WEIGHTS
        elif self.profile == "swing":
            base = SWING_WEIGHTS
        else:
            base = DEFAULT_WEIGHTS
        self.weights = {**base, **(weights or {})}
        # Normalize weights to sum 1
        total = sum(self.weights.values()) or 1.0
        self.weights = {k: v / total for k, v in self.weights.items()}
        self.decimals = decimals

    def score_candidate(
        self,
        ticker: str,
        metrics: dict[str, Any],
        peer_metrics: list[dict[str, Any]],
        evidence: list[EvidenceItem],
        *,
        researcher_summary: str | None = None,
        researcher_available: bool = True,
    ) -> DiscoveryScoreResult:
        # Exclude self-only peer sets (reexamine used to pass [self] and collapse
        # every percentile to ~50, which dragged Interesting names down to Watch).
        peers = [
            p
            for p in peer_metrics
            if isinstance(p, dict) and p is not metrics
        ]
        peer_roe = [float(p["roe"]) for p in peers if p.get("roe") is not None]
        peer_margin = [
            float(p["profit_margin"])
            for p in peers
            if p.get("profit_margin") is not None
        ]
        peer_growth = [
            float(p["revenue_growth"])
            for p in peers
            if p.get("revenue_growth") is not None
        ]
        peer_pe = [
            float(p["pe"]) for p in peers if p.get("pe") is not None and float(p["pe"]) > 0
        ]
        peer_debt = [
            float(p["debt_to_equity"])
            for p in peers
            if p.get("debt_to_equity") is not None
        ]
        peer_mom = [
            float(p["momentum_20d"])
            for p in peers
            if p.get("momentum_20d") is not None
        ]
        peer_vol = [
            float(p["volatility"]) for p in peers if p.get("volatility") is not None
        ]

        components: list[ComponentScore] = []

        # Fundamental quality: absolute ROE + margin, optional peer nudge
        fund_notes: list[str] = []
        fund_parts: list[float] = []
        fund_methods: list[str] = []
        if metrics.get("roe") is not None:
            abs_roe = _piecewise(
                float(metrics["roe"]),
                [(-0.20, 10), (0.0, 40), (0.10, 60), (0.20, 78), (0.35, 95)],
            )
            peer_s = _pct_rank(float(metrics["roe"]), peer_roe) if peer_roe else None
            blended, method = _blend_with_peers(abs_roe, peer_s, len(peer_roe))
            fund_parts.append(blended)
            fund_methods.append(f"ROE {method}")
        else:
            fund_notes.append("ROE missing -> neutral")
            fund_parts.append(NEUTRAL)
        if metrics.get("profit_margin") is not None:
            abs_pm = _piecewise(
                float(metrics["profit_margin"]),
                [(-0.10, 15), (0.0, 42), (0.08, 65), (0.18, 82), (0.30, 95)],
            )
            peer_s = (
                _pct_rank(float(metrics["profit_margin"]), peer_margin)
                if peer_margin
                else None
            )
            blended, method = _blend_with_peers(abs_pm, peer_s, len(peer_margin))
            fund_parts.append(blended)
            fund_methods.append(f"margin {method}")
        else:
            fund_notes.append("Profit margin missing -> neutral")
            fund_parts.append(NEUTRAL)
        components.append(
            ComponentScore(
                name="fundamental_quality",
                score=_clamp(sum(fund_parts) / len(fund_parts)),
                weight=self.weights["fundamental_quality"],
                raw_metrics={
                    "roe": metrics.get("roe"),
                    "profit_margin": metrics.get("profit_margin"),
                },
                method="; ".join(fund_methods) or "neutral (missing fundamentals)",
                notes=fund_notes,
            )
        )

        # Growth
        if metrics.get("revenue_growth") is not None:
            abs_g = _piecewise(
                float(metrics["revenue_growth"]),
                [(-0.30, 15), (-0.05, 35), (0.0, 48), (0.15, 70), (0.35, 88), (0.60, 96)],
            )
            peer_s = (
                _pct_rank(float(metrics["revenue_growth"]), peer_growth)
                if peer_growth
                else None
            )
            growth_score, growth_method = _blend_with_peers(
                abs_g, peer_s, len(peer_growth)
            )
            growth_notes: list[str] = []
        else:
            growth_score = NEUTRAL
            growth_method = "neutral (missing growth)"
            growth_notes = ["Revenue growth missing -> neutral"]
        components.append(
            ComponentScore(
                name="growth_quality",
                score=_clamp(growth_score),
                weight=self.weights["growth_quality"],
                raw_metrics={"revenue_growth": metrics.get("revenue_growth")},
                method=growth_method,
                notes=growth_notes,
            )
        )

        # Financial health: lower debt better; higher current ratio better
        health_parts: list[float] = []
        health_notes: list[str] = []
        health_methods: list[str] = []
        if metrics.get("debt_to_equity") is not None:
            abs_debt = _piecewise(
                float(metrics["debt_to_equity"]),
                [(0.0, 95), (0.40, 80), (1.0, 58), (2.0, 38), (4.0, 15)],
            )
            peer_s = (
                _pct_rank(
                    float(metrics["debt_to_equity"]),
                    peer_debt,
                    higher_is_better=False,
                )
                if peer_debt
                else None
            )
            blended, method = _blend_with_peers(abs_debt, peer_s, len(peer_debt))
            health_parts.append(blended)
            health_methods.append(f"debt {method}")
        else:
            health_notes.append("Debt/equity missing -> neutral")
            health_parts.append(NEUTRAL)
        cr = metrics.get("current_ratio")
        if cr is not None:
            health_parts.append(
                _piecewise(float(cr), [(0.4, 20), (1.0, 55), (1.5, 72), (2.5, 88), (4.0, 92)])
            )
            health_methods.append("current-ratio absolute scale")
        else:
            health_notes.append("Current ratio missing -> neutral")
            health_parts.append(NEUTRAL)
        components.append(
            ComponentScore(
                name="financial_health",
                score=_clamp(sum(health_parts) / len(health_parts)),
                weight=self.weights["financial_health"],
                raw_metrics={
                    "debt_to_equity": metrics.get("debt_to_equity"),
                    "current_ratio": metrics.get("current_ratio"),
                },
                method="; ".join(health_methods) or "neutral (missing health metrics)",
                notes=health_notes,
            )
        )

        # Valuation: lower PE better
        if metrics.get("pe") is not None and float(metrics["pe"]) > 0:
            abs_pe = _piecewise(
                float(metrics["pe"]),
                [(6, 92), (12, 80), (18, 65), (28, 48), (45, 28), (70, 12)],
            )
            peer_s = (
                _pct_rank(float(metrics["pe"]), peer_pe, higher_is_better=False)
                if peer_pe
                else None
            )
            val_score, val_method = _blend_with_peers(abs_pe, peer_s, len(peer_pe))
            val_notes: list[str] = []
        else:
            val_score = NEUTRAL
            val_method = "neutral (missing PE)"
            val_notes = ["PE missing or non-positive -> neutral"]
        components.append(
            ComponentScore(
                name="valuation",
                score=_clamp(val_score),
                weight=self.weights["valuation"],
                raw_metrics={"pe": metrics.get("pe"), "ps": metrics.get("ps")},
                method=val_method,
                notes=val_notes,
            )
        )

        # Momentum
        if metrics.get("momentum_20d") is not None:
            abs_mom = _piecewise(
                float(metrics["momentum_20d"]),
                [(-0.25, 12), (-0.10, 30), (0.0, 50), (0.08, 70), (0.18, 85), (0.35, 95)],
            )
            peer_s = (
                _pct_rank(float(metrics["momentum_20d"]), peer_mom) if peer_mom else None
            )
            mom_score, mom_method = _blend_with_peers(abs_mom, peer_s, len(peer_mom))
            mom_notes: list[str] = []
            if metrics.get("above_50dma"):
                mom_score = _clamp(mom_score + 5)
                mom_notes.append("+5 for price above 50-day MA")
        else:
            mom_score = NEUTRAL
            mom_method = "neutral (missing momentum)"
            mom_notes = ["Momentum missing -> neutral"]
        components.append(
            ComponentScore(
                name="momentum",
                score=_clamp(mom_score),
                weight=self.weights["momentum"],
                raw_metrics={
                    "momentum_20d": metrics.get("momentum_20d"),
                    "above_50dma": metrics.get("above_50dma"),
                },
                method=f"{mom_method}; bonus if above 50DMA",
                notes=mom_notes,
            )
        )

        # Catalysts: news count + optional event-first catalyst_score / horizon fit
        news_count = int(metrics.get("news_count") or 0)
        catalyst_score = _clamp(min(news_count, 10) / 10 * 70 + 15)
        cat_notes: list[str] = []
        if not news_count:
            cat_notes.append("No news items -> low catalyst score")
        event_score = metrics.get("catalyst_score")
        if event_score is not None:
            catalyst_score = _clamp(0.45 * catalyst_score + 0.55 * float(event_score))
            cat_notes.append(f"Event catalyst score {float(event_score):.0f}")
        horizon_fit = metrics.get("horizon_fit")
        if horizon_fit is not None:
            catalyst_score = _clamp(0.75 * catalyst_score + 0.25 * float(horizon_fit))
            cat_notes.append(
                f"Horizon fit {float(horizon_fit):.0f} for hold_days="
                f"{metrics.get('hold_days', '?')}"
            )
        components.append(
            ComponentScore(
                name="catalysts",
                score=catalyst_score,
                weight=self.weights["catalysts"],
                raw_metrics={
                    "news_count": news_count,
                    "catalyst_score": metrics.get("catalyst_score"),
                    "horizon_fit": metrics.get("horizon_fit"),
                    "hold_days": metrics.get("hold_days"),
                    "catalyst_headline": metrics.get("catalyst_headline"),
                },
                method="news volume + event catalyst + hold-horizon fit",
                notes=cat_notes,
            )
        )

        # Risk / move quality - absolute first so reexamine matches discovery
        risk_parts: list[float] = []
        risk_notes: list[str] = []
        beta = metrics.get("beta")
        if self.profile == "daytrade":
            if metrics.get("volatility") is not None:
                vol = float(metrics["volatility"])
                # Sweet spot ~0.25-0.50 annualized-ish daily vol proxy
                abs_vol = _piecewise(
                    vol,
                    [(0.08, 28), (0.18, 55), (0.30, 78), (0.45, 88), (0.70, 55), (1.0, 25)],
                )
                peer_s = _pct_rank(vol, peer_vol) if peer_vol else None
                # Daytrade peer nudge uses mid-band preference via absolute already
                blended, method = _blend_with_peers(abs_vol, peer_s, len(peer_vol))
                risk_parts.append(blended)
                risk_notes.append(f"Vol {method}")
            else:
                risk_notes.append("Volatility missing -> neutral")
                risk_parts.append(NEUTRAL)
            if beta is not None:
                risk_parts.append(_clamp(40 + abs(float(beta)) * 25))
            else:
                risk_notes.append("Beta missing -> neutral")
                risk_parts.append(NEUTRAL)
            risk_method = "daytrade move quality: absolute vol sweet-spot + beta magnitude"
        else:
            if metrics.get("volatility") is not None:
                vol = float(metrics["volatility"])
                abs_vol = _piecewise(
                    vol,
                    [(0.10, 90), (0.20, 75), (0.35, 55), (0.55, 32), (0.85, 15)],
                )
                peer_s = (
                    _pct_rank(vol, peer_vol, higher_is_better=False) if peer_vol else None
                )
                blended, method = _blend_with_peers(abs_vol, peer_s, len(peer_vol))
                risk_parts.append(blended)
                risk_notes.append(f"Vol {method}")
            else:
                risk_notes.append("Volatility missing -> neutral")
                risk_parts.append(NEUTRAL)
            if beta is not None:
                risk_parts.append(_clamp(100 - abs(float(beta) - 1.0) * 40))
            else:
                risk_notes.append("Beta missing -> neutral")
                risk_parts.append(NEUTRAL)
            risk_method = "invest risk: absolute vol (lower better) + beta proximity to 1"
        components.append(
            ComponentScore(
                name="risk",
                score=_clamp(sum(risk_parts) / len(risk_parts)),
                weight=self.weights["risk"],
                raw_metrics={"volatility": metrics.get("volatility"), "beta": beta},
                method=risk_method,
                notes=risk_notes,
            )
        )

        # Evidence quality
        if evidence:
            eq = (
                sum(
                    (
                        e.reliability * 0.25
                        + (1.0 if e.source_type == "primary" else 0.6) * 0.20
                        + e.freshness * 0.15
                        + e.directness * 0.20
                        + e.corroboration * 0.10
                        + 0.7 * 0.10
                    )
                    * 100
                    for e in evidence
                )
                / len(evidence)
            )
            eq_notes = [f"{len(evidence)} evidence items averaged"]
        else:
            eq = 20.0
            eq_notes = ["No evidence -> low evidence quality"]
        components.append(
            ComponentScore(
                name="evidence_quality",
                score=_clamp(eq),
                weight=self.weights["evidence_quality"],
                raw_metrics={"evidence_count": len(evidence)},
                method="weighted authority/primary/recency/directness/corroboration",
                notes=eq_notes,
            )
        )

        # Affordability / position sizing for the user's budget
        budget = float(metrics.get("investable_amount") or 100.0)
        price = metrics.get("price")
        shares = metrics.get("shares_buyable")
        afford_notes: list[str] = []
        if price is not None and price > 0:
            if shares is None:
                shares = int(budget // float(price))
            # Target: being able to buy ~10+ whole shares scores highly
            share_score = _clamp(float(shares) / 15.0 * 100)
            # Smaller market caps score higher for discovery sizing
            mcap = metrics.get("market_cap")
            if mcap is not None and mcap > 0:
                # $500M -> high, $40B -> low
                mcap_score = _clamp(100 - (float(mcap) / 40_000_000_000) * 100)
            else:
                mcap_score = NEUTRAL
                afford_notes.append("Market cap missing -> neutral size term")
            afford_score = _clamp(0.65 * share_score + 0.35 * mcap_score)
            afford_notes.append(
                f"${budget:.0f} buys ~{shares} shares @ ${float(price):.2f}"
            )
        else:
            afford_score = 15.0
            afford_notes.append("Price missing -> low affordability")
            shares = None
        components.append(
            ComponentScore(
                name="affordability",
                score=afford_score,
                weight=self.weights.get("affordability", 0.17),
                raw_metrics={
                    "investable_amount": budget,
                    "price": price,
                    "shares_buyable": shares,
                    "market_cap": metrics.get("market_cap"),
                },
                method="whole shares purchasable with budget + inverse market-cap size",
                notes=afford_notes,
            )
        )

        weighted = sum(c.score * c.weight for c in components)
        score = round(_clamp(weighted), self.decimals)

        present = sum(
            1
            for k in ("roe", "profit_margin", "revenue_growth", "pe", "momentum_20d", "volatility")
            if metrics.get(k) is not None
        )
        confidence = min(0.95, 0.35 + 0.08 * present + (0.1 if evidence else 0) + (0.05 if researcher_available else 0))
        if not researcher_available:
            confidence = max(0.2, confidence - 0.15)

        calc_lines = [
            f"{c.name}={c.score:.1f} x {c.weight:.2f} = {c.score * c.weight:.2f}"
            for c in components
        ]
        calc_lines.append(f"weighted_sum={weighted:.2f} -> score={score}")

        return DiscoveryScoreResult(
            ticker=ticker.upper(),
            score=score,
            confidence=confidence,
            signal=_signal_for(score),
            components=components,
            calculation="; ".join(calc_lines),
            evidence_ids=[e.id for e in evidence],
            researcher_summary=researcher_summary,
        )
