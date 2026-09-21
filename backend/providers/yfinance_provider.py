"""Yahoo Finance market data via yfinance.

Discovery can burn Yahoo's free rate limit quickly. This provider:
- spaces outbound calls
- caches quotes / history / financials / chart snapshots briefly
- retries transient rate limits
- surfaces rate-limit errors instead of pretending there is no data
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Any

import yfinance as yf

from backend.providers.base import HistoryBar, NewsItem, Quote


class YahooRateLimitError(RuntimeError):
    """Yahoo Finance rejected the request for requesting too often."""


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if number != number:  # NaN
            return None
        return number
    except (TypeError, ValueError):
        return None


def _news_link(entry: dict[str, Any], content: dict[str, Any]) -> str | None:
    link = entry.get("link") or entry.get("url")
    if link:
        return str(link)
    click = content.get("clickThroughUrl")
    if isinstance(click, dict) and click.get("url"):
        return str(click["url"])
    canon = content.get("canonicalUrl")
    if isinstance(canon, dict) and canon.get("url"):
        return str(canon["url"])
    return None


def _is_rate_limited(exc: BaseException) -> bool:
    name = type(exc).__name__
    text = str(exc).lower()
    return (
        "ratelimit" in name.lower()
        or "too many requests" in text
        or "rate limited" in text
        or "429" in text
    )


class _TtlCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (expires_at, value)
        self._items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if not hit:
                return None
            expires, value = hit
            if expires < now:
                return None
            return value

    def get_stale(self, key: str) -> Any | None:
        """Return value even if TTL expired (rate-limit / offline fallback)."""
        with self._lock:
            hit = self._items.get(key)
            if not hit:
                return None
            return hit[1]

    def put(self, key: str, value: Any, ttl_s: float) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + ttl_s, value)


# Process-wide so Discovery + chart share one throttle / cache.
_CACHE = _TtlCache()
_CALL_LOCK = threading.Lock()
_LAST_CALL_AT = 0.0
_MIN_CALL_GAP_S = 0.35
_QUOTE_TTL_S = 60.0
_HISTORY_TTL_S = 300.0
_FINANCIALS_TTL_S = 900.0
_CHART_TTL_S = 900.0  # 15m - bars are fine stale; protects Yahoo quota
_NEWS_TTL_S = 600.0


def _throttle() -> None:
    global _LAST_CALL_AT
    with _CALL_LOCK:
        now = time.monotonic()
        wait = _MIN_CALL_GAP_S - (now - _LAST_CALL_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL_AT = time.monotonic()


def _call_yahoo(fn, *, retries: int = 3, label: str = "yahoo"):
    """Run a Yahoo call with spacing and rate-limit retries."""
    last_exc: BaseException | None = None
    for attempt in range(retries):
        _throttle()
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if _is_rate_limited(exc):
                # Back off harder on each retry; Yahoo cool-downs are sticky.
                time.sleep(1.5 * (attempt + 1) ** 2)
                continue
            raise
    assert last_exc is not None
    if _is_rate_limited(last_exc):
        raise YahooRateLimitError(
            f"Yahoo Finance rate limit while loading {label}. "
            "Stop discovery briefly, wait ~30-60s, then refresh."
        ) from last_exc
    raise last_exc


class YFinanceProvider:
    name = "yfinance"

    async def get_quote(self, ticker: str) -> Quote:
        return await asyncio.to_thread(self._get_quote_sync, ticker)

    def _get_quote_sync(self, ticker: str) -> Quote:
        symbol = ticker.upper().strip()
        cache_key = f"quote:{symbol}"
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return cached

        def fetch() -> Quote:
            stock = yf.Ticker(symbol)
            info: dict[str, Any] = {}
            price = None
            currency = None
            prev_close = None
            day_open = None
            day_high = None
            day_low = None
            name = None
            try:
                fast = stock.fast_info
                price = _safe_float(
                    getattr(fast, "last_price", None) or getattr(fast, "lastPrice", None)
                )
                currency = getattr(fast, "currency", None)
                prev_close = _safe_float(
                    getattr(fast, "previous_close", None)
                    or getattr(fast, "previousClose", None)
                )
                day_open = _safe_float(
                    getattr(fast, "open", None) or getattr(fast, "day_open", None)
                )
                day_high = _safe_float(
                    getattr(fast, "day_high", None) or getattr(fast, "dayHigh", None)
                )
                day_low = _safe_float(
                    getattr(fast, "day_low", None) or getattr(fast, "dayLow", None)
                )
            except Exception as exc:
                if _is_rate_limited(exc):
                    raise

            try:
                raw_info = stock.info or {}
            except Exception as exc:
                if _is_rate_limited(exc):
                    raise
                raw_info = {}

            if isinstance(raw_info, dict) and raw_info:
                price = price or _safe_float(
                    raw_info.get("currentPrice") or raw_info.get("regularMarketPrice")
                )
                currency = currency or raw_info.get("currency")
                prev_close = prev_close or _safe_float(
                    raw_info.get("regularMarketPreviousClose")
                    or raw_info.get("previousClose")
                )
                day_open = day_open or _safe_float(
                    raw_info.get("regularMarketOpen") or raw_info.get("open")
                )
                day_high = day_high or _safe_float(
                    raw_info.get("regularMarketDayHigh") or raw_info.get("dayHigh")
                )
                day_low = day_low or _safe_float(
                    raw_info.get("regularMarketDayLow") or raw_info.get("dayLow")
                )
                name = raw_info.get("shortName") or raw_info.get("longName")
                info = {
                    k: raw_info.get(k)
                    for k in (
                        "currentPrice",
                        "regularMarketPrice",
                        "marketCap",
                        "trailingPE",
                        "forwardPE",
                        "priceToSalesTrailing12Months",
                        "debtToEquity",
                        "returnOnEquity",
                        "profitMargins",
                        "revenueGrowth",
                        "earningsGrowth",
                        "beta",
                        "averageVolume",
                        "sector",
                        "industry",
                        "shortName",
                        "longName",
                        "fiftyTwoWeekHigh",
                        "fiftyTwoWeekLow",
                        "dividendYield",
                    )
                    if k in raw_info
                }

            change = None
            change_pct = None
            if price is not None and prev_close not in (None, 0):
                change = round(float(price) - float(prev_close), 4)
                change_pct = round((change / float(prev_close)) * 100, 2)

            info = {
                **(info if isinstance(info, dict) else {}),
                "name": name,
                "previous_close": prev_close,
                "day_open": day_open,
                "day_high": day_high,
                "day_low": day_low,
                "change": change,
                "change_pct": change_pct,
                "market_cap": info.get("marketCap") if isinstance(info, dict) else None,
                "pe": info.get("trailingPE") if isinstance(info, dict) else None,
                "sector": info.get("sector") if isinstance(info, dict) else None,
                "industry": info.get("industry") if isinstance(info, dict) else None,
                "beta": info.get("beta") if isinstance(info, dict) else None,
                "avg_volume": info.get("averageVolume") if isinstance(info, dict) else None,
                "fifty_two_week_high": (
                    info.get("fiftyTwoWeekHigh") if isinstance(info, dict) else None
                ),
                "fifty_two_week_low": (
                    info.get("fiftyTwoWeekLow") if isinstance(info, dict) else None
                ),
            }

            return Quote(
                ticker=symbol,
                price=price,
                currency=currency,
                as_of=datetime.now(timezone.utc).isoformat(),
                raw=info,
            )

        try:
            quote = _call_yahoo(fetch, label=f"quote {symbol}")
        except YahooRateLimitError:
            stale = _CACHE.get_stale(cache_key)
            if stale is not None:
                return stale
            raise
        _CACHE.put(cache_key, quote, _QUOTE_TTL_S)
        return quote

    async def get_history(
        self,
        ticker: str,
        period: str = "1y",
        *,
        interval: str | None = None,
    ) -> list[HistoryBar]:
        return await asyncio.to_thread(
            self._get_history_sync, ticker, period, interval
        )

    def _get_history_sync(
        self,
        ticker: str,
        period: str,
        interval: str | None = None,
    ) -> list[HistoryBar]:
        symbol = ticker.upper().strip()
        cache_key = f"hist:{symbol}:{period}:{interval or 'default'}"
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return cached

        def fetch() -> list[HistoryBar]:
            kwargs: dict[str, Any] = {"period": period, "auto_adjust": True}
            if interval:
                kwargs["interval"] = interval
            frame = yf.Ticker(symbol).history(**kwargs)
            if frame is None or frame.empty:
                return []
            bars: list[HistoryBar] = []
            for idx, row in frame.iterrows():
                if hasattr(idx, "isoformat"):
                    date_str = idx.isoformat()
                elif hasattr(idx, "strftime"):
                    date_str = idx.strftime("%Y-%m-%d")
                else:
                    date_str = str(idx)
                bars.append(
                    HistoryBar(
                        date=date_str,
                        open=_safe_float(row.get("Open")),
                        high=_safe_float(row.get("High")),
                        low=_safe_float(row.get("Low")),
                        close=_safe_float(row.get("Close")),
                        volume=_safe_float(row.get("Volume")),
                    )
                )
            return bars

        try:
            bars = _call_yahoo(fetch, label=f"history {symbol}")
        except YahooRateLimitError:
            stale = _CACHE.get_stale(cache_key)
            if stale is not None:
                return list(stale)
            raise
        except Exception:
            stale = _CACHE.get_stale(cache_key)
            if stale is not None:
                return list(stale)
            return []
        _CACHE.put(cache_key, bars, _HISTORY_TTL_S)
        return bars

    async def get_chart_snapshot(self, ticker: str, range_key: str = "1mo") -> dict[str, Any]:
        """Quote + OHLCV bars for a brokerage-style chart view (free yfinance)."""
        return await asyncio.to_thread(self._get_chart_snapshot_sync, ticker, range_key)

    def get_stale_chart_snapshot(
        self, ticker: str, range_key: str = "1mo"
    ) -> dict[str, Any] | None:
        symbol = ticker.upper().strip()
        cache_key = f"chart:{symbol}:{range_key}"
        stale = _CACHE.get_stale(cache_key)
        if stale is None:
            return None
        out = dict(stale)
        out["stale"] = True
        out["source"] = "cache"
        return out

    def _get_chart_snapshot_sync(self, ticker: str, range_key: str) -> dict[str, Any]:
        symbol = ticker.upper().strip()
        cache_key = f"chart:{symbol}:{range_key}"
        cached = _CACHE.get(cache_key)
        if cached is not None:
            out = dict(cached)
            out["stale"] = False
            out["source"] = out.get("source") or "yahoo"
            return out

        ranges: dict[str, tuple[str, str | None]] = {
            "1d": ("1d", "5m"),
            "5d": ("5d", "30m"),
            "1mo": ("1mo", "1d"),
            "3mo": ("3mo", "1d"),
            "6mo": ("6mo", "1d"),
            "1y": ("1y", "1d"),
            "5y": ("5y", "1wk"),
        }
        period, interval = ranges.get(range_key, ranges["1mo"])
        try:
            bars = self._get_history_sync(symbol, period, interval)
        except YahooRateLimitError:
            stale = _CACHE.get_stale(cache_key)
            if stale is not None:
                out = dict(stale)
                out["stale"] = True
                out["source"] = "cache"
                return out
            raise

        name = None
        currency = None
        last = None
        prev_close = None
        day_open = None
        day_high = None
        day_low = None
        market_cap = None

        def load_meta() -> None:
            nonlocal name, currency, last, prev_close, day_open, day_high, day_low, market_cap
            stock = yf.Ticker(symbol)
            try:
                fast = stock.fast_info
                last = _safe_float(
                    getattr(fast, "last_price", None) or getattr(fast, "lastPrice", None)
                )
                prev_close = _safe_float(
                    getattr(fast, "previous_close", None)
                    or getattr(fast, "previousClose", None)
                )
                day_open = _safe_float(
                    getattr(fast, "open", None) or getattr(fast, "day_open", None)
                )
                day_high = _safe_float(
                    getattr(fast, "day_high", None) or getattr(fast, "dayHigh", None)
                )
                day_low = _safe_float(
                    getattr(fast, "day_low", None) or getattr(fast, "dayLow", None)
                )
                currency = getattr(fast, "currency", None)
                market_cap = _safe_float(
                    getattr(fast, "market_cap", None) or getattr(fast, "marketCap", None)
                )
            except Exception as exc:
                if _is_rate_limited(exc):
                    raise

            try:
                info = stock.info or {}
            except Exception as exc:
                if _is_rate_limited(exc):
                    raise
                info = {}
            if isinstance(info, dict):
                name = info.get("shortName") or info.get("longName") or name
                currency = currency or info.get("currency")
                last = last or _safe_float(
                    info.get("currentPrice") or info.get("regularMarketPrice")
                )
                prev_close = prev_close or _safe_float(
                    info.get("regularMarketPreviousClose") or info.get("previousClose")
                )
                day_open = day_open or _safe_float(
                    info.get("regularMarketOpen") or info.get("open")
                )
                day_high = day_high or _safe_float(
                    info.get("regularMarketDayHigh") or info.get("dayHigh")
                )
                day_low = day_low or _safe_float(
                    info.get("regularMarketDayLow") or info.get("dayLow")
                )
                market_cap = market_cap or _safe_float(info.get("marketCap"))

        try:
            _call_yahoo(load_meta, retries=3, label=f"chart meta {symbol}")
        except YahooRateLimitError:
            # Bars alone are still useful; fill last from them below.
            pass

        if last is None and bars:
            last = bars[-1].close
        if day_open is None and bars and range_key == "1d":
            day_open = bars[0].open or bars[0].close
        if day_high is None and bars and range_key == "1d":
            highs = [b.high for b in bars if b.high is not None]
            day_high = max(highs) if highs else None
        if day_low is None and bars and range_key == "1d":
            lows = [b.low for b in bars if b.low is not None]
            day_low = min(lows) if lows else None

        change = None
        change_pct = None
        if last is not None and prev_close not in (None, 0):
            change = round(last - float(prev_close), 4)
            change_pct = round((change / float(prev_close)) * 100, 2)

        range_open = bars[0].open if bars else None
        range_close = bars[-1].close if bars else last
        range_change = None
        range_change_pct = None
        if range_open and range_close and range_open != 0:
            range_change = round(float(range_close) - float(range_open), 4)
            range_change_pct = round((range_change / float(range_open)) * 100, 2)

        snapshot = {
            "ticker": symbol,
            "name": name,
            "currency": currency or "USD",
            "range": range_key,
            "period": period,
            "interval": interval or "1d",
            "last": last,
            "previous_close": prev_close,
            "day_open": day_open,
            "day_high": day_high,
            "day_low": day_low,
            "change": change,
            "change_pct": change_pct,
            "range_open": range_open,
            "range_close": range_close,
            "range_change": range_change,
            "range_change_pct": range_change_pct,
            "market_cap": market_cap,
            "bars": [
                {
                    "t": b.date,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                }
                for b in bars
            ],
            "as_of": datetime.now(timezone.utc).isoformat(),
            "stale": False,
            "source": "yahoo",
        }
        if bars or last is not None:
            _CACHE.put(cache_key, snapshot, _CHART_TTL_S)
        return snapshot

    async def get_financials(self, ticker: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_financials_sync, ticker)

    def _get_financials_sync(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.upper().strip()
        cache_key = f"fin:{symbol}"
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return dict(cached)

        def fetch() -> dict[str, Any]:
            stock = yf.Ticker(symbol)
            result: dict[str, Any] = {"ticker": symbol}
            try:
                info = stock.info or {}
            except Exception as exc:
                if _is_rate_limited(exc):
                    raise
                info = {}

            keys = [
                "marketCap",
                "enterpriseValue",
                "trailingPE",
                "forwardPE",
                "priceToBook",
                "priceToSalesTrailing12Months",
                "enterpriseToEbitda",
                "profitMargins",
                "operatingMargins",
                "grossMargins",
                "returnOnEquity",
                "returnOnAssets",
                "debtToEquity",
                "currentRatio",
                "quickRatio",
                "revenueGrowth",
                "earningsGrowth",
                "freeCashflow",
                "operatingCashflow",
                "totalRevenue",
                "ebitda",
                "totalDebt",
                "totalCash",
                "beta",
                "fiftyTwoWeekHigh",
                "fiftyTwoWeekLow",
                "averageVolume",
                "sector",
                "industry",
                "longName",
                "shortName",
            ]
            result["metrics"] = {
                k: info.get(k) for k in keys if info.get(k) is not None
            }
            return result

        try:
            result = _call_yahoo(fetch, label=f"financials {symbol}")
        except YahooRateLimitError:
            raise
        except Exception:
            result = {"ticker": symbol, "metrics": {}}
        _CACHE.put(cache_key, result, _FINANCIALS_TTL_S)
        return result

    async def get_news(self, ticker: str) -> list[NewsItem]:
        return await asyncio.to_thread(self._get_news_sync, ticker)

    def _get_news_sync(self, ticker: str) -> list[NewsItem]:
        symbol = ticker.upper().strip()
        cache_key = f"news:{symbol}"
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

        def fetch() -> list[NewsItem]:
            raw = yf.Ticker(symbol).news or []
            items: list[NewsItem] = []
            for entry in raw[:10]:
                content = (
                    entry.get("content") if isinstance(entry.get("content"), dict) else {}
                )
                title = (
                    entry.get("title")
                    or content.get("title")
                    or entry.get("headline")
                )
                if not title:
                    continue
                link = _news_link(entry, content)
                published = None
                ts = entry.get("providerPublishTime") or entry.get("pubDate")
                if isinstance(ts, (int, float)):
                    published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                elif isinstance(ts, str):
                    published = ts
                source = entry.get("publisher")
                provider = content.get("provider")
                if not source and isinstance(provider, dict):
                    source = provider.get("displayName")
                items.append(
                    NewsItem(
                        title=str(title),
                        url=str(link) if link else None,
                        published_at=published,
                        source=str(source) if source else None,
                        summary=content.get("summary")
                        if isinstance(content, dict)
                        else None,
                    )
                )
            return items

        try:
            items = _call_yahoo(fetch, label=f"news {symbol}")
        except YahooRateLimitError:
            raise
        except Exception:
            return []
        _CACHE.put(cache_key, items, _NEWS_TTL_S)
        return items
