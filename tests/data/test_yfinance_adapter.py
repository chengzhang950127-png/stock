"""Tests for the YFinance adapter — yfinance itself is mocked out."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.contracts import Currency, Market
from src.data.cache import clear_cache
from src.data.yfinance_adapter import (
    DataFetchError,
    YFinanceAdapter,
    _normalise_history,
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
async def test_fetch_price_bars_raises_after_retries(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)

    adapter = YFinanceAdapter(max_attempts=2, base_delay=0.0)

    def always_fail(code: str, start: str, end: str) -> pd.DataFrame:
        raise RuntimeError("permanent failure")

    with (
        patch.object(YFinanceAdapter, "_download_history", staticmethod(always_fail)),
        pytest.raises(DataFetchError),
    ):
        await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))


@pytest.mark.asyncio
async def test_fetch_price_bars_cached_skips_http(
    monkeypatch: pytest.MonkeyPatch, cache_dir: Path
) -> None:
    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)
    clear_cache(cache_dir=cache_dir)

    adapter = YFinanceAdapter(max_attempts=3, base_delay=0.0)
    calls = {"n": 0}

    def counting(code: str, start: str, end: str) -> pd.DataFrame:
        calls["n"] += 1
        return _fake_history_df()

    with patch.object(YFinanceAdapter, "_download_history", staticmethod(counting)):
        await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))
        await adapter.fetch_price_bars("SPY", date(2024, 1, 2), date(2024, 1, 4))
    assert calls["n"] == 1, "cached call must not re-issue the HTTP request"


def test_invalid_date_range_raises() -> None:
    adapter = YFinanceAdapter()
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(adapter.fetch_price_bars("SPY", date(2024, 2, 1), date(2024, 1, 1)))
