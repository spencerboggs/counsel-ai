"""Wake reconciliation after Autopilot was stopped / asleep."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.portfolio.ledger import TradeLedger
from backend.portfolio.settlement import SettlementService
from backend.portfolio.store import PaperPositionStore
from backend.portfolio.wash_sales import WashSaleService
from backend.providers.alpaca import AlpacaClient, active_trading_backend
from backend.storage.database import Database


async def wake_reconcile(db: Database, *, asleep_since: str | None) -> dict[str, Any]:
    """Compare local ledger vs account; summarize what changed while asleep."""
    backend = active_trading_backend()
    capital = await SettlementService(db).account_snapshot()
    positions = await PaperPositionStore(db).list_positions("open")
    lots = await TradeLedger(db).open_lots()
    wash = await WashSaleService(db).active_blocks()

    broker_positions: list[dict[str, Any]] = []
    broker_orders: list[dict[str, Any]] = []
    broker_error = None
    if backend in {"paper_alpaca", "live_alpaca"}:
        client = AlpacaClient(live=backend == "live_alpaca")
        if client.configured:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=20.0) as http:
                    pos_r = await http.get(
                        f"{client.base}/v2/positions",
                        headers=client._headers(),
                    )
                    ord_r = await http.get(
                        f"{client.base}/v2/orders",
                        headers=client._headers(),
                        params={"status": "open", "limit": 50},
                    )
                if pos_r.status_code < 400:
                    broker_positions = pos_r.json() if isinstance(pos_r.json(), list) else []
                else:
                    broker_error = pos_r.text
                if ord_r.status_code < 400:
                    broker_orders = ord_r.json() if isinstance(ord_r.json(), list) else []
            except Exception as exc:
                broker_error = str(exc)

    local_symbols = sorted({str(p["ticker"]).upper() for p in positions})
    broker_symbols = sorted(
        {
            str(p.get("symbol") or "").upper()
            for p in broker_positions
            if p.get("symbol")
        }
    )
    mismatches: list[str] = []
    if backend != "paper_local" and broker_symbols:
        only_local = set(local_symbols) - set(broker_symbols)
        only_broker = set(broker_symbols) - set(local_symbols)
        if only_local:
            mismatches.append(f"Local-only: {', '.join(sorted(only_local))}")
        if only_broker:
            mismatches.append(f"Broker-only: {', '.join(sorted(only_broker))}")

    asleep_note = None
    if asleep_since:
        asleep_note = (
            f"Autopilot was asleep since {asleep_since}. "
            "Reconciled account, lots, wash blocks, and open orders before trading."
        )

    return {
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
        "asleep_since": asleep_since,
        "asleep_note": asleep_note,
        "venue": backend,
        "capital": capital,
        "local_open_positions": len(positions),
        "local_open_lots": len(lots),
        "local_symbols": local_symbols,
        "broker_positions": len(broker_positions),
        "broker_open_orders": len(broker_orders),
        "broker_symbols": broker_symbols,
        "wash_blocks": wash,
        "mismatches": mismatches,
        "broker_error": broker_error,
        "trading_halted_for_mismatch": bool(mismatches),
        "note": (
            "Paper seed cash is not live equity. Live/paper-Alpaca capital "
            "comes from the broker account snapshot."
        ),
    }
