"""Behavioural tests for the public factor library.

Each factor has at least three tests covering:

* normal input,
* boundary input (exactly the minimum window length),
* insufficient input (returns ``None`` / ``False``, never raises).

Tests for as-of look-ahead protection and field-usage (close vs. adj_close)
live alongside the factor they exercise.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.strategies.factor_lib import (
    TRADING_DAYS_PER_MONTH,
    TRADING_DAYS_PER_YEAR,
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

# ---------------------------------------------------------------------------
# momentum
# ---------------------------------------------------------------------------


class TestMomentum:
    def test_positive_return_on_uptrend(self, linear_up_bars):
        result = momentum(linear_up_bars, linear_up_bars[-1].date, lookback_days=20)
        assert result is not None
        assert result > 0

    def test_zero_return_on_flat_series(self, flat_bars):
        result = momentum(flat_bars, flat_bars[-1].date, lookback_days=10)
        assert result == pytest.approx(0.0)

    def test_negative_return_on_downtrend(self, make_bar):
        bars = [
            make_bar(date(2023, 1, 1) + timedelta(days=i), close=Decimal("200") - Decimal(i))
            for i in range(50)
        ]
        result = momentum(bars, bars[-1].date, lookback_days=10)
        assert result is not None
        assert result < 0

    def test_boundary_window_exact_size_returns_value(self, linear_up_bars):
        # lookback=10 needs 11 bars (10 returns + 1 base)
        bars = linear_up_bars[:11]
        assert momentum(bars, bars[-1].date, lookback_days=10) is not None

    def test_insufficient_history_returns_none(self, linear_up_bars):
        bars = linear_up_bars[:10]
        assert momentum(bars, bars[-1].date, lookback_days=10) is None

    def test_empty_input_returns_none(self):
        assert momentum([], date(2024, 1, 1), lookback_days=10) is None

    def test_skip_recent_days_changes_window(self, linear_up_bars):
        # With skip=21 the recent month is excluded; on a perfectly linear
        # series the return should be smaller than the un-skipped variant.
        full = momentum(linear_up_bars, linear_up_bars[-1].date, lookback_days=100)
        skipped = momentum(
            linear_up_bars, linear_up_bars[-1].date, lookback_days=100, skip_recent_days=21
        )
        assert full is not None and skipped is not None
        assert skipped != pytest.approx(full)

    def test_lookahead_bars_are_dropped(self, linear_up_bars):
        as_of = linear_up_bars[100].date
        truncated_explicit = linear_up_bars[:101]
        a = momentum(linear_up_bars, as_of, lookback_days=20)
        b = momentum(truncated_explicit, as_of, lookback_days=20)
        assert a == b
        assert a is not None

    def test_invalid_lookback_raises(self, linear_up_bars):
        with pytest.raises(ValueError):
            momentum(linear_up_bars, linear_up_bars[-1].date, lookback_days=0)

    def test_invalid_skip_raises(self, linear_up_bars):
        with pytest.raises(ValueError):
            momentum(linear_up_bars, linear_up_bars[-1].date, lookback_days=10, skip_recent_days=-1)


class TestMomentumTwelveMinusOne:
    def test_returns_none_when_history_short(self, linear_up_bars):
        # Needs 12*21 + 21 + 1 = 274 bars
        bars = linear_up_bars[:200]
        assert momentum_12_1(bars, bars[-1].date) is None

    def test_returns_value_at_boundary(self, linear_up_bars):
        needed = 12 * TRADING_DAYS_PER_MONTH + TRADING_DAYS_PER_MONTH + 1
        bars = linear_up_bars[:needed]
        assert momentum_12_1(bars, bars[-1].date) is not None

    def test_positive_on_uptrend(self, linear_up_bars):
        result = momentum_12_1(linear_up_bars, linear_up_bars[-1].date)
        assert result is not None and result > 0


class TestMomentum6mAnd3m:
    def test_6m_returns_none_when_short(self, linear_up_bars):
        bars = linear_up_bars[: 6 * TRADING_DAYS_PER_MONTH]  # off by one — too short
        assert momentum_6m(bars, bars[-1].date) is None

    def test_6m_returns_value_at_boundary(self, linear_up_bars):
        bars = linear_up_bars[: 6 * TRADING_DAYS_PER_MONTH + 1]
        assert momentum_6m(bars, bars[-1].date) is not None

    def test_3m_positive_on_uptrend(self, linear_up_bars):
        result = momentum_3m(linear_up_bars, linear_up_bars[-1].date)
        assert result is not None and result > 0


# ---------------------------------------------------------------------------
# simple_moving_average / is_above_sma
# ---------------------------------------------------------------------------


class TestSimpleMovingAverage:
    def test_average_of_constant_series(self, flat_bars):
        sma = simple_moving_average(flat_bars, flat_bars[-1].date, window=10)
        assert sma == Decimal("100")

    def test_returns_decimal(self, linear_up_bars):
        sma = simple_moving_average(linear_up_bars, linear_up_bars[-1].date, window=10)
        assert isinstance(sma, Decimal)

    def test_boundary_window_size(self, linear_up_bars):
        bars = linear_up_bars[:10]
        assert simple_moving_average(bars, bars[-1].date, window=10) is not None

    def test_insufficient_returns_none(self, linear_up_bars):
        bars = linear_up_bars[:9]
        assert simple_moving_average(bars, bars[-1].date, window=10) is None

    def test_uses_close_not_adj_close(self, make_bar):
        # Build bars where close and adj_close diverge; SMA must follow close.
        bars = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100"),
                adj_close=Decimal("50"),  # adjusted is half
            )
            for i in range(20)
        ]
        sma = simple_moving_average(bars, bars[-1].date, window=10)
        assert sma == Decimal("100")

    def test_invalid_window_raises(self, flat_bars):
        with pytest.raises(ValueError):
            simple_moving_average(flat_bars, flat_bars[-1].date, window=0)

    def test_empty_input_returns_none(self):
        assert simple_moving_average([], date(2024, 1, 1), window=5) is None


class TestIsAboveSma:
    def test_true_when_close_above_sma(self, linear_up_bars):
        # On a rising series, the latest close is above the trailing average.
        assert is_above_sma(linear_up_bars, linear_up_bars[-1].date, sma_window=20) is True

    def test_true_when_equal(self, flat_bars):
        # Constant series: latest close equals SMA → "at or above".
        assert is_above_sma(flat_bars, flat_bars[-1].date, sma_window=10) is True

    def test_false_when_below(self, make_bar):
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("200") - Decimal(i))
            for i in range(30)
        ]
        assert is_above_sma(bars, bars[-1].date, sma_window=20) is False

    def test_returns_none_when_history_short(self, linear_up_bars):
        bars = linear_up_bars[:5]
        assert is_above_sma(bars, bars[-1].date, sma_window=20) is None


# ---------------------------------------------------------------------------
# price_to_high
# ---------------------------------------------------------------------------


class TestPriceToHigh:
    def test_zero_when_at_high(self, linear_up_bars):
        # Linear up: latest close is also the trailing high.
        result = price_to_high(linear_up_bars, linear_up_bars[-1].date, lookback_days=20)
        assert result == pytest.approx(0.0)

    def test_negative_when_below_high(self, make_bar):
        # Build a hill: rise then fall.
        bars = []
        for i in range(20):
            bars.append(make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal(100 + i)))
        for i in range(10):
            bars.append(make_bar(date(2024, 1, 21) + timedelta(days=i), close=Decimal(120 - i)))
        result = price_to_high(bars, bars[-1].date, lookback_days=30)
        assert result is not None and result < 0

    def test_boundary_window(self, linear_up_bars):
        bars = linear_up_bars[:10]
        assert price_to_high(bars, bars[-1].date, lookback_days=10) is not None

    def test_insufficient_returns_none(self, linear_up_bars):
        bars = linear_up_bars[:5]
        assert price_to_high(bars, bars[-1].date, lookback_days=10) is None


# ---------------------------------------------------------------------------
# atr
# ---------------------------------------------------------------------------


class TestATR:
    def test_constant_high_low_band(self, make_bar):
        # Each bar has a 2-point HL band; ATR(period) ≈ 2.
        bars = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
            )
            for i in range(20)
        ]
        result = atr(bars, bars[-1].date, period=14)
        assert result == Decimal("2")

    def test_returns_decimal(self, linear_up_bars):
        result = atr(linear_up_bars, linear_up_bars[-1].date, period=14)
        assert isinstance(result, Decimal)

    def test_boundary_window(self, linear_up_bars):
        # period=5 needs 6 bars
        bars = linear_up_bars[:6]
        assert atr(bars, bars[-1].date, period=5) is not None

    def test_insufficient_returns_none(self, linear_up_bars):
        bars = linear_up_bars[:5]
        assert atr(bars, bars[-1].date, period=5) is None

    def test_invalid_period_raises(self, flat_bars):
        with pytest.raises(ValueError):
            atr(flat_bars, flat_bars[-1].date, period=0)

    def test_uses_raw_high_low_close(self, make_bar):
        # adj_close is irrelevant; ATR depends only on raw HLC.
        bars_a = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100"),
                high=Decimal("103"),
                low=Decimal("97"),
                adj_close=Decimal("100"),
            )
            for i in range(20)
        ]
        bars_b = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100"),
                high=Decimal("103"),
                low=Decimal("97"),
                adj_close=Decimal("50"),  # different adj
            )
            for i in range(20)
        ]
        assert atr(bars_a, bars_a[-1].date) == atr(bars_b, bars_b[-1].date)


# ---------------------------------------------------------------------------
# relative_strength
# ---------------------------------------------------------------------------


class TestRelativeStrength:
    def test_outperforming_stock_positive(self, make_bar):
        stock = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100") + Decimal(i))
            for i in range(30)
        ]
        bench = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100") + Decimal(str(i * 0.1)),
                code="BENCH",
            )
            for i in range(30)
        ]
        result = relative_strength(stock, bench, stock[-1].date, lookback_days=20)
        assert result is not None and result > 0

    def test_underperforming_stock_negative(self, make_bar):
        bench = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100") + Decimal(i))
            for i in range(30)
        ]
        stock = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100") + Decimal(str(i * 0.1)),
            )
            for i in range(30)
        ]
        result = relative_strength(stock, bench, stock[-1].date, lookback_days=20)
        assert result is not None and result < 0

    def test_short_benchmark_returns_none(self, linear_up_bars, make_bar):
        bench = [make_bar(date(2024, 1, 1), close=Decimal("100"))]
        assert (
            relative_strength(linear_up_bars, bench, linear_up_bars[-1].date, lookback_days=10)
            is None
        )

    def test_short_stock_returns_none(self, linear_up_bars, make_bar):
        stock = [make_bar(date(2024, 1, 1), close=Decimal("100"))]
        assert (
            relative_strength(stock, linear_up_bars, linear_up_bars[-1].date, lookback_days=10)
            is None
        )


# ---------------------------------------------------------------------------
# volume_breakout
# ---------------------------------------------------------------------------


class TestVolumeBreakout:
    def test_true_when_recent_surge(self, make_bar):
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100"), volume=1_000_000)
            for i in range(60)
        ]
        bars += [
            make_bar(date(2024, 3, 1) + timedelta(days=i), close=Decimal("100"), volume=3_000_000)
            for i in range(20)
        ]
        assert volume_breakout(bars, bars[-1].date, recent_window=20, history_window=60) is True

    def test_false_when_recent_quiet(self, make_bar):
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100"), volume=2_000_000)
            for i in range(60)
        ]
        bars += [
            make_bar(date(2024, 3, 1) + timedelta(days=i), close=Decimal("100"), volume=500_000)
            for i in range(20)
        ]
        assert volume_breakout(bars, bars[-1].date) is False

    def test_short_history_returns_false(self, make_bar):
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100"), volume=1_000_000)
            for i in range(10)
        ]
        assert volume_breakout(bars, bars[-1].date) is False

    def test_boundary_history(self, make_bar):
        # exactly 80 bars (recent=20, history=60); first 60 quiet, last 20 surge
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100"), volume=1_000_000)
            for i in range(60)
        ]
        bars += [
            make_bar(date(2024, 3, 1) + timedelta(days=i), close=Decimal("100"), volume=2_000_000)
            for i in range(20)
        ]
        assert volume_breakout(bars, bars[-1].date) is True

    def test_threshold_kwarg(self, make_bar):
        # 1.2x recent volume — fails default 1.5x threshold but passes when relaxed.
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100"), volume=1_000_000)
            for i in range(60)
        ]
        bars += [
            make_bar(date(2024, 3, 1) + timedelta(days=i), close=Decimal("100"), volume=1_200_000)
            for i in range(20)
        ]
        assert volume_breakout(bars, bars[-1].date) is False
        assert volume_breakout(bars, bars[-1].date, threshold=1.1) is True

    def test_invalid_window_raises(self, flat_bars):
        with pytest.raises(ValueError):
            volume_breakout(flat_bars, flat_bars[-1].date, recent_window=0)


# ---------------------------------------------------------------------------
# realized_volatility
# ---------------------------------------------------------------------------


class TestRealizedVolatility:
    def test_zero_on_flat_series(self, flat_bars):
        result = realized_volatility(flat_bars, flat_bars[-1].date, lookback_days=20)
        assert result == pytest.approx(0.0, abs=1e-12)

    def test_positive_on_volatile_series(self, make_bar):
        # Alternating up / down 5% bars → non-trivial vol.
        prices = [Decimal("100")]
        for i in range(50):
            mult = Decimal("1.05") if i % 2 == 0 else Decimal("1") / Decimal("1.05")
            prices.append(prices[-1] * mult)
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=p, adj_close=p)
            for i, p in enumerate(prices)
        ]
        result = realized_volatility(bars, bars[-1].date, lookback_days=30)
        assert result is not None and result > 0

    def test_annualized_scales_correctly(self, make_bar):
        prices = [Decimal("100")]
        for i in range(50):
            mult = Decimal("1.02") if i % 2 == 0 else Decimal("1") / Decimal("1.02")
            prices.append(prices[-1] * mult)
        bars = [
            make_bar(date(2024, 1, 1) + timedelta(days=i), close=p, adj_close=p)
            for i, p in enumerate(prices)
        ]
        daily = realized_volatility(bars, bars[-1].date, lookback_days=30, annualize=False)
        annual = realized_volatility(bars, bars[-1].date, lookback_days=30, annualize=True)
        assert daily is not None and annual is not None
        assert annual == pytest.approx(daily * math.sqrt(TRADING_DAYS_PER_YEAR))

    def test_boundary_window(self, linear_up_bars):
        bars = linear_up_bars[:11]  # 10 returns require 11 bars
        assert realized_volatility(bars, bars[-1].date, lookback_days=10) is not None

    def test_insufficient_returns_none(self, linear_up_bars):
        bars = linear_up_bars[:10]
        assert realized_volatility(bars, bars[-1].date, lookback_days=10) is None

    def test_invalid_lookback_raises(self, flat_bars):
        with pytest.raises(ValueError):
            realized_volatility(flat_bars, flat_bars[-1].date, lookback_days=1)

    def test_uses_adj_close(self, make_bar):
        # Two series with identical adj_close but different raw close should give
        # identical vol — that proves the function reads adj_close, not close.
        adj_prices = [Decimal("100")]
        for i in range(20):
            mult = Decimal("1.03") if i % 2 == 0 else Decimal("1") / Decimal("1.03")
            adj_prices.append(adj_prices[-1] * mult)

        bars_a = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("100"),
                adj_close=p,
            )
            for i, p in enumerate(adj_prices)
        ]
        bars_b = [
            make_bar(
                date(2024, 1, 1) + timedelta(days=i),
                close=Decimal("999"),
                adj_close=p,
            )
            for i, p in enumerate(adj_prices)
        ]
        assert realized_volatility(bars_a, bars_a[-1].date, lookback_days=15) == pytest.approx(
            realized_volatility(bars_b, bars_b[-1].date, lookback_days=15)
        )


# ---------------------------------------------------------------------------
# look-ahead defense (cross-cutting)
# ---------------------------------------------------------------------------


def test_future_bars_dropped_for_momentum(make_bar):
    """Bars after as_of must not affect momentum."""
    base = [
        make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100") + Decimal(i))
        for i in range(20)
    ]
    future_bars = base + [
        make_bar(date(2024, 1, 21) + timedelta(days=i), close=Decimal("999")) for i in range(5)
    ]
    as_of = date(2024, 1, 20)
    assert momentum(base, as_of, lookback_days=5) == momentum(future_bars, as_of, lookback_days=5)


def test_future_bars_dropped_for_sma(make_bar):
    base = [make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100")) for i in range(15)]
    future_bars = base + [
        make_bar(date(2024, 1, 16) + timedelta(days=i), close=Decimal("500")) for i in range(5)
    ]
    as_of = date(2024, 1, 15)
    assert simple_moving_average(base, as_of, window=10) == simple_moving_average(
        future_bars, as_of, window=10
    )


def test_unsorted_input_handled(make_bar):
    """Shuffled bars give the same answer as sorted bars."""
    sorted_bars = [
        make_bar(date(2024, 1, 1) + timedelta(days=i), close=Decimal("100") + Decimal(i))
        for i in range(20)
    ]
    shuffled = list(reversed(sorted_bars))
    as_of = sorted_bars[-1].date
    assert momentum(sorted_bars, as_of, lookback_days=10) == momentum(
        shuffled, as_of, lookback_days=10
    )


def test_empty_inputs_safe_across_factors():
    """No factor raises on empty input."""
    d = date(2024, 1, 1)
    assert momentum([], d, lookback_days=5) is None
    assert momentum_12_1([], d) is None
    assert simple_moving_average([], d, window=5) is None
    assert is_above_sma([], d, sma_window=5) is None
    assert price_to_high([], d, lookback_days=5) is None
    assert atr([], d) is None
    assert realized_volatility([], d, lookback_days=5) is None
    assert volume_breakout([], d) is False


def test_zero_starting_price_returns_none(make_bar):
    """Defensive: a starting price of 0 (bad data) yields None, not ZeroDivision."""
    bars = [
        make_bar(date(2024, 1, 1), close=Decimal("0"), adj_close=Decimal("0")),
    ] + [
        make_bar(
            date(2024, 1, 1) + timedelta(days=i), close=Decimal("100"), adj_close=Decimal("100")
        )
        for i in range(1, 20)
    ]
    # 20 bars; lookback=19 makes start_idx = 0 (the zero-price bar).
    assert momentum(bars, bars[-1].date, lookback_days=19) is None
