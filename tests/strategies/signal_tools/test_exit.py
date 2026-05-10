"""Tests for exit-price tools (LONG side)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.strategies.signal_tools.exit import (
    stop_loss_from_atr,
    stop_loss_from_pct,
    take_profit_from_risk_reward,
    trailing_stop,
)

# ---------- stop_loss_from_atr ----------


def test_stop_loss_from_atr_default_multiplier():
    assert stop_loss_from_atr(Decimal("171.5"), Decimal("3.5")) == Decimal("164.5")


def test_stop_loss_from_atr_zero_atr_returns_entry():
    assert stop_loss_from_atr(Decimal("100"), Decimal("0"), multiplier=2.0) == Decimal("100")


def test_stop_loss_from_atr_preserves_decimal_precision():
    # 100 - 1.5 * 1.05 = 100 - 1.575 = 98.425
    stop = stop_loss_from_atr(Decimal("100.00"), Decimal("1.05"), multiplier=1.5)
    assert stop == Decimal("98.425")


def test_stop_loss_from_atr_rejects_non_positive_entry():
    with pytest.raises(ValueError, match="entry_price"):
        stop_loss_from_atr(Decimal("0"), Decimal("3"))


def test_stop_loss_from_atr_rejects_non_positive_multiplier():
    with pytest.raises(ValueError, match="multiplier"):
        stop_loss_from_atr(Decimal("100"), Decimal("3"), multiplier=0)


def test_stop_loss_from_atr_rejects_when_stop_goes_non_positive():
    # entry=10, atr=10, mult=2 -> stop = -10
    with pytest.raises(ValueError, match="non-positive"):
        stop_loss_from_atr(Decimal("10"), Decimal("10"), multiplier=2.0)


# ---------- stop_loss_from_pct ----------


def test_stop_loss_from_pct_default_8pct():
    assert stop_loss_from_pct(Decimal("100"), pct=0.08) == Decimal("92.00")


def test_stop_loss_from_pct_preserves_precision():
    # 1.05 * 100 must remain exact
    stop = stop_loss_from_pct(Decimal("100.00"), pct=0.05)
    assert stop == Decimal("95.0000")


def test_stop_loss_from_pct_strict_open_interval():
    with pytest.raises(ValueError, match="pct"):
        stop_loss_from_pct(Decimal("100"), pct=0.0)
    with pytest.raises(ValueError, match="pct"):
        stop_loss_from_pct(Decimal("100"), pct=1.0)
    with pytest.raises(ValueError, match="pct"):
        stop_loss_from_pct(Decimal("100"), pct=-0.01)


def test_stop_loss_from_pct_rejects_non_positive_entry():
    with pytest.raises(ValueError, match="entry_price"):
        stop_loss_from_pct(Decimal("-5"))


# ---------- take_profit_from_risk_reward ----------


def test_take_profit_from_risk_reward_default_2to1():
    tp = take_profit_from_risk_reward(Decimal("171.5"), Decimal("164.5"))
    # risk=7, reward=14, tp=185.5
    assert tp == Decimal("185.5")


def test_take_profit_from_risk_reward_custom_ratio():
    tp = take_profit_from_risk_reward(Decimal("100"), Decimal("90"), rr_ratio=3.0)
    assert tp == Decimal("130")


def test_take_profit_from_risk_reward_zero_ratio_rejected():
    with pytest.raises(ValueError, match="rr_ratio"):
        take_profit_from_risk_reward(Decimal("100"), Decimal("90"), rr_ratio=0)


def test_take_profit_from_risk_reward_stop_above_entry_rejected():
    with pytest.raises(ValueError, match="stop_loss"):
        take_profit_from_risk_reward(Decimal("100"), Decimal("110"))


def test_take_profit_from_risk_reward_stop_equal_entry_rejected():
    with pytest.raises(ValueError, match="stop_loss"):
        take_profit_from_risk_reward(Decimal("100"), Decimal("100"))


# ---------- trailing_stop ----------


def test_trailing_stop_default_3x_atr():
    assert trailing_stop(Decimal("180"), Decimal("3.5")) == Decimal("169.5")


def test_trailing_stop_zero_atr_returns_high():
    assert trailing_stop(Decimal("180"), Decimal("0"), multiplier=3.0) == Decimal("180")


def test_trailing_stop_rejects_non_positive_high():
    with pytest.raises(ValueError, match="current_high"):
        trailing_stop(Decimal("0"), Decimal("3"))


def test_trailing_stop_rejects_when_stop_goes_non_positive():
    # high=10, atr=10, mult=3 -> stop = -20
    with pytest.raises(ValueError, match="non-positive"):
        trailing_stop(Decimal("10"), Decimal("10"), multiplier=3.0)
