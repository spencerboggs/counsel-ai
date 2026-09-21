"""Pre-trade capital and compliance gate."""

from __future__ import annotations

from typing import Any

from backend.compliance.risk_gates import assert_execution_allowed, trading_config
from backend.portfolio.ledger import TradeLedger
from backend.portfolio.settlement import SettlementService
from backend.portfolio.store import PaperPositionStore
from backend.portfolio.wash_sales import WashSaleService
from backend.storage.database import Database


class CapitalGateError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class CapitalGate:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._ledger = TradeLedger(db)
        self._settlement = SettlementService(db)
        self._wash = WashSaleService(db)

    async def check_buy(
        self,
        *,
        symbol: str,
        qty: float,
        price: float,
        wash_override_phrase: str | None = None,
        max_notional: float | None = None,
        quote_as_of: str | None = None,
    ) -> dict[str, Any]:
        if qty < 1:
            raise CapitalGateError("qty", "Order requires at least 1 whole share")
        notional = float(qty) * float(price)
        if max_notional is not None and notional > max_notional + 0.01:
            raise CapitalGateError(
                "max_notional",
                f"Order ${notional:.2f} exceeds max notional ${max_notional:.2f}",
            )

        safety = await assert_execution_allowed(
            self._db,
            symbol=symbol,
            notional=notional,
            quote_as_of=quote_as_of,
            side="buy",
        )

        tcfg = trading_config()
        open_rows = await PaperPositionStore(self._db).list_positions("open")
        if len(open_rows) >= int(tcfg["max_positions"]):
            have = any(str(r["ticker"]).upper() == symbol.upper() for r in open_rows)
            if not have:
                raise CapitalGateError(
                    "max_positions",
                    f"Already at max_positions={tcfg['max_positions']}",
                    {"open": len(open_rows)},
                )

        snap = await self._settlement.account_snapshot()
        bp = float(snap.get("buying_power") or 0)
        equity = float(snap.get("equity") or snap.get("cash") or bp or 0)
        max_sym_pct = float(tcfg.get("max_symbol_notional_pct") or tcfg.get("max_bet_pct") or 0.06)
        max_sym = equity * max_sym_pct
        if equity > 0 and notional > max_sym + 0.01:
            raise CapitalGateError(
                "symbol_exposure",
                (
                    f"Order ${notional:.2f} exceeds per-bet/symbol cap "
                    f"${max_sym:.2f} ({100 * max_sym_pct:.0f}% of equity)."
                ),
                {"notional": notional, "max_symbol": max_sym, "max_bet_pct": max_sym_pct},
            )

        wash = await self._wash.assert_buy_allowed(
            symbol, wash_override_phrase=wash_override_phrase
        )
        if not wash["allowed"]:
            raise CapitalGateError(
                "wash_sale",
                wash["block"]["message"],
                wash["block"],
            )

        if snap.get("trading_blocked") or snap.get("account_blocked"):
            raise CapitalGateError(
                "account_blocked",
                "Account trading is blocked at the broker.",
                snap,
            )
        if notional > bp + 0.01:
            raise CapitalGateError(
                "buying_power",
                (
                    f"Order ${notional:.2f} exceeds available buying power ${bp:.2f}. "
                    "Buying power uses settled cash / broker BP - unsettled sale "
                    "proceeds are not treated as immediately spendable."
                ),
                {"buying_power": bp, "notional": notional, "snapshot": snap},
            )

        return {
            "ok": True,
            "notional": round(notional, 2),
            "buying_power": bp,
            "wash_override": bool(wash.get("override")),
            "snapshot": snap,
            "safety": safety,
        }

    async def check_sell(
        self,
        *,
        symbol: str,
        qty: float,
        quote_as_of: str | None = None,
    ) -> dict[str, Any]:
        await assert_execution_allowed(
            self._db,
            symbol=symbol,
            notional=None,
            quote_as_of=quote_as_of,
            side="sell",
        )
        open_qty = await self._ledger.symbol_open_qty(symbol)
        if qty > open_qty + 1e-6:
            raise CapitalGateError(
                "insufficient_shares",
                f"Cannot sell {qty} {symbol.upper()}; open lot qty is {open_qty}",
                {"open_qty": open_qty},
            )
        return {"ok": True, "open_qty": open_qty}
