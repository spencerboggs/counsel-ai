"""Counsel panel aggregation tests."""

from backend.counsel.panel import aggregate_panel, normalize_dimension_scores


def _dims(value: float) -> dict[str, float]:
    return {
        name: value
        for name in (
            "fundamental_quality",
            "growth_quality",
            "financial_health",
            "valuation",
            "momentum",
            "catalysts",
            "risk",
            "evidence_quality",
            "affordability",
        )
    }


def test_panel_uses_median_not_mean():
    """A near-zero skeptic must not collapse a strong fund+counsel consensus."""
    findings = [
        {
            "role": "fundamental",
            "model": "qwen",
            "dimension_scores": _dims(70),
            "summary": "bull",
            "confidence": 0.6,
            "evidence_ids": ["EV-1"],
            "risks": [],
        },
        {
            "role": "skeptic",
            "model": "qwen",
            "dimension_scores": _dims(0.2),
            "summary": "bear",
            "confidence": 0.5,
            "evidence_ids": [],
            "risks": ["thin evidence"],
        },
        {
            "role": "counsel",
            "model": "qwen",
            "dimension_scores": _dims(60),
            "summary": "balanced",
            "confidence": 0.55,
            "evidence_ids": ["EV-1"],
            "risks": [],
        },
    ]
    result = aggregate_panel(findings)
    # 0.2 was on a 0-1 scale -> normalized to 20; median(70, 20, 60) = 60
    assert result["panel_score"] == 60.0
    assert result["panel_spread"] == 50.0
    assert len(result["agents"]) == 3
    skeptic = next(a for a in result["agents"] if a["role"] == "skeptic")
    assert skeptic["score"] == 20.0


def test_normalize_dimension_scores_rescales_unit_interval():
    out = normalize_dimension_scores({"fundamental_quality": 0.7, "risk": 0.4})
    assert out["fundamental_quality"] == 70.0
    assert out["risk"] == 40.0


def test_normalize_dimension_scores_keeps_hundred_scale():
    out = normalize_dimension_scores({"fundamental_quality": 70, "risk": 40})
    assert out["fundamental_quality"] == 70.0
    assert out["risk"] == 40.0


def test_panel_average_and_spread_two_roles():
    findings = [
        {
            "role": "fundamental",
            "model": "qwen",
            "dimension_scores": _dims(80),
            "summary": "bull",
            "confidence": 0.6,
            "evidence_ids": ["EV-1"],
            "risks": [],
        },
        {
            "role": "skeptic",
            "model": "qwen",
            "dimension_scores": _dims(40),
            "summary": "bear",
            "confidence": 0.5,
            "evidence_ids": [],
            "risks": ["thin evidence"],
        },
    ]
    result = aggregate_panel(findings)
    assert result["panel_score"] == 60.0
    assert result["panel_spread"] == 40.0
    assert len(result["agents"]) == 2
