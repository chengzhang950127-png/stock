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
from datetime import UTC, date, datetime
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

# yfinance accepts arbitrarily many tickers in one download() call but the
# response gets unwieldy past ~30 (and at ~50+ a single failed ticker
# corrupts the response shape). 25 is a good chunk size: ~5x fewer HTTP
# calls than per-ticker, with manageable failure blast radius.
_BULK_CHUNK_SIZE = 25


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

    async def fetch_price_bars(self, code: str, start: date, end: date) -> list[PriceBar]:
        """Fetch daily OHLCV bars for one ticker between ``start`` and ``end``.

        Thin wrapper over :meth:`fetch_price_bars_bulk` so single-ticker and
        bulk paths share one normalisation surface.
        """
        result = await self.fetch_price_bars_bulk([code], start, end)
        return result.get(code, [])

    async def fetch_price_bars_bulk(
        self, codes: list[str], start: date, end: date
    ) -> dict[str, list[PriceBar]]:
        """Bulk fetch OHLCV bars for many tickers between ``start`` and ``end``.

        Internally chunks ``codes`` into groups of ``_BULK_CHUNK_SIZE`` so
        individual yfinance responses stay parseable, and calls
        ``yf.download(tickers=[...])`` once per chunk. Failed chunks (after
        retries) leave the affected tickers mapped to ``[]`` rather than
        aborting the whole run.

        ``start`` / ``end`` are both inclusive — yfinance treats ``end`` as
        exclusive, so we bump it by one day so callers don't have to remember.
        """
        if start > end:
            raise ValueError(f"start ({start}) must be <= end ({end})")
        if not codes:
            return {}

        result: dict[str, list[PriceBar]] = {c: [] for c in codes}
        chunks = [codes[i : i + _BULK_CHUNK_SIZE] for i in range(0, len(codes), _BULK_CHUNK_SIZE)]
        for chunk in chunks:
            chunk_result = await self._fetch_chunk_cached(tuple(sorted(chunk)), start, end)
            for code in chunk:
                if chunk_result.get(code):
                    result[code] = chunk_result[code]
        return result

    @cached(ttl_seconds=_PRICE_TTL, namespace="YFinanceAdapter.fetch_chunk")
    async def _fetch_chunk_cached(
        self, sorted_codes: tuple[str, ...], start: date, end: date
    ) -> dict[str, list[PriceBar]]:
        """One bulk yfinance call, cached on (sorted_codes, start, end).

        Sorted tuple as cache key so two callers requesting the same chunk
        in different orders share entries. Returned shape: ``{code: bars}``.
        """
        await self._respect_rate_limit()
        from datetime import timedelta

        try:
            df = await _retry_async(
                self._download_history,
                list(sorted_codes),
                start.isoformat(),
                (end + timedelta(days=1)).isoformat(),
                max_attempts=self._max_attempts,
                base_delay=self._base_delay,
            )
        except DataFetchError as exc:
            log.warning(
                "Bulk chunk fetch failed; affected tickers map to []",
                tickers=list(sorted_codes),
                error=str(exc),
            )
            return {c: [] for c in sorted_codes}
        return _normalise_history_bulk(list(sorted_codes), df)

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
    def _download_history(codes: str | list[str], start: str, end: str) -> Any:
        # Imported inside the thread so the event loop never blocks on import.
        import yfinance as yf

        # yfinance accepts both a single code string and a list — list path
        # gives the bulk shape (MultiIndex columns: field x ticker).
        df = yf.download(
            tickers=codes,
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
    """Convert a single-ticker yfinance OHLC DataFrame to ``list[PriceBar]``.

    Columns are expected as ``Open / High / Low / Close / Adj Close / Volume``.
    Some yfinance versions wrap them in a two-level column index even for a
    single ticker — we flatten that case.
    """
    if df is None or len(df) == 0:
        return []

    if hasattr(df.columns, "levels"):
        try:
            df = df.copy()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        except Exception:
            pass

    bars: list[PriceBar] = []
    for ts, row in df.iterrows():
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


def _normalise_history_bulk(codes: list[str], df: Any) -> dict[str, list[PriceBar]]:
    """Split a multi-ticker yfinance DataFrame into per-ticker bar lists.

    yfinance returns either a flat single-ticker frame (when ``len(codes)==1``)
    or a ``MultiIndex`` frame keyed by ``(field, ticker)`` for many. This
    function handles both shapes and slices out one sub-frame per code,
    delegating to :func:`_normalise_history` for actual normalisation.

    Tickers that are missing from the response (delisted, typo, throttled
    out) map to ``[]`` — the caller decides how to surface that.
    """
    if df is None or len(df) == 0:
        return {c: [] for c in codes}

    result: dict[str, list[PriceBar]] = {}
    if hasattr(df.columns, "levels") and df.columns.nlevels == 2:
        # MultiIndex shape — could be (field, ticker) or (ticker, field).
        level0 = set(df.columns.get_level_values(0))
        ticker_level = 1 if any(t in level0 for t in ("Open", "Close")) else 0
        for code in codes:
            try:
                sub = df.xs(code, axis=1, level=ticker_level)
            except KeyError:
                result[code] = []
                continue
            sub = sub.dropna(how="all")
            result[code] = _normalise_history(code, sub)
    else:
        # Single-ticker fallback: yfinance returned a flat frame even though
        # we asked for one or more tickers (typical when len(codes)==1).
        if len(codes) == 1:
            result[codes[0]] = _normalise_history(codes[0], df)
        else:
            # Unexpected shape — log once and degrade gracefully.
            log.warning(
                "Bulk fetch returned unexpected single-level columns; "
                "falling back to first ticker only",
                requested=codes,
            )
            for code in codes:
                result[code] = _normalise_history(code, df) if code == codes[0] else []
    return result


def _normalise_metadata(code: str, info: dict[str, Any]) -> Stock:
    name = info.get("longName") or info.get("shortName") or code
    industry = info.get("industry") or info.get("sector")
    market_cap_raw = info.get("marketCap")
    market_cap = _to_decimal(market_cap_raw) if market_cap_raw not in (None, 0) else None
    listed_date: date | None = None
    first_trade = info.get("firstTradeDateEpochUtc")
    if isinstance(first_trade, (int, float)) and first_trade > 0:
        # Py 3.12 deprecates utcfromtimestamp; use the tz-aware path.
        try:
            listed_date = datetime.fromtimestamp(first_trade, tz=UTC).date()
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


__all__ = ["DataFetchError", "YFinanceAdapter", "_BULK_CHUNK_SIZE"]
