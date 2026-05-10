"""Tests for position-sizing tools."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.strategies.signal_tools.sizing import (
    position_size_fixed_pct,
    position_size_fixed_risk,
    position_size_kelly,
)

# ---------- position_size_fixed_pct ----------


def test_position_size_fixed_pct_default_10pct():
    # 100K * 10% / 171.5 = 10000 / 171.5
    shares = position_size_fixed_pct(Decimal("100000"), Decimal("171.5"))
    assert shares == Decimal("10000") / Decimal("171.5")


def test_position_size_fixed_pct_zero_alloc_returns_zero():
    assert position_size_fixed_pct(
        Decimal("100000"), Decimal("100"), allocation_pct=0.0
    ) == Decimal("0")


def test_position_size_fixed_pct_preserves_decimal_precision():
    # 100000 * 0.05 / 100 = 50.00 — must be exact, not 49.99999...
    shares = position_size_fixed_pct(Decimal("100000"), Decimal("100"), allocation_pct=0.05)
    assert shares == Decimal("50")


def test_position_size_fixed_pct_rejects_non_positive_equity():
    with pytest.raises(ValueError, match="account_equity"):
        position_size_fixed_pct(Decimal("0"), Decimal("100"))


def test_position_size_fixed_pct_rejects_alloc_above_one():
    with pytest.raises(ValueError, match="allocation_pct"):
        position_size_fixed_pct(Decimal("100000"), Decimal("100"), allocation_pct=1.5)


# ---------- position_size_fixed_risk ----------


def test_position_size_fixed_risk_one_percent_aapl():
    # 100K * 1% = $1000 risk; per-share risk = 7; shares ~= 142.857
    shares = position_size_fixed_risk(
        account_equity=Decimal("100000"),
        entry_price=Decimal("171.5"),
        stop_loss=Decimal("164.5"),
        risk_pct=0.01,
    )
    assert shares == Decimal("1000") / Decimal("7")
    # Sanity: dollar-risk reconstructed from shares matches budget exactly.
    assert shares * (Decimal("171.5") - Decimal("164.5")) == Decimal("1000")


def test_position_size_fixed_risk_tight_stop_yields_more_shares():
    tight = position_size_fixed_risk(
        Decimal("100000"), Decimal("100"), Decimal("99"), risk_pct=0.01
    )
    wide = position_size_fixed_risk(
        Decimal("100000"), Decimal("100"), Decimal("90"), risk_pct=0.01
    )
    assert tight > wide


def test_position_size_fixed_risk_rejects_stop_above_entry():
    with pytest.raises(ValueError, match="stop_loss"):
        position_size_fixed_risk(
            Decimal("100000"), Decimal("100"), Decimal("110"), risk_pct=0.01
        )


def test_position_size_fixed_risk_rejects_zero_risk_pct():
    with pytest.raises(ValueError, match="risk_pct"):
        position_size_fixed_risk(
            Decimal("100000"), Decimal("100"), Decimal("90"), risk_pct=0.0
        )


def test_position_size_fixed_risk_rejects_risk_pct_above_one():
    with pytest.raises(ValueError, match="risk_pct"):
        position_size_fixed_risk(
            Decimal("100000"), Decimal("100"), Decimal("90"), risk_pct=1.5
        )


# ---------- position_size_kelly ----------


def test_position_size_kelly_classic_60_40_two_to_one():
    # p=0.6, b=2 -> f* = (0.6*2 - 0.4)/2 = 0.4 ; * fraction(0.25) = 0.1
    f = position_size_kelly(0.6, avg_win=2.0, avg_loss=1.0, fraction=0.25)
    assert f == pytest.approx(0.1)


def test_position_size_kelly_full_kelly_returns_unscaled_edge():
    # p=0.55, b=1 -> f* = 0.10 ; fraction=1.0 -> 0.10
    f = position_size_kelly(0.55, avg_win=1.0, avg_loss=1.0, fraction=1.0)
    assert f == pytest.approx(0.10)


def test_position_size_kelly_negative_edge_clamped_to_zero():
    # p=0.4, b=1 -> f* = -0.2 -> clamp to 0
    f = position_size_kelly(0.4, avg_win=1.0, avg_loss=1.0)
    assert f == 0.0


def test_position_size_kelly_zero_avg_loss_uses_safe_fallback():
    # avoids division by zero; returns min(fraction, 0.5)
    assert position_size_kelly(0.6, avg_win=2.0, avg_loss=0.0, fraction=0.25) == 0.25
    assert position_size_kelly(0.6, avg_win=2.0, avg_loss=0.0, fraction=0.9) == 0.5


def test_position_size_kelly_zero_avg_win_returns_zero():
    # Zero upside means no edge -> never bet.
    assert position_size_kelly(0.6, avg_win=0.0, avg_loss=1.0) == 0.0


def test_position_size_kelly_high_edge_stays_bounded():
    # Even with an extreme edge (p=0.99, b=100), Kelly is mathematically
    # bounded by win_rate, so f* = p - q/b = 0.99 - 0.0001 = 0.9899.
    # The defensive >1 clamp lives in the code for fraction>1 inputs we
    # already reject — here we just verify the result stays in [0, 1].
    f = position_size_kelly(0.99, avg_win=10.0, avg_loss=0.1, fraction=1.0)
    assert 0.0 <= f <= 1.0
    assert f == pytest.approx(0.9899)


def test_position_size_kelly_rejects_invalid_win_rate():
    with pytest.raises(ValueError, match="win_rate"):
        position_size_kelly(1.5, avg_win=1.0, avg_loss=1.0)
    with pytest.raises(ValueError, match="win_rate"):
        position_size_kelly(-0.1, avg_win=1.0, avg_loss=1.0)


def test_position_size_kelly_rejects_negative_avg_loss():
    with pytest.raises(ValueError, match="avg_loss"):
        position_size_kelly(0.6, avg_win=1.0, avg_loss=-1.0)


def test_position_size_kelly_rejects_invalid_fraction():
    with pytest.raises(ValueError, match="fraction"):
        position_size_kelly(0.6, avg_win=1.0, avg_loss=1.0, fraction=1.5)
