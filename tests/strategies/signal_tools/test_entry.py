"""Tests for entry-price tools.

Each function exercises: typical input, boundary case, Decimal precision,
and input-validation errors. Real-ish AAPL-range prices keep assertions
human-readable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.strategies.signal_tools.entry import (
    buy_range_from_atr,
    buy_range_from_pullback,
    buy_range_from_support,
)

# ---------- buy_range_from_atr ----------


def test_buy_range_from_atr_default_multipliers():
    low, high = buy_range_from_atr(Decimal("175"), Decimal("3.5"))
    assert (low, high) == (Decimal("169.75"), Decimal("173.25"))


def test_buy_range_from_atr_zero_atr_collapses_to_current_price():
    low, high = buy_range_from_atr(Decimal("100"), Decimal("0"))
    assert low == high == Decimal("100")


def test_buy_range_from_atr_preserves_decimal_precision():
    # 1.05 * 100 should stay exact, not drift to 105.0000001 like float would.
    low, high = buy_range_from_atr(
        Decimal("100.00"),
        Decimal("1.05"),
        atr_multiplier_low=1.0,
        atr_multiplier_high=2.0,
    )
    assert low == Decimal("97.90")
    assert high == Decimal("98.95")


def test_buy_range_from_atr_returns_strictly_ascending():
    low, high = buy_range_from_atr(
        Decimal("200"),
        Decimal("4"),
        atr_multiplier_low=0.25,
        atr_multiplier_high=2.0,
    )
    assert low < high


def test_buy_range_from_atr_rejects_non_positive_price():
    with pytest.raises(ValueError, match="current_price"):
        buy_range_from_atr(Decimal("0"), Decimal("3.5"))


def test_buy_range_from_atr_rejects_negative_atr():
    with pytest.raises(ValueError, match="atr_value"):
        buy_range_from_atr(Decimal("100"), Decimal("-1"))


def test_buy_range_from_atr_rejects_inverted_multipliers():
    with pytest.raises(ValueError, match="atr_multiplier_low"):
        buy_range_from_atr(
            Decimal("100"),
            Decimal("3"),
            atr_multiplier_low=2.0,
            atr_multiplier_high=1.0,
        )


# ---------- buy_range_from_support ----------


def test_buy_range_from_support_picks_minimum_in_window():
    lows = [Decimal("170"), Decimal("168"), Decimal("172"), Decimal("169")]
    low, high = buy_range_from_support(Decimal("175"), lows, window=4)
    assert low == Decimal("168")
    assert high == Decimal("171.36")


def test_buy_range_from_support_window_truncates_to_recent():
    lows = [Decimal("150"), Decimal("160"), Decimal("170"), Decimal("180")]
    # Only the last 2 -> min == 170
    low, _ = buy_range_from_support(Decimal("200"), lows, window=2)
    assert low == Decimal("170")


def test_buy_range_from_support_window_larger_than_history_uses_all():
    lows = [Decimal("160"), Decimal("155")]
    low, _ = buy_range_from_support(Decimal("200"), lows, window=20)
    assert low == Decimal("155")


def test_buy_range_from_support_rejects_empty_lows():
    with pytest.raises(ValueError, match="recent_lows"):
        buy_range_from_support(Decimal("100"), [], window=20)


def test_buy_range_from_support_rejects_non_positive_low():
    with pytest.raises(ValueError, match=r"recent_lows\[1\]"):
        buy_range_from_support(
            Decimal("100"),
            [Decimal("90"), Decimal("0")],
            window=20,
        )


def test_buy_range_from_support_rejects_zero_window():
    with pytest.raises(ValueError, match="window"):
        buy_range_from_support(Decimal("100"), [Decimal("90")], window=0)


# ---------- buy_range_from_pullback ----------


def test_buy_range_from_pullback_default_band():
    low, high = buy_range_from_pullback(Decimal("175"), Decimal("170"))
    # 170 * 0.95 .. 170 * 0.98
    assert low == Decimal("161.50")
    assert high == Decimal("166.60")


def test_buy_range_from_pullback_custom_band():
    low, high = buy_range_from_pullback(
        Decimal("100"),
        Decimal("100"),
        pullback_pct_min=0.01,
        pullback_pct_max=0.10,
    )
    assert low == Decimal("90.00")
    assert high == Decimal("99.00")


def test_buy_range_from_pullback_zero_pullback_min_keeps_high_at_sma():
    _, high = buy_range_from_pullback(
        Decimal("100"),
        Decimal("100"),
        pullback_pct_min=0.0,
        pullback_pct_max=0.05,
    )
    assert high == Decimal("100.00")


def test_buy_range_from_pullback_rejects_inverted_band():
    with pytest.raises(ValueError, match="pullback_pct_min"):
        buy_range_from_pullback(
            Decimal("100"),
            Decimal("100"),
            pullback_pct_min=0.10,
            pullback_pct_max=0.05,
        )


def test_buy_range_from_pullback_rejects_pct_out_of_unit():
    with pytest.raises(ValueError, match="pullback_pct_max"):
        buy_range_from_pullback(
            Decimal("100"),
            Decimal("100"),
            pullback_pct_max=1.5,
        )


def test_buy_range_from_pullback_rejects_non_positive_sma():
    with pytest.raises(ValueError, match="sma_value"):
        buy_range_from_pullback(Decimal("100"), Decimal("0"))
