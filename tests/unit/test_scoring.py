"""Discovery scorer unit tests."""

from __future__ import annotations

from backend.evidence.models import EvidenceItem
from backend.scoring.discovery import DiscoveryScorer


def _metrics(**overrides):
    base = {
        "roe": 0.2,
        "profit_margin": 0.15,
        "revenue_growth": 0.1,
        "debt_to_equity": 50,
        "current_ratio": 1.5,
        "pe": 20,
        "momentum_20d": 0.05,
        "above_50dma": True,
        "volatility": 0.02,
        "beta": 1.1,
        "news_count": 3,
    }
    base.update(overrides)
    return base


def test_weighted_score_decimals_and_signal():
    scorer = DiscoveryScorer(decimals=1)
    peers = [_metrics(roe=0.1), _metrics(roe=0.3), _metrics()]
    evidence = [
        EvidenceItem(
            id="EV-1",
            ticker="AAPL",
            claim="test",
            source_name="test",
            source_type="secondary",
            retrieved_at="2026-01-01T00:00:00Z",
            reliability=0.9,
            freshness=0.9,
            directness=1.0,
            corroboration=0.8,
        )
    ]
    result = scorer.score_candidate("AAPL", _metrics(), peers, evidence)
    assert isinstance(result.score, float)
    assert round(result.score, 1) == result.score
    assert 0 <= result.score <= 100
    assert result.signal
    assert len(result.components) == 9
    assert any(c.name == "affordability" for c in result.components)
    assert "weighted_sum" in result.calculation


def test_missing_metrics_use_neutral_notes():
    scorer = DiscoveryScorer()
    result = scorer.score_candidate("XYZ", {}, [], [])
    assert result.score == 50.0 or 20 <= result.score <= 60
    fund = next(c for c in result.components if c.name == "fundamental_quality")
    assert any("neutral" in n.lower() for n in fund.notes)
