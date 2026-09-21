"""Aggregate crew votes in Python. Lawyer and broker rejects block trades."""

from __future__ import annotations

from typing import Any


RESEARCHER_ROLES = {
    "fundamental_researcher",
    "factor_researcher",
    "macro_researcher",
    "social_scanner",
}


def _stance(vote: dict[str, Any]) -> str:
    return str(vote.get("stance") or "abstain").lower().strip()


def evaluate_consensus(
    votes: list[dict[str, Any]],
    *,
    proposal: dict[str, Any] | None,
    allowlist: list[str],
    wash_blocked: set[str],
) -> dict[str, Any]:
    by_role = {str(v.get("role")): v for v in votes if v.get("role")}
    lawyer = by_role.get("lawyer") or {}
    broker = by_role.get("broker_accountant") or {}
    client = by_role.get("client") or {}
    trader = by_role.get("trader") or {}

    reasons: list[str] = []
    if _stance(lawyer) == "reject":
        return {
            "approved": False,
            "action": "none",
            "reasons": ["Lawyer veto: " + str(lawyer.get("rationale") or "reject")],
            "proposal": proposal,
        }
    if _stance(broker) == "reject":
        return {
            "approved": False,
            "action": "none",
            "reasons": [
                "Broker/accountant veto: " + str(broker.get("rationale") or "reject")
            ],
            "proposal": proposal,
        }

    prop = proposal or (trader.get("proposal") if isinstance(trader.get("proposal"), dict) else {})
    action = str((prop or {}).get("action") or "none").lower()
    symbol = str((prop or {}).get("symbol") or "").upper() or None

    if action in {"none", "hold"} or not symbol:
        return {
            "approved": False,
            "action": action if action in {"hold", "none"} else "none",
            "reasons": ["No actionable trade proposal."],
            "proposal": prop,
        }

    if symbol not in {s.upper() for s in allowlist}:
        return {
            "approved": False,
            "action": "none",
            "reasons": [f"{symbol} not on allowlist."],
            "proposal": prop,
        }

    if action == "buy" and symbol in wash_blocked:
        return {
            "approved": False,
            "action": "none",
            "reasons": [f"{symbol} wash-sale blocked - Autopilot cannot override."],
            "proposal": prop,
        }

    if _stance(lawyer) != "approve" or _stance(broker) != "approve":
        reasons.append("Lawyer and broker must both approve actionable trades.")
        return {
            "approved": False,
            "action": "none",
            "reasons": reasons,
            "proposal": prop,
        }

    if action == "buy":
        if _stance(client) == "reject":
            return {
                "approved": False,
                "action": "none",
                "reasons": ["Client rejected the buy."],
                "proposal": prop,
            }
        researcher_approves = sum(
            1
            for role in RESEARCHER_ROLES
            if _stance(by_role.get(role) or {}) == "approve"
        )
        if researcher_approves < 2:
            return {
                "approved": False,
                "action": "none",
                "reasons": [
                    f"Need >=2 researcher approvals (have {researcher_approves})."
                ],
                "proposal": prop,
            }
        if _stance(trader) not in {"approve", "hold"} and not prop.get("action"):
            return {
                "approved": False,
                "action": "none",
                "reasons": ["Trader did not propose a buy."],
                "proposal": prop,
            }

    # sell path: lawyer+broker already approved
    return {
        "approved": True,
        "action": action,
        "symbol": symbol,
        "shares": float(prop.get("shares") or 0),
        "notional": float(prop.get("notional") or 0),
        "reasons": ["Consensus passed law and capital personality gates."],
        "proposal": prop,
    }
