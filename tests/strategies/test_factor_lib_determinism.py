"""Determinism tests — every factor must give bit-identical results on
two calls with the same input.

Determinism is the bedrock of backtest reproducibility. If any factor depends
on iteration order, randomness, or wall-clock time, this test catches it.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.contracts import Market, PriceBar
from src.strategies.factor_lib import (
    atr,
    is_above_sma,
    momentum,
    momentum_3m,
    momentum_6m,
    momentum_12_1,
    price_to_high,
    realized_volatility,
    relative_strength,
    simple_moving_average,
    volume_breakout,
)


def _bar(d: date, price: Decimal, *, code: str = "TEST", volume: int = 1_000_000) -> PriceBar:
    return PriceBar(
        code=code,
        market=Market.US,
        date=d,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        adj_close=price,
        volume=volume,
    )


@pytest.fixture
def long_bars() -> list[PriceBar]:
    """Long enough series (300 bars) for every factor to compute."""
    base = date(2023, 1, 2)
    return [
        _bar(base + timedelta(days=i), Decimal("100") + Decimal(i) / Decimal("10"))
        for i in range(300)
    ]


@pytest.fixture
def long_bench() -> list[PriceBar]:
    base = date(2023, 1, 2)
    return [
        _bar(base + timedelta(days=i), Decimal("200") + Decimal(i) / Decimal("20"), code="SPY")
        for i in range(300)
    ]


def test_momentum_deterministic(long_bars):
    a = momentum(long_bars, long_bars[-1].date, lookback_days=50)
    b = momentum(long_bars, long_bars[-1].date, lookback_days=50)
    assert a == b


def test_momentum_12_1_deterministic(long_bars):
    a = momentum_12_1(long_bars, long_bars[-1].date)
    b = momentum_12_1(long_bars, long_bars[-1].date)
    assert a == b


def test_momentum_6m_3m_deterministic(long_bars):
    assert momentum_6m(long_bars, long_bars[-1].date) == momentum_6m(long_bars, long_bars[-1].date)
    assert momentum_3m(long_bars, long_bars[-1].date) == momentum_3m(long_bars, long_bars[-1].date)


def test_simple_moving_average_decimal_precision(long_bars):
    a = simple_moving_average(long_bars, long_bars[-1].date, window=50)
    b = simple_moving_average(long_bars, long_bars[-1].date, window=50)
    assert a == b
    assert isinstance(a, Decimal)


def test_is_above_sma_deterministic(long_bars):
    a = is_above_sma(long_bars, long_bars[-1].date, sma_window=50)
    b = is_above_sma(long_bars, long_bars[-1].date, sma_window=50)
    assert a == b


def test_price_to_high_deterministic(long_bars):
    a = price_to_high(long_bars, long_bars[-1].date, lookback_days=60)
    b = price_to_high(long_bars, long_bars[-1].date, lookback_days=60)
    assert a == b


def test_atr_deterministic_decimal(long_bars):
    a = atr(long_bars, long_bars[-1].date, period=14)
    b = atr(long_bars, long_bars[-1].date, period=14)
    assert a == b
    assert isinstance(a, Decimal)


def test_relative_strength_deterministic(long_bars, long_bench):
    a = relative_strength(long_bars, long_bench, long_bars[-1].date, lookback_days=60)
    b = relative_strength(long_bars, long_bench, long_bars[-1].date, lookback_days=60)
    assert a == b


def test_volume_breakout_deterministic(long_bars):
    a = volume_breakout(long_bars, long_bars[-1].date)
    b = volume_breakout(long_bars, long_bars[-1].date)
    assert a == b


def test_realized_volatility_deterministic(long_bars):
    a = realized_volatility(long_bars, long_bars[-1].date, lookback_days=60)
    b = realized_volatility(long_bars, long_bars[-1].date, lookback_days=60)
    assert a == b


def test_input_order_independent(long_bars):
    """Same bars in a different order yield the same factor values."""
    shuffled = list(reversed(long_bars))
    as_of = long_bars[-1].date
    assert momentum(long_bars, as_of, lookback_days=30) == momentum(
        shuffled, as_of, lookback_days=30
    )
    assert simple_moving_average(long_bars, as_of, window=30) == simple_moving_average(
        shuffled, as_of, window=30
    )
    assert atr(long_bars, as_of, period=14) == atr(shuffled, as_of, period=14)
    assert realized_volatility(long_bars, as_of, lookback_days=30) == realized_volatility(
        shuffled, as_of, lookback_days=30
    )
