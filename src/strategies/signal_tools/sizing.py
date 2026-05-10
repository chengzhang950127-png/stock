"""
Position-sizing tools.

Pure deterministic sizing functions. Two share-count helpers return a
fractional :class:`decimal.Decimal` (the strategy / engine layer is free
to floor it for whole-share venues). The Kelly helper returns a fractional
allocation in ``[0.0, 1.0]`` as :class:`float`.

The hard 10 % / 20 % portfolio caps live in the strategy layer, not here —
these helpers do math, not policy.
"""

from __future__ import annotations

from decimal import Decimal


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _check_positive(name: str, value: Decimal) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def position_size_fixed_pct(
    account_equity: Decimal,
    entry_price: Decimal,
    allocation_pct: float = 0.10,
) -> Decimal:
    """Allocate a fixed fraction of equity to one position.

    Returns the share count as a Decimal (fractional shares allowed; whole-share
    truncation is the engine's responsibility)::

        shares = (account_equity * allocation_pct) / entry_price

    >>> from decimal import Decimal
    >>> position_size_fixed_pct(Decimal("100000"), Decimal("171.5"), allocation_pct=0.10)
    Decimal('58.30903790087463556851311953')
    """
    _check_positive("account_equity", account_equity)
    _check_positive("entry_price", entry_price)
    if not (0.0 <= allocation_pct <= 1.0):
        raise ValueError(f"allocation_pct must be in [0, 1], got {allocation_pct}")

    dollar_alloc = account_equity * _to_decimal(allocation_pct)
    return dollar_alloc / entry_price


def position_size_fixed_risk(
    account_equity: Decimal,
    entry_price: Decimal,
    stop_loss: Decimal,
    risk_pct: float = 0.01,
) -> Decimal:
    """Risk a fixed fraction of equity per trade (van Tharp / R-multiple sizing).

    Sizes the position so that hitting ``stop_loss`` loses exactly
    ``account_equity * risk_pct``::

        risk_per_share = entry_price - stop_loss      # > 0 for LONG
        dollar_risk    = account_equity * risk_pct
        shares         = dollar_risk / risk_per_share

    >>> from decimal import Decimal
    >>> position_size_fixed_risk(
    ...     Decimal("100000"), Decimal("171.5"), Decimal("164.5"), risk_pct=0.01
    ... )
    Decimal('142.8571428571428571428571429')
    """
    _check_positive("account_equity", account_equity)
    _check_positive("entry_price", entry_price)
    _check_positive("stop_loss", stop_loss)
    if stop_loss >= entry_price:
        raise ValueError(
            f"stop_loss ({stop_loss}) must be strictly below entry_price ({entry_price}) for LONG"
        )
    if not (0.0 < risk_pct <= 1.0):
        raise ValueError(f"risk_pct must be in (0, 1], got {risk_pct}")

    risk_per_share = entry_price - stop_loss
    dollar_risk = account_equity * _to_decimal(risk_pct)
    return dollar_risk / risk_per_share


def position_size_kelly(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = 0.25,
) -> float:
    """Fractional Kelly allocation.

    Computes the classic Kelly fraction and scales by ``fraction``
    (default 1/4 — the conservative V0.1 choice that trades off ~half of
    Kelly's growth rate for substantially lower volatility)::

        b  = avg_win / avg_loss
        p  = win_rate
        q  = 1 - p
        f* = (p * b - q) / b
        out = clamp(f* * fraction, 0.0, 1.0)

    Defensive case: when ``avg_loss == 0`` the formula divides by zero, so
    we fall back to ``min(fraction, 0.5)``. This keeps backtests with no
    losing trades from crashing while avoiding all-in sizing.

    >>> position_size_kelly(0.55, 1.0, 1.0, fraction=1.0)
    0.10000000000000009
    """
    if not (0.0 <= win_rate <= 1.0):
        raise ValueError(f"win_rate must be in [0, 1], got {win_rate}")
    if avg_win < 0:
        raise ValueError(f"avg_win must be non-negative, got {avg_win}")
    if avg_loss < 0:
        raise ValueError(f"avg_loss must be non-negative, got {avg_loss}")
    if not (0.0 <= fraction <= 1.0):
        raise ValueError(f"fraction must be in [0, 1], got {fraction}")

    if avg_loss == 0:
        return min(fraction, 0.5)

    b = avg_win / avg_loss
    if b == 0:
        # No upside — never bet.
        return 0.0
    p = win_rate
    q = 1.0 - p
    f_star = (p * b - q) / b
    scaled = f_star * fraction
    if scaled < 0.0:
        return 0.0
    if scaled > 1.0:
        return 1.0
    return scaled
