"""Coordinate gated buys/sells through the immutable ledger."""

from __future__ import annotations

from typing import Any

from backend.portfolio.capital_gate import CapitalGate, CapitalGateError
from backend.portfolio.ledger import TradeLedger
from backend.portfolio.store import PaperPositionStore
from backend.providers.alpaca import AlpacaClient, active_trading_backend
from backend.providers.yfinance_provider import YFinanceProvider
from backend.storage.database import Database


class TradeExecutor:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._ledger = TradeLedger(db)
        self._gate = CapitalGate(db)
        self._positions = PaperPositionStore(db)

    async def buy(
        self,
        *,
        ticker: str,
        shares: float,
        price: float | None = None,
        notional: float | None = None,
        source_run_id: str | None = None,
        notes: str | None = None,
        wash_override_phrase: str | None = None,
        venue: str | None = None,
        live_confirmed: bool = False,
    ) -> dict[str, Any]:
        symbol = ticker.upper().strip()
        backend = venue or active_trading_backend()
        if backend == "live_alpaca" and not live_confirmed:
            raise CapitalGateError(
                "live_confirm",
                "Live trading requires explicit confirmation on this order",
            )

        px = price
        quote_as_of = None
        try:
            quote = await YFinanceProvider().get_quote(symbol)
            quote_as_of = quote.as_of
            if px is None:
                px = quote.price
            elif quote.price and float(px) > 0 and float(quote.price) > 0:
                # Reject obviously bad passed prices vs fresh quote
                from backend.compliance.risk_gates import trading_config

                lim = float(trading_config()["reject_abnormal_price_move_pct"])
                move = abs(float(px) - float(quote.price)) / float(quote.price)
                if move > lim:
                    raise CapitalGateError(
                        "abnormal_price",
                        (
                            f"Passed price ${float(px):.2f} diverges "
                            f"{move:.0%} from quote ${float(quote.price):.2f}."
                        ),
                    )
        except CapitalGateError:
            raise
        except Exception:
            if px is None:
                raise CapitalGateError("price", "A positive price is required") from None
        if not px or px <= 0:
            raise CapitalGateError("price", "A positive price is required")

        qty = float(shares)
        if notional is not None:
            qty = float(int(notional // px))
        if qty < 1:
            raise CapitalGateError(
                "qty",
                f"Budget cannot buy 1 share at ${px:.2f}",
            )

        gate = await self._gate.check_buy(
            symbol=symbol,
            qty=qty,
            price=float(px),
            wash_override_phrase=wash_override_phrase,
            max_notional=float(notional) if notional is not None else None,
            quote_as_of=quote_as_of,
        )

        broker_ref = None
        raw: dict[str, Any] = {}
        order_notes = notes or ""

        if backend == "live_alpaca":
            client = AlpacaClient(live=True)
            if not client.configured:
                raise CapitalGateError("alpaca", "Alpaca live keys are not saved")
            result = await client.submit_market_order(symbol, qty, side="buy")
            raw = result
            if result.get("http_status", 500) >= 400 or result.get("error"):
                raise CapitalGateError("broker", f"Live order failed: {result}", result)
            broker_ref = result.get("id")
            order_notes = f"LIVE Alpaca {broker_ref}. {order_notes}".strip()
        elif backend == "paper_alpaca":
            client = AlpacaClient(live=False)
            if not client.configured:
                raise CapitalGateError("alpaca", "Alpaca paper keys are not saved")
            result = await client.submit_market_order(symbol, qty, side="buy")
            raw = result
            if result.get("http_status", 500) >= 400 or result.get("error"):
                raise CapitalGateError(
                    "broker", f"Alpaca paper order failed: {result}", result
                )
            broker_ref = result.get("id")
            order_notes = f"Alpaca PAPER {broker_ref}. {order_notes}".strip()
        else:
            order_notes = (
                order_notes or "Local paper - not sent to a broker"
            ).strip()

        order = await self._ledger.create_order(
            venue=backend,
            symbol=symbol,
            side="buy",
            qty=qty,
            status="accepted",
            broker_order_id=str(broker_ref) if broker_ref else None,
            source_run_id=source_run_id,
            notes=order_notes,
            raw=raw or None,
        )
        fill = await self._ledger.record_fill(
            order_id=order["id"],
            symbol=symbol,
            side="buy",
            qty=qty,
            price=float(px),
            fees=0.0,
            broker_fill_id=str(broker_ref) if broker_ref else None,
            raw=raw or None,
            adjust_paper_cash=(backend == "paper_local"),
            wash_override=bool(gate.get("wash_override")),
        )

        # Mirror open position row for UI compatibility.
        pos = await self._positions.open_position(
            symbol,
            qty,
            float(px),
            source_run_id=source_run_id,
            notes=order_notes,
        )
        return {
            "position": pos,
            "order": order,
            "fill": fill,
            "gate": gate,
            "realized_note": "Buy opens a tax lot; no realized gain until sell.",
        }

    async def sell(
        self,
        *,
        position_id: str | None = None,
        ticker: str | None = None,
        shares: float | None = None,
        price: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        backend = active_trading_backend()
        row = None
        if position_id:
            row = await self._positions.get(position_id)
            if row is None or row["status"] != "open":
                raise CapitalGateError("position", "Open paper position not found")
            symbol = str(row["ticker"]).upper()
            qty = float(shares if shares is not None else row["shares"])
        else:
            if not ticker or shares is None:
                raise CapitalGateError("position", "ticker and shares required")
            symbol = ticker.upper()
            qty = float(shares)

        px = price
        quote_as_of = None
        if px is None:
            quote = await YFinanceProvider().get_quote(symbol)
            px = quote.price
            quote_as_of = quote.as_of
        if not px or px <= 0:
            # Fall back to cost if quote fails for close
            if row:
                px = float(row["cost_basis"])
            else:
                raise CapitalGateError("price", "Could not price sell")

        await self._gate.check_sell(symbol=symbol, qty=qty, quote_as_of=quote_as_of)

        broker_ref = None
        raw: dict[str, Any] = {}
        if backend in {"paper_alpaca", "live_alpaca"}:
            client = AlpacaClient(live=backend == "live_alpaca")
            result = await client.submit_market_order(symbol, qty, side="sell")
            raw = result
            broker_ref = result.get("id")

        order = await self._ledger.create_order(
            venue=backend,
            symbol=symbol,
            side="sell",
            qty=qty,
            status="accepted",
            broker_order_id=str(broker_ref) if broker_ref else None,
            notes=notes or "Close / sell",
            raw=raw or None,
        )
        fill = await self._ledger.record_fill(
            order_id=order["id"],
            symbol=symbol,
            side="sell",
            qty=qty,
            price=float(px),
            fees=0.0,
            broker_fill_id=str(broker_ref) if broker_ref else None,
            raw=raw or None,
            adjust_paper_cash=(backend == "paper_local"),
        )

        closed = None
        if position_id:
            closed = await self._positions.close_position(position_id)

        realized = sum(
            float(d.get("realized_gain") or 0) for d in (fill.get("dispositions") or [])
        )
        return {
            "position": closed,
            "order": order,
            "fill": fill,
            "realized_gain": round(realized, 2),
            "note": "Tax is on realized profit, not sale proceeds.",
        }
