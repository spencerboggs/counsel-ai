"""Optional Alpaca broker adapter. Paper uses paper endpoints; live is gated."""

from __future__ import annotations

from typing import Any

import httpx

from backend.config.secrets import SecretsFile, load_secrets


ALPACA_PAPER = "https://paper-api.alpaca.markets"
ALPACA_LIVE = "https://api.alpaca.markets"


class AlpacaClient:
    def __init__(self, *, live: bool = False) -> None:
        secrets = load_secrets()
        self.live = live
        if live:
            self.key = secrets.alpaca_live_key or ""
            self.secret = secrets.alpaca_live_secret or ""
            self.base = ALPACA_LIVE
        else:
            self.key = secrets.alpaca_paper_key or ""
            self.secret = secrets.alpaca_paper_secret or ""
            self.base = ALPACA_PAPER

    @property
    def configured(self) -> bool:
        return bool(self.key and self.secret)

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
        }

    async def get_account(self) -> dict[str, Any] | None:
        if not self.configured:
            return None
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self.base}/v2/account",
                headers=self._headers(),
            )
            if response.status_code >= 400:
                return {"error": response.text, "status": response.status_code}
            return response.json()

    async def get_positions(self) -> list[dict[str, Any]] | dict[str, Any]:
        if not self.configured:
            return {"error": "Alpaca keys not configured"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.base}/v2/positions",
                headers=self._headers(),
            )
            if response.status_code >= 400:
                return {"error": response.text, "status": response.status_code}
            data = response.json()
            return data if isinstance(data, list) else []

    async def get_orders(self, *, status: str = "open", limit: int = 50) -> list[dict[str, Any]] | dict[str, Any]:
        if not self.configured:
            return {"error": "Alpaca keys not configured"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.base}/v2/orders",
                headers=self._headers(),
                params={"status": status, "limit": limit, "direction": "desc"},
            )
            if response.status_code >= 400:
                return {"error": response.text, "status": response.status_code}
            data = response.json()
            return data if isinstance(data, list) else []

    async def get_portfolio_history(
        self,
        *,
        period: str = "1M",
        timeframe: str = "1D",
    ) -> dict[str, Any]:
        """Equity curve from Alpaca (free with paper/live keys)."""
        if not self.configured:
            return {"error": "Alpaca keys not configured"}
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get(
                f"{self.base}/v2/account/portfolio/history",
                headers=self._headers(),
                params={"period": period, "timeframe": timeframe, "extended_hours": "false"},
            )
            if response.status_code >= 400:
                return {"error": response.text, "status": response.status_code}
            return response.json()

    async def monitor_snapshot(self) -> dict[str, Any]:
        """Combined free broker monitor for paper or live."""
        if not self.configured:
            return {
                "configured": False,
                "live": self.live,
                "note": "Add free Alpaca paper keys in Settings to monitor broker portfolio.",
            }
        account = await self.get_account()
        positions = await self.get_positions()
        orders = await self.get_orders(status="open", limit=30)
        history = await self.get_portfolio_history(period="1M", timeframe="1D")
        pos_list = positions if isinstance(positions, list) else []
        ord_list = orders if isinstance(orders, list) else []
        return {
            "configured": True,
            "live": self.live,
            "venue": "live_alpaca" if self.live else "paper_alpaca",
            "account": account,
            "positions": pos_list,
            "open_orders": ord_list,
            "portfolio_history": history if "error" not in (history or {}) else None,
            "portfolio_history_error": (history or {}).get("error"),
            "counts": {
                "positions": len(pos_list),
                "open_orders": len(ord_list),
            },
            "note": "Alpaca paper API is free with user keys. No paid market-data plan required for account/positions.",
        }

    async def submit_market_order(
        self,
        ticker: str,
        qty: float,
        *,
        side: str = "buy",
    ) -> dict[str, Any]:
        if not self.configured:
            return {"error": "Alpaca keys not configured"}
        # Whole shares only - many symbols are not fractionable on Alpaca.
        whole = int(qty)
        if whole < 1:
            return {"error": "Order requires at least 1 whole share", "http_status": 400}
        body = {
            "symbol": ticker.upper(),
            "qty": str(whole),
            "side": side,
            "type": "market",
            "time_in_force": "day",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base}/v2/orders",
                headers=self._headers(),
                json=body,
            )
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text}
            payload["http_status"] = response.status_code
            return payload


def active_trading_backend() -> str:
    secrets = load_secrets()
    if (
        secrets.trading_mode == "live_alpaca"
        and secrets.live_trading_confirmed
        and secrets.alpaca_live_key
        and secrets.alpaca_live_secret
    ):
        return "live_alpaca"
    if (
        secrets.trading_mode == "paper_alpaca"
        and secrets.alpaca_paper_key
        and secrets.alpaca_paper_secret
    ):
        return "paper_alpaca"
    return "paper_local"
