"""Tests for the YFinance adapter — yfinance itself is mocked out."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.contracts import Currency, Market, PriceBar
from src.data.cache import clear_cache
from src.data.yfinance_adapter import (
    _BULK_CHUNK_SIZE,
    DataFetchError,
    YFinanceAdapter,
    _normalise_history,
    _normalise_history_bulk,
    _normalise_metadata,
    _to_decimal,
)


def _fake_history_df() -> pd.DataFrame:
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [471.5, 472.0, 470.8],
            "High": [473.1, 473.2, 471.5],
            "Low": [470.0, 471.0, 469.0],
            "Close": [472.6, 472.4, 470.1],
            "Adj Close": [471.0, 470.8, 468.5],
            "Volume": [10_000_000, 9_000_000, 8_500_000],
        },
        index=idx,
    )


def test_to_decimal_avoids_float_drift() -> None:
    # Decimal(0.1) leaks the IEEE-754 representation; Decimal(str(0.1)) does not.
    assert _to_decimal(0.1) == Decimal("0.1")
    assert _to_decimal(471.23) == Decimal("471.23")


def test_to_decimal_rejects_none() -> None:
    with pytest.raises(DataFetchError):
        _to_decimal(None)


def test_normalise_history_produces_price_bars() -> None:
    bars = _normalise_history("SPY", _fake_history_df())
    assert len(bars) == 3
    bar = bars[0]
    assert bar.code == "SPY"
    assert bar.market is Market.US
    assert bar.date == date(2024, 1, 2)
    assert bar.open == Decimal("471.5")
    assert bar.close == Decimal("472.6")
    assert bar.adj_close == Decimal("471.0")
    assert bar.volume == 10_000_000


def test_normalise_history_handles_multiindex_columns() -> None:
    df = _fake_history_df()
    df.columns = pd.MultiIndex.from_product([df.columns, ["SPY"]])
    bars = _normalise_history("SPY", df)
    assert len(bars) == 3
    assert bars[0].open == Decimal("471.5")


def test_normalise_metadata_fills_us_defaults() -> None:
    info = {
        "longName": "SPDR S&P 500 ETF Trust",
        "industry": "Exchange-Traded Fund",
        "marketCap": 470_000_000_000,
        "firstTradeDateEpochUtc": 728_265_600,  # 1993-01-29
    }
    stock = _normalise_metadata("SPY", info)
    assert stock.code == "SPY"
    assert stock.market is Market.US
    assert stock.currency is Currency.USD
    assert stock.name == "SPDR S&P 500 ETF Trust"
    assert stock.market_cap == Decimal("470000000000")
    assert stock.listed_date is not None


@pytest.mark.asyncio
async def test_fetch_price_bars_uses_retry(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)

    adapter = YFinanceAdapter(max_attempts=3, base_delay=0.0)

    calls = {"n": 0}

    def flaky(code: str, start: str, end: str) -> pd.DataFrame:
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("simulated network blip")
        return _fake_history_df()

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(flaky)):
        bars = await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))
    assert len(bars) == 3
    assert calls["n"] == 2  # one retry then success


@pytest.mark.asyncio
async def test_fetch_price_bars_chunk_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    """A persistently failing chunk maps every ticker in it to [] rather than
    aborting the whole universe — see _fetch_chunk_cached."""
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)

    adapter = YFinanceAdapter(max_attempts=2, base_delay=0.0)

    def always_fail(codes: list[str], start: str, end: str) -> pd.DataFrame:
        raise RuntimeError("permanent failure")

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(always_fail)):
        out = await adapter.fetch_price_bars_bulk(
            ["SPY", "QQQ"], date(2024, 1, 2), date(2024, 1, 4)
        )
    assert out == {"SPY": [], "QQQ": []}


@pytest.mark.asyncio
async def test_retry_eventually_raises_data_fetch_error() -> None:
    """The retry helper itself still raises DataFetchError after exhaustion."""
    from src.data.yfinance_adapter import _retry_async

    def always_fail() -> None:
        raise RuntimeError("nope")

    with pytest.raises(DataFetchError):
        await _retry_async(always_fail, max_attempts=2, base_delay=0.0)


@pytest.mark.asyncio
async def test_fetch_price_bars_cached_skips_http(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    from src.contracts import PriceBar

    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)

    adapter = YFinanceAdapter(max_attempts=3, base_delay=0.0)
    calls = {"n": 0}

    def counting(code: str, start: str, end: str) -> pd.DataFrame:
        calls["n"] += 1
        return _fake_history_df()

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(counting)):
        bars1 = await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))
        bars2 = await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))
    assert calls["n"] == 1, "cached call must not re-issue the HTTP request"
    # r2 fix — cache hits must return real PriceBar instances (else
    # PriceBarRepository.upsert_many crashes with AttributeError on b.code).
    assert all(isinstance(b, PriceBar) for b in bars2), (
        "cache hit must rehydrate to PriceBar, not raw dicts"
    )
    assert bars1 == bars2


def test_invalid_date_range_raises() -> None:
    adapter = YFinanceAdapter()
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(adapter.fetch_price_bars("SPY", date(2024, 2, 1), date(2024, 1, 1)))


# ---- Bulk fetch tests (Modification 2) -------------------------------------


def _fake_bulk_df(codes: list[str]) -> pd.DataFrame:
    """Construct a yfinance-shaped MultiIndex DataFrame for many tickers.

    yfinance's bulk shape is columns = MultiIndex [(field, ticker)] with the
    same date index for every ticker. NaNs fill missing data.
    """
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    data = {}
    for code_idx, code in enumerate(codes):
        base = 100.0 + code_idx * 10
        data[("Open", code)] = [base, base + 0.5, base - 0.3]
        data[("High", code)] = [base + 1.5, base + 1.7, base + 0.9]
        data[("Low", code)] = [base - 0.5, base - 0.4, base - 1.0]
        data[("Close", code)] = [base + 1.0, base + 1.2, base - 0.5]
        data[("Adj Close", code)] = [base + 0.9, base + 1.1, base - 0.6]
        data[("Volume", code)] = [1_000_000, 1_100_000, 900_000]
    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns, names=["Price", "Ticker"])
    # Reorder column levels so field is outer (matches our normaliser path).
    return df.reindex(columns=pd.MultiIndex.from_product([fields, codes]))


def test_normalise_history_bulk_splits_per_ticker() -> None:
    df = _fake_bulk_df(["SPY", "QQQ", "AAPL"])
    out = _normalise_history_bulk(["SPY", "QQQ", "AAPL"], df)
    assert set(out.keys()) == {"SPY", "QQQ", "AAPL"}
    for code in ("SPY", "QQQ", "AAPL"):
        assert len(out[code]) == 3
        assert all(isinstance(b, PriceBar) for b in out[code])
        assert all(b.code == code for b in out[code])
        assert all(b.market is Market.US for b in out[code])


def test_normalise_history_bulk_missing_ticker_maps_to_empty() -> None:
    df = _fake_bulk_df(["SPY", "QQQ"])
    out = _normalise_history_bulk(["SPY", "QQQ", "MISSING"], df)
    assert len(out["SPY"]) == 3
    assert len(out["QQQ"]) == 3
    assert out["MISSING"] == []


def test_bulk_chunk_size_constant_is_reasonable() -> None:
    # If someone bumps this to >100 the per-chunk failure blast radius and
    # response-shape brittleness make the fix worthless. Pin a sane ceiling.
    assert 5 <= _BULK_CHUNK_SIZE <= 50


@pytest.mark.asyncio
async def test_fetch_price_bars_bulk_one_chunk(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)
    adapter = YFinanceAdapter(max_attempts=2, base_delay=0.0)

    calls: list[list[str]] = []

    def fake_download(codes: list[str], start: str, end: str) -> pd.DataFrame:
        # codes arrives as a list when bulk path is taken
        assert isinstance(codes, list)
        calls.append(list(codes))
        return _fake_bulk_df(list(codes))

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(fake_download)):
        out = await adapter.fetch_price_bars_bulk(
            ["SPY", "QQQ", "AAPL"], date(2024, 1, 2), date(2024, 1, 4)
        )

    assert len(calls) == 1, "three tickers must fit in a single chunk → one HTTP call"
    assert sorted(calls[0]) == ["AAPL", "QQQ", "SPY"]
    assert set(out.keys()) == {"SPY", "QQQ", "AAPL"}
    assert all(len(out[c]) == 3 for c in out)


@pytest.mark.asyncio
async def test_fetch_price_bars_bulk_chunks_large_universe(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)
    adapter = YFinanceAdapter(max_attempts=2, base_delay=0.0)

    universe = [f"T{i:03d}" for i in range(60)]
    chunks_seen: list[list[str]] = []

    def fake_download(codes: list[str], start: str, end: str) -> pd.DataFrame:
        chunks_seen.append(list(codes))
        return _fake_bulk_df(list(codes))

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(fake_download)):
        out = await adapter.fetch_price_bars_bulk(universe, date(2024, 1, 2), date(2024, 1, 4))

    expected_chunks = -(-len(universe) // _BULK_CHUNK_SIZE)
    assert len(chunks_seen) == expected_chunks, (
        f"60 tickers with chunk size {_BULK_CHUNK_SIZE} should make {expected_chunks} HTTP calls, "
        f"got {len(chunks_seen)}"
    )
    # Every requested code must show up in the result, none missing.
    assert set(out.keys()) == set(universe)
    # And each chunk must respect the size cap.
    assert all(len(c) <= _BULK_CHUNK_SIZE for c in chunks_seen)


@pytest.mark.asyncio
async def test_fetch_price_bars_bulk_partial_failure(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    """One ticker missing from response → that ticker maps to [], others fine."""
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)
    adapter = YFinanceAdapter(max_attempts=2, base_delay=0.0)

    def fake_download(codes: list[str], start: str, end: str) -> pd.DataFrame:
        # Drop "BADTICKER" from the response.
        present = [c for c in codes if c != "BADTICKER"]
        return _fake_bulk_df(present)

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(fake_download)):
        out = await adapter.fetch_price_bars_bulk(
            ["SPY", "BADTICKER", "QQQ"], date(2024, 1, 2), date(2024, 1, 4)
        )

    assert len(out["SPY"]) == 3
    assert len(out["QQQ"]) == 3
    assert out["BADTICKER"] == []


@pytest.mark.asyncio
async def test_fetch_price_bars_thin_wrapper_uses_bulk(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    """The single-ticker public method is now a thin wrapper over the bulk path."""
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)
    adapter = YFinanceAdapter(max_attempts=2, base_delay=0.0)

    def fake_download(codes: list[str], start: str, end: str) -> pd.DataFrame:
        return _fake_bulk_df(list(codes))

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(fake_download)):
        bars = await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))

    assert len(bars) == 3
    assert all(isinstance(b, PriceBar) for b in bars)
    assert all(b.code == "SPY" for b in bars)
