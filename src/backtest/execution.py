"""Execution simulation: slippage + commissions.

V0.1 model:

* **Slippage** is a flat bps adjustment to the intended fill price. BUYs
  pay a touch more, SELLs receive a touch less. This is the simplest
  defensible model — no order-book depth, no spread modelling, no
  market-impact curve.
* **Commissions** follow IBKR's ``Tiered`` US-equities pricing in its
  simplest form: ``max(min_fee, fee_per_share * shares)``.

All math runs in :class:`Decimal` so cumulative fee accounting matches
broker statements to the cent.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from src.contracts import SignalDirection

_BPS_DIVISOR = Decimal("10000")
_PRICE_QUANTUM = Decimal("0.0001")  # 4 decimal places for intermediate math
_FEE_QUANTUM = Decimal("0.01")  # USD cent


def apply_slippage(
    intended_price: Decimal,
    direction: SignalDirection,
    slippage_bps: float,
) -> Decimal:
    """Apply a flat bps slippage adjustment to ``intended_price``.

    BUY pays slightly more; SELL receives slightly less. HOLD is a no-op
    (returns the intended price unchanged) since no fill happens.

    Negative ``slippage_bps`` is rejected — the calling site is asking
    for free alpha and that is almost certainly a bug.
    """
    if slippage_bps < 0:
        raise ValueError(f"slippage_bps must be non-negative, got {slippage_bps}")
    if intended_price <= 0:
        raise ValueError(f"intended_price must be positive, got {intended_price}")

    bps = Decimal(str(slippage_bps)) / _BPS_DIVISOR

    if direction == SignalDirection.BUY:
        adjusted = intended_price * (Decimal("1") + bps)
    elif direction == SignalDirection.SELL:
        adjusted = intended_price * (Decimal("1") - bps)
    else:  # HOLD — no fill, no slippage
        return intended_price

    return adjusted.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_fee(
    shares: Decimal,
    fee_per_share: Decimal,
    min_fee: Decimal,
) -> Decimal:
    """Compute the per-trade commission.

    ``max(min_fee, fee_per_share * shares)``. Zero-share calls are valid
    (return ``min_fee``) but generally indicate a bug upstream — the
    caller probably skipped a no-trade short-circuit.

    All inputs Decimal, output Decimal quantized to USD cent.
    """
    if shares < 0:
        raise ValueError(f"shares must be non-negative, got {shares}")
    if fee_per_share < 0:
        raise ValueError(f"fee_per_share must be non-negative, got {fee_per_share}")
    if min_fee < 0:
        raise ValueError(f"min_fee must be non-negative, got {min_fee}")

    proportional = fee_per_share * shares
    fee = max(min_fee, proportional)
    return fee.quantize(_FEE_QUANTUM, rounding=ROUND_HALF_UP)
