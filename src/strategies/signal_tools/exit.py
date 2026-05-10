"""
Exit-price tools.

Pure deterministic functions returning stop-loss / take-profit / trailing-stop
prices for LONG positions. All price values are :class:`decimal.Decimal`,
multipliers and ratios are :class:`float`.

Conventions
-----------
* All helpers assume LONG positions: ``stop_loss < entry_price < take_profit``.
  Short-side support arrives with a future strategy that needs it (YAGNI).
* Floats are converted to ``Decimal`` via ``Decimal(str(x))``.
"""

from __future__ import annotations

from decimal import Decimal


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _check_positive(name: str, value: Decimal) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def _check_non_negative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def stop_loss_from_atr(
    entry_price: Decimal,
    atr_value: Decimal,
    multiplier: float = 2.0,
) -> Decimal:
    """ATR-based stop loss for a LONG entry.

    ``stop = entry_price - multiplier * atr_value``. The result must be
    positive — if the ATR is so wide the stop would go to zero or below,
    a ``ValueError`` is raised so the strategy can pick a different entry
    or skip the trade.

    >>> from decimal import Decimal
    >>> stop_loss_from_atr(Decimal("171.5"), Decimal("3.5"))
    Decimal('164.5')
    """
    _check_positive("entry_price", entry_price)
    _check_non_negative("atr_value", atr_value)
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier}")

    stop = entry_price - _to_decimal(multiplier) * atr_value
    if stop <= 0:
        raise ValueError(
            f"computed stop loss is non-positive ({stop}); "
            f"ATR ({atr_value}) * multiplier ({multiplier}) exceeds entry_price ({entry_price})"
        )
    return stop


def stop_loss_from_pct(
    entry_price: Decimal,
    pct: float = 0.08,
) -> Decimal:
    """Fixed-percentage stop loss below entry for a LONG position.

    ``stop = entry_price * (1 - pct)``. ``pct`` is restricted to ``(0, 1)``
    so the stop is strictly below entry and strictly positive.

    >>> from decimal import Decimal
    >>> stop_loss_from_pct(Decimal("100"), pct=0.08)
    Decimal('92.00')
    """
    _check_positive("entry_price", entry_price)
    if not (0.0 < pct < 1.0):
        raise ValueError(f"pct must be in (0, 1), got {pct}")
    return entry_price * (Decimal("1") - _to_decimal(pct))


def take_profit_from_risk_reward(
    entry_price: Decimal,
    stop_loss: Decimal,
    rr_ratio: float = 2.0,
) -> Decimal:
    """Take-profit price implied by a per-trade risk:reward ratio.

    For a LONG position::

        risk   = entry_price - stop_loss
        reward = risk * rr_ratio
        tp     = entry_price + reward

    Requires ``stop_loss < entry_price`` (LONG invariant) and ``rr_ratio > 0``.

    >>> from decimal import Decimal
    >>> take_profit_from_risk_reward(Decimal("171.5"), Decimal("164.5"))
    Decimal('185.5')
    """
    _check_positive("entry_price", entry_price)
    _check_positive("stop_loss", stop_loss)
    if stop_loss >= entry_price:
        raise ValueError(
            f"stop_loss ({stop_loss}) must be strictly below entry_price ({entry_price}) for LONG"
        )
    if rr_ratio <= 0:
        raise ValueError(f"rr_ratio must be positive, got {rr_ratio}")

    risk = entry_price - stop_loss
    return entry_price + risk * _to_decimal(rr_ratio)


def trailing_stop(
    current_high: Decimal,
    atr_value: Decimal,
    multiplier: float = 3.0,
) -> Decimal:
    """Chandelier-style trailing stop based on highest price since entry.

    ``stop = current_high - multiplier * atr_value``. Caller is expected to
    track ``current_high`` over the life of the position and ratchet this
    stop upward — never downward — across days.

    >>> from decimal import Decimal
    >>> trailing_stop(Decimal("180"), Decimal("3.5"))
    Decimal('169.5')
    """
    _check_positive("current_high", current_high)
    _check_non_negative("atr_value", atr_value)
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier}")

    stop = current_high - _to_decimal(multiplier) * atr_value
    if stop <= 0:
        raise ValueError(
            f"computed trailing stop is non-positive ({stop}); "
            f"ATR ({atr_value}) * multiplier ({multiplier}) exceeds current_high ({current_high})"
        )
    return stop
