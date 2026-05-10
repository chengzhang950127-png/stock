"""Execution cost model + slippage / fee primitives.

The ``ExecutionCostModel`` is a frozen dataclass that bundles slippage,
per-share fee, minimum fee, and the currency the model is denominated in.
``BacktestEngine.__init__`` validates ``cost_model.currency == account.currency``
(see ``src/backtest/INVARIANTS.md`` #B2). Different markets have different
fee schedules; engines must not assume USD.

V0.1 ships ``US_DEFAULT_COST`` only. HK is added in WP-1.2 / V0.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from src.contracts import Currency, SignalDirection

_BPS_DIVISOR = Decimal("10000")
_PRICE_QUANTUM = Decimal("0.0001")
_FEE_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class ExecutionCostModel:
    """Slippage + commission spec, scoped to a single currency.

    All fields together; the engine validates currency consistency at
    construction time. See ``src/backtest/INVARIANTS.md`` #B2.
    """

    slippage_bps: float  # 5.0 = 5 basis points = 0.05%
    fee_per_share: Decimal  # IBKR Pro: 0.005 USD/share
    min_fee: Decimal  # IBKR Pro: 1.00 USD/trade minimum
    currency: Currency  # MUST match account.currency at engine init


# V0.1 only US. HK in WP-1.2 / V0.2.
US_DEFAULT_COST = ExecutionCostModel(
    slippage_bps=5.0,
    fee_per_share=Decimal("0.005"),
    min_fee=Decimal("1.0"),
    currency=Currency.USD,
)


def apply_slippage(
    intended_price: Decimal,
    direction: SignalDirection,
    slippage_bps: float,
) -> Decimal:
    """Apply slippage to an intended fill price.

    BUY pays slightly more (``intended * (1 + bps/10000)``); SELL receives
    slightly less (``intended / (1 + bps/10000)`` — the symmetric form is
    what IBKR's TWS uses internally; numerically very close to ``* (1 - x)``
    for small ``x`` but with the property that BUY-then-immediate-SELL
    round-trips don't quite return to ``intended_price``, matching reality).

    HOLD is a no-op (returns the intended price unchanged).
    """
    if slippage_bps < 0:
        raise ValueError(f"slippage_bps must be non-negative, got {slippage_bps}")
    if intended_price <= 0:
        raise ValueError(f"intended_price must be positive, got {intended_price}")

    factor = Decimal("1") + Decimal(str(slippage_bps)) / _BPS_DIVISOR

    if direction == SignalDirection.BUY:
        adjusted = intended_price * factor
    elif direction == SignalDirection.SELL:
        adjusted = intended_price / factor
    elif direction == SignalDirection.HOLD:
        return intended_price
    else:
        raise ValueError(f"Slippage not applicable to direction {direction}")

    return adjusted.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_fee(
    shares: Decimal,
    fee_per_share: Decimal,
    min_fee: Decimal,
) -> Decimal:
    """Per-trade commission: ``max(min_fee, fee_per_share * |shares|)``.

    Always positive; quantized to USD cent. Zero-share calls return
    ``min_fee`` — generally a sign of a bug upstream (caller skipped a
    no-trade short-circuit) but we don't raise.
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
