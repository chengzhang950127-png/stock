"""Slippage + commission + ExecutionCostModel currency unit tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.backtest.execution import (
    US_DEFAULT_COST,
    ExecutionCostModel,
    apply_slippage,
    calculate_fee,
)
from src.contracts import Currency, SignalDirection

# ---- ExecutionCostModel ----


def test_us_default_cost_has_usd_currency() -> None:
    assert US_DEFAULT_COST.currency == Currency.USD
    assert US_DEFAULT_COST.slippage_bps == 5.0
    assert US_DEFAULT_COST.fee_per_share == Decimal("0.005")
    assert US_DEFAULT_COST.min_fee == Decimal("1.0")


def test_execution_cost_model_is_frozen() -> None:
    """Frozen dataclass — strategies can't mutate the cost model."""
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        US_DEFAULT_COST.slippage_bps = 10.0  # type: ignore[misc]


# ---- Slippage ----


def test_buy_slippage_increases_price() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.BUY, slippage_bps=5.0)
    assert fill == Decimal("100.0500")


def test_sell_slippage_reduces_price_via_symmetric_division() -> None:
    """SELL uses intended/(1+bps) — symmetric to BUY's *(1+bps)."""
    fill = apply_slippage(Decimal("100.00"), SignalDirection.SELL, slippage_bps=5.0)
    # 100 / 1.0005 = 99.9500...
    assert fill == Decimal("99.9500")


def test_hold_returns_unchanged_price() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.HOLD, slippage_bps=5.0)
    assert fill == Decimal("100.00")


def test_zero_slippage_is_identity() -> None:
    fill = apply_slippage(Decimal("100.00"), SignalDirection.BUY, slippage_bps=0.0)
    assert fill == Decimal("100.0000")


def test_negative_slippage_is_rejected() -> None:
    with pytest.raises(ValueError, match="slippage_bps must be non-negative"):
        apply_slippage(Decimal("100"), SignalDirection.BUY, slippage_bps=-1.0)


def test_non_positive_intended_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="intended_price must be positive"):
        apply_slippage(Decimal("0"), SignalDirection.BUY, slippage_bps=5.0)


def test_buy_pays_more_than_sell_receives_for_same_intended() -> None:
    """Round-trip BUY-then-SELL at the same intended_price must lose money
    to slippage — this is the realism check."""
    intended = Decimal("100")
    buy_fill = apply_slippage(intended, SignalDirection.BUY, slippage_bps=10.0)
    sell_fill = apply_slippage(intended, SignalDirection.SELL, slippage_bps=10.0)
    assert buy_fill > sell_fill


# ---- Fees ----


def test_fee_uses_minimum_when_proportional_is_smaller() -> None:
    fee = calculate_fee(Decimal("10"), Decimal("0.005"), Decimal("1.00"))
    assert fee == Decimal("1.00")


def test_fee_uses_proportional_when_above_minimum() -> None:
    fee = calculate_fee(Decimal("1000"), Decimal("0.005"), Decimal("1.00"))
    assert fee == Decimal("5.00")


def test_fee_at_threshold_returns_minimum() -> None:
    fee = calculate_fee(Decimal("200"), Decimal("0.005"), Decimal("1.00"))
    assert fee == Decimal("1.00")


def test_fee_with_zero_shares_returns_minimum() -> None:
    fee = calculate_fee(Decimal("0"), Decimal("0.005"), Decimal("1.00"))
    assert fee == Decimal("1.00")


def test_fee_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        calculate_fee(Decimal("-1"), Decimal("0.005"), Decimal("1.00"))
    with pytest.raises(ValueError):
        calculate_fee(Decimal("1"), Decimal("-0.005"), Decimal("1.00"))
    with pytest.raises(ValueError):
        calculate_fee(Decimal("1"), Decimal("0.005"), Decimal("-1.00"))


def test_fee_quantizes_to_cent() -> None:
    """333 * 0.005 = 1.665 → rounds to 1.67 (HALF_UP)."""
    fee = calculate_fee(Decimal("333"), Decimal("0.005"), Decimal("1.00"))
    assert fee == Decimal("1.67")


def test_can_construct_arbitrary_currency_cost_model() -> None:
    """Engine validates currency at __init__; the cost model itself is
    not constrained to USD by construction."""
    hk_model = ExecutionCostModel(
        slippage_bps=10.0,
        fee_per_share=Decimal("0.0008"),
        min_fee=Decimal("8.0"),
        currency=Currency.HKD,
    )
    assert hk_model.currency == Currency.HKD
