"""Fractional Kelly position sizing from in-sample probe stats.

Caps at max_bet_pct (default 6%) and applies kelly_fraction (default 0.5).
"""

from __future__ import annotations

from typing import Any


def _trading_kelly_defaults() -> dict[str, float]:
    try:
        from backend.compliance.risk_gates import trading_config

        t = trading_config()
        return {
            "max_bet_pct": float(t.get("max_bet_pct", 0.06)),
            "kelly_fraction": float(t.get("kelly_fraction", 0.5)),
            "min_edge": float(t.get("kelly_min_edge", 0.0)),
        }
    except Exception:
        return {"max_bet_pct": 0.06, "kelly_fraction": 0.5, "min_edge": 0.0}


def kelly_fraction_from_probe(probe: dict[str, Any] | None) -> dict[str, Any]:
    """Estimate f* from historical_probe forward stats (prefer d5).

    Even-money Kelly from win rate: f* = 2p - 1.
    Mean forward return gently scales size when positive.
    Result is always half-Kelly (configurable) and hard-capped at max_bet_pct.
    """
    defaults = _trading_kelly_defaults()
    max_bet = defaults["max_bet_pct"]
    frac = defaults["kelly_fraction"]

    empty = {
        "kelly_full": 0.0,
        "kelly_fractional": 0.0,
        "bet_pct": 0.0,
        "capped": True,
        "reason": "No usable probe stats - exploratory/mini size only.",
        "inputs": {},
    }
    if not probe or int(probe.get("samples") or 0) < 5:
        return empty

    forward = probe.get("forward") or {}
    stats = forward.get("d5") or forward.get("d3") or forward.get("d10") or forward.get("d1")
    if not isinstance(stats, dict):
        return empty

    p = stats.get("win_rate")
    mean = stats.get("mean")
    n = stats.get("n") or probe.get("samples")
    if p is None:
        return empty
    p = float(p)
    mean = float(mean) if mean is not None else 0.0

    # Even-money Kelly from win rate (robust when we lack separate W/L odds).
    f_star = max(0.0, 2.0 * p - 1.0)
    if mean > 0 and f_star > 0:
        f_star = min(1.0, f_star * (1.0 + min(mean * 5.0, 0.5)))
    elif mean <= 0 and p <= 0.55:
        return {
            **empty,
            "reason": "Probe shows weak/negative edge (win_rate and mean).",
            "inputs": {"p": round(p, 4), "mean": round(mean, 4), "n": n},
        }

    f_half = f_star * frac
    bet_pct = min(f_half, max_bet)

    if bet_pct <= defaults["min_edge"] and f_star <= 0:
        return {
            "kelly_full": round(f_star, 4),
            "kelly_fractional": round(f_half, 4),
            "bet_pct": 0.0,
            "capped": True,
            "reason": "Kelly edge not positive after fraction.",
            "inputs": {"p": round(p, 4), "mean": round(mean, 4), "n": n},
        }

    return {
        "kelly_full": round(f_star, 4),
        "kelly_fractional": round(f_half, 4),
        "bet_pct": round(bet_pct, 4),
        "capped": bet_pct >= max_bet - 1e-9 or f_half > max_bet,
        "max_bet_pct": max_bet,
        "kelly_fraction_used": frac,
        "reason": (
            f"Half-Kelly from probe (p={p:.2f}, mean={mean:.3f}, n={n}); "
            f"hard cap {max_bet:.0%}."
        ),
        "inputs": {"p": round(p, 4), "mean": round(mean, 4), "n": n},
    }


def size_notional(
    *,
    equity_or_bp: float,
    probe: dict[str, Any] | None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Return dollar notional for a buy given capital and probe."""
    defaults = _trading_kelly_defaults()
    max_bet = defaults["max_bet_pct"]
    capital = max(0.0, float(equity_or_bp or 0))
    kelly = kelly_fraction_from_probe(probe)

    conf = 1.0
    if confidence is not None:
        conf = max(0.35, min(1.0, float(confidence)))

    bet_pct = float(kelly.get("bet_pct") or 0) * conf
    # Floor: weak probe still allows tiny exploratory size (<=2%, still under 6% cap)
    if bet_pct <= 0 and capital > 0:
        bet_pct = min(0.02, max_bet) * conf * 0.5
        kelly = {
            **kelly,
            "bet_pct": round(bet_pct, 4),
            "reason": (kelly.get("reason") or "")
            + " Using exploratory mini-size (<=2%).",
        }

    bet_pct = min(bet_pct, max_bet)
    notional = round(capital * bet_pct, 2)
    return {
        "notional": notional,
        "bet_pct": round(bet_pct, 4),
        "capital_base": capital,
        "kelly": kelly,
        "max_bet_pct": max_bet,
    }
