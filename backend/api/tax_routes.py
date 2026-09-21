"""Tax ledger, settlement, wash-sale, and compliance API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.portfolio.capital_gate import CapitalGateError
from backend.portfolio.ledger import TradeLedger
from backend.portfolio.settlement import SettlementService
from backend.portfolio.wash_sales import WashSaleService
from backend.compliance.status import compliance_checklist

tax_router = APIRouter(prefix="/tax", tags=["tax"])


class PurgeRequest(BaseModel):
    entity_type: str
    entity_id: str
    reason: str = Field(min_length=20)
    confirmation_phrase: str


class WashCheckRequest(BaseModel):
    ticker: str
    wash_override_phrase: str | None = None


@tax_router.get("/summary")
async def tax_summary(request: Request) -> dict:
    ledger = TradeLedger(request.app.state.db)
    settlement = SettlementService(request.app.state.db)
    wash = WashSaleService(request.app.state.db)
    realized = await ledger.realized_summary()
    capital = await settlement.account_snapshot()
    blocks = await wash.active_blocks()
    lots = await ledger.open_lots()
    unrealized_cost = sum(
        float(lot["qty_open"])
        * float(
            lot["adjusted_basis_per_share"]
            if lot.get("adjusted_basis_per_share") is not None
            else lot["cost_basis_per_share"]
        )
        for lot in lots
    )
    return {
        "realized": realized,
        "capital": capital,
        "wash_blocks": blocks,
        "open_lots": len(lots),
        "open_lot_cost": round(unrealized_cost, 2),
        "disclaimer": (
            "Informational only - not tax, legal, or investment advice. "
            "You remain responsible for IRS reporting even when a 1099-B is incomplete."
        ),
    }


@tax_router.get("/dispositions")
async def list_dispositions(request: Request, limit: int = 500) -> dict:
    ledger = TradeLedger(request.app.state.db)
    rows = await ledger.list_dispositions(limit=limit)
    return {"count": len(rows), "items": rows}


@tax_router.get("/lots")
async def list_lots(request: Request) -> dict:
    ledger = TradeLedger(request.app.state.db)
    rows = await ledger.open_lots()
    return {"count": len(rows), "items": rows}


@tax_router.get("/fills")
async def list_fills(request: Request, limit: int = 500) -> dict:
    ledger = TradeLedger(request.app.state.db)
    rows = await ledger.list_fills(limit=limit)
    return {"count": len(rows), "items": rows}


@tax_router.get("/orders")
async def list_orders(request: Request, limit: int = 500) -> dict:
    ledger = TradeLedger(request.app.state.db)
    rows = await ledger.list_orders(limit=limit)
    return {"count": len(rows), "items": rows}


@tax_router.get("/wash-blocks")
async def wash_blocks(request: Request) -> dict:
    wash = WashSaleService(request.app.state.db)
    items = await wash.active_blocks()
    return {
        "count": len(items),
        "items": items,
        "note": "Same-ticker wash window (30 days before/after a loss sale).",
    }


@tax_router.post("/wash-check")
async def wash_check(body: WashCheckRequest, request: Request) -> dict:
    wash = WashSaleService(request.app.state.db)
    result = await wash.assert_buy_allowed(
        body.ticker, wash_override_phrase=body.wash_override_phrase
    )
    return result


@tax_router.get("/capital")
async def capital(request: Request) -> dict:
    return await SettlementService(request.app.state.db).account_snapshot()


@tax_router.post("/purge-request")
async def purge_request(body: PurgeRequest, request: Request) -> dict:
    ledger = TradeLedger(request.app.state.db)
    try:
        return await ledger.request_purge(
            body.entity_type,
            body.entity_id,
            body.reason,
            body.confirmation_phrase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@tax_router.get("/compliance")
async def compliance() -> dict:
    return compliance_checklist()
