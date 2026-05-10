"""
yfinance-backed market data adapter.

Why yfinance: free, no API key, covers US equities + the ETFs the V0.1
backtest needs. Limitations (rate limits, occasional 429s, no real-time)
are acceptable for the V0.1 trend-momentum backtest. Polygon and other
paid sources land in V1.x.

Design notes
------------
* The yfinance library is sync. We call it via :func:`asyncio.to_thread`
  so the event loop stays free for concurrent fetches.
* Bulk fetches use ``yf.download(tickers=[...])`` to avoid one HTTP per
  ticker. Single-ticker fetches still go through the bulk path so the
  normalisation code stays one-shaped.
* All Decimal conversions go through ``Decimal(str(float_value))`` —
  passing the float directly preserves the float's binary drift.
* Retries are bounded (3 attempts, exponential backoff). After exhaustion
  we raise :class:`DataFetchError` so callers can surface a clear failure.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.contracts import Currency, Market, PriceBar, Stock
from src.data.cache import cached, register_model
from src.data.universe import get_us_universe

log = structlog.get_logger(__name__)

# The cache stores Pydantic models tagged by class name; register both so
# cache hits return real ``Stock`` / ``PriceBar`` instances rather than
# raw dicts. (Without this, downstream code hits AttributeError on day 2.)
register_model(Stock)
register_model(PriceBar)

_PRICE_TTL = 24 * 60 * 60
_METADATA_TTL = 7 * 24 * 60 * 60


class DataFetchError(RuntimeError):
    """Raised when an external data fetch fails after exhausting retries."""


def _to_decimal(value: Any) -> Decimal:
    """Convert yfinance floats to Decimal without preserving float drift.

    We always go via ``str()`` — ``Decimal(0.1)`` gives a 50-digit residue
    of the IEEE-754 representation, which then leaks into stored prices.
    """
    if value is None:
        raise DataFetchError("Refusing to convert None price to Decimal")
    return Decimal(str(value))


async def _retry_async(
    func: Any,
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """Call ``func`` with exponential backoff. Re-raises as DataFetchError."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "yfinance call failed; retrying",
                attempt=attempt,
                max_attempts=max_attempts,
                delay=delay,
                error=str(exc),
            )
            await asyncio.sleep(delay)
    raise DataFetchError(f"yfinance call failed after {max_attempts} attempts: {last_exc}")


class YFinanceAdapter:
    """Async wrapper around the synchronous yfinance library.

    Each public method goes through retry + caching. Cached values live
    under ``.cache/yfinance/`` (gitignored). The cache decorator excludes
    ``self`` from the cache key so multiple adapter instances share
    entries during a backfill.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        rate_limit_per_sec: float | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._rate_limit = rate_limit_per_sec
        self._last_call_at: float = 0.0
        self._rate_lock = asyncio.Lock()

    # ---- Public API ----

    @cached(ttl_seconds=_PRICE_TTL, namespace="YFinanceAdapter.fetch_price_bars")
    async def fetch_price_bars(self, code: str, start: date, end: date) -> list[PriceBar]:
        """Fetch daily OHLCV bars for ``code`` between ``start`` and ``end``.

        ``start`` / ``end`` are inclusive on the left and right per yfinance
        semantics where ``end`` is treated as exclusive — we add one day so
        callers don't have to remember.
        """
        if start > end:
            raise ValueError(f"start ({start}) must be <= end ({end})")
        await self._respect_rate_limit()
        # yfinance treats end as exclusive, so bump it.
        from datetime import timedelta

        df = await _retry_async(
            self._download_history,
            code,
            start.isoformat(),
            (end + timedelta(days=1)).isoformat(),
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
        )
        return _normalise_history(code, df)

    @cached(ttl_seconds=_METADATA_TTL, namespace="YFinanceAdapter.fetch_stock_metadata")
    async def fetch_stock_metadata(self, code: str) -> Stock:
        """Fetch static metadata for one ticker."""
        await self._respect_rate_limit()
        info = await _retry_async(
            self._fetch_info,
            code,
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
        )
        return _normalise_metadata(code, info)

    async def fetch_universe(self) -> list[Stock]:
        """Fetch metadata for every ticker in the V0.1 US universe.

        Bulk-fetches metadata one ticker at a time but in parallel batches
        so the wall-clock stays manageable for ~100 tickers. Failed
        tickers are skipped (logged) rather than aborting the whole run.
        """
        tickers = get_us_universe()
        results: list[Stock] = []

        # Resolve metadata in modest concurrency to be polite.
        sem = asyncio.Semaphore(8)

        async def one(t: str) -> Stock | None:
            async with sem:
                try:
                    return await self.fetch_stock_metadata(t)
                except DataFetchError as exc:
                    log.warning("Skipping ticker — metadata fetch failed", code=t, error=str(exc))
                    return None

        for stock in await asyncio.gather(*(one(t) for t in tickers)):
            if stock is not None:
                results.append(stock)
        return results

    # ---- Internals ----

    @staticmethod
    def _download_history(code: str, start: str, end: str) -> Any:
        # Imported inside the thread so the event loop never blocks on import.
        import yfinance as yf

        df = yf.download(
            tickers=code,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
            group_by="column",
        )
        return df

    @staticmethod
    def _fetch_info(code: str) -> dict[str, Any]:
        import yfinance as yf

        ticker = yf.Ticker(code)
        # yfinance attribute access triggers HTTP. ``.info`` returns a dict.
        info = ticker.info or {}
        return dict(info)

    async def _respect_rate_limit(self) -> None:
        if self._rate_limit is None or self._rate_limit <= 0:
            return
        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            min_gap = 1.0 / self._rate_limit
            wait = min_gap - (now - self._last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_at = asyncio.get_event_loop().time()


# ---- Normalisation helpers (module-level so they're easy to unit-test) ----


def _normalise_history(code: str, df: Any) -> list[PriceBar]:
    """Convert a yfinance OHLC DataFrame to a list of ``PriceBar``.

    yfinance has multiple shapes depending on whether you ask for one
    ticker or many; this only handles the single-ticker shape (columns
    are ``Open / High / Low / Close / Adj Close / Volume``).
    """
    if df is None or len(df) == 0:
        return []

    # Some yfinance versions (>=0.2.x) return a 2-level column index even for
    # a single ticker (top level = field, second level = ticker). Flatten it.
    if hasattr(df.columns, "levels"):
        # If the second level is a single ticker, drop it.
        try:
            df = df.copy()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        except Exception:
            pass

    bars: list[PriceBar] = []
    for ts, row in df.iterrows():
        # Pandas Timestamp -> date
        bar_date = ts.date() if hasattr(ts, "date") else ts
        try:
            close = _to_decimal(row["Close"])
            adj_close_raw = row.get("Adj Close") if hasattr(row, "get") else row["Adj Close"]
            adj_close = _to_decimal(adj_close_raw) if adj_close_raw is not None else close
            bars.append(
                PriceBar(
                    code=code,
                    market=Market.US,
                    date=bar_date,
                    open=_to_decimal(row["Open"]),
                    high=_to_decimal(row["High"]),
                    low=_to_decimal(row["Low"]),
                    close=close,
                    adj_close=adj_close,
                    volume=int(row["Volume"]) if row["Volume"] is not None else 0,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning(
                "Skipping malformed bar",
                code=code,
                date=str(bar_date),
                error=str(exc),
            )
    return bars


def _normalise_metadata(code: str, info: dict[str, Any]) -> Stock:
    name = info.get("longName") or info.get("shortName") or code
    industry = info.get("industry") or info.get("sector")
    market_cap_raw = info.get("marketCap")
    market_cap = _to_decimal(market_cap_raw) if market_cap_raw not in (None, 0) else None
    listed_date: date | None = None
    first_trade = info.get("firstTradeDateEpochUtc")
    if isinstance(first_trade, (int, float)) and first_trade > 0:
        try:
            listed_date = datetime.utcfromtimestamp(first_trade).date()
        except (OSError, OverflowError, ValueError):
            listed_date = None
    return Stock(
        code=code,
        market=Market.US,
        currency=Currency.USD,
        name=name,
        industry=industry,
        market_cap=market_cap,
        listed_date=listed_date,
    )


__all__ = ["DataFetchError", "YFinanceAdapter"]
