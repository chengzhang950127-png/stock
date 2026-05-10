"""Slippage and commission unit tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.backtest.execution import apply_slippage, calculate_fee
from src.contracts import SignalDirection

# ---- Slippage ----


def test_buy_slippage_increases_price() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.BUY, slippage_bps=5.0)
    # 5 bps = 0.05% → 100 * 1.0005 = 100.05
    assert fill == Decimal("100.0500")


def test_sell_slippage_reduces_price() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.SELL, slippage_bps=5.0)
    assert fill == Decimal("99.9500")


def test_hold_returns_unchanged_price() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.HOLD, slippage_bps=5.0)
    assert fill == Decimal("100.00")


def test_zero_slippage_is_identity_for_buy() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.BUY, slippage_bps=0.0)
    assert fill == Decimal("100.0000")


def test_negative_slippage_is_rejected() -> None:
    with pytest.raises(ValueError, match="slippage_bps must be non-negative"):
        apply_slippage(Decimal("100"), SignalDirection.BUY, slippage_bps=-1.0)


def test_non_positive_intended_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="intended_price must be positive"):
        apply_slippage(Decimal("0"), SignalDirection.BUY, slippage_bps=5.0)
    with pytest.raises(ValueError, match="intended_price must be positive"):
        apply_slippage(Decimal("-5"), SignalDirection.BUY, slippage_bps=5.0)


def test_large_slippage_buy_is_well_defined() -> None:
    """100 bps = 1% — used as a stress-test value, not a realistic one."""
    fill = apply_slippage(Decimal("200"), SignalDirection.BUY, slippage_bps=100.0)
    assert fill == Decimal("202.0000")


# ---- Fees ----


def test_fee_uses_minimum_when_proportional_is_smaller() -> None:
    fee = calculate_fee(
        shares=Decimal("10"),
        fee_per_share=Decimal("0.005"),
        min_fee=Decimal("1.00"),
    )
    # proportional = 0.05; min_fee = 1.00 → 1.00
    assert fee == Decimal("1.00")


def test_fee_uses_proportional_when_above_minimum() -> None:
    fee = calculate_fee(
        shares=Decimal("1000"),
        fee_per_share=Decimal("0.005"),
        min_fee=Decimal("1.00"),
    )
    # proportional = 5.00; min_fee = 1.00 → 5.00
    assert fee == Decimal("5.00")


def test_fee_at_threshold_returns_minimum() -> None:
    """Edge case where proportional == min_fee exactly."""
    fee = calculate_fee(
        shares=Decimal("200"),
        fee_per_share=Decimal("0.005"),
        min_fee=Decimal("1.00"),
    )
    assert fee == Decimal("1.00")


def test_fee_with_zero_shares_returns_minimum() -> None:
    fee = calculate_fee(
        shares=Decimal("0"),
        fee_per_share=Decimal("0.005"),
        min_fee=Decimal("1.00"),
    )
    assert fee == Decimal("1.00")


def test_fee_rejects_negative_shares() -> None:
    with pytest.raises(ValueError, match="shares must be non-negative"):
        calculate_fee(Decimal("-1"), Decimal("0.005"), Decimal("1.00"))


def test_fee_rejects_negative_fee_per_share() -> None:
    with pytest.raises(ValueError, match="fee_per_share must be non-negative"):
        calculate_fee(Decimal("100"), Decimal("-0.005"), Decimal("1.00"))


def test_fee_rejects_negative_min_fee() -> None:
    with pytest.raises(ValueError, match="min_fee must be non-negative"):
        calculate_fee(Decimal("100"), Decimal("0.005"), Decimal("-1.00"))


def test_fee_quantizes_to_cent() -> None:
    """Decimal output is rounded to two places — cumulative drift would
    otherwise diverge from broker statements."""
    fee = calculate_fee(
        shares=Decimal("333"),
        fee_per_share=Decimal("0.005"),
        min_fee=Decimal("1.00"),
    )
    # proportional = 1.665 → 1.67 (ROUND_HALF_UP)
    assert fee == Decimal("1.67")
