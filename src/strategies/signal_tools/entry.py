"""
Entry-price tools.

Pure deterministic functions that translate "I like this stock" into a
concrete buy range. No data-source access, no LLM calls — strategies pass
in already-computed numerical inputs and get back ``(low, high)`` Decimal
tuples in strictly ascending order.

All price inputs and outputs are :class:`decimal.Decimal`. Multipliers and
percentages are :class:`float`. Floats are converted to ``Decimal`` via
``Decimal(str(x))`` to avoid binary-float drift.
"""

from __future__ import annotations

from decimal import Decimal


def _to_decimal(value: float) -> Decimal:
    """Convert a float to Decimal via ``str()`` to preserve human precision."""
    return Decimal(str(value))


def _check_positive_price(name: str, value: Decimal) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def _check_non_negative(name: str, value: Decimal) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def _check_pct_unit(name: str, value: float) -> None:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def buy_range_from_atr(
    current_price: Decimal,
    atr_value: Decimal,
    atr_multiplier_low: float = 0.5,
    atr_multiplier_high: float = 1.5,
) -> tuple[Decimal, Decimal]:
    """ATR-based pullback buy range.

    Returns ``(low, high)`` in strictly ascending order::

        low  = current_price - atr_multiplier_high * atr_value
        high = current_price - atr_multiplier_low  * atr_value

    Letting buyers wait for a pullback rather than chase a breakout.

    >>> from decimal import Decimal
    >>> buy_range_from_atr(Decimal("175"), Decimal("3.5"))
    (Decimal('169.75'), Decimal('173.25'))
    """
    _check_positive_price("current_price", current_price)
    _check_non_negative("atr_value", atr_value)
    if atr_multiplier_low < 0 or atr_multiplier_high < 0:
        raise ValueError(
            f"atr multipliers must be non-negative, got "
            f"low={atr_multiplier_low}, high={atr_multiplier_high}"
        )
    if atr_multiplier_low > atr_multiplier_high:
        raise ValueError(
            f"atr_multiplier_low ({atr_multiplier_low}) must be <= "
            f"atr_multiplier_high ({atr_multiplier_high})"
        )
    low = current_price - _to_decimal(atr_multiplier_high) * atr_value
    high = current_price - _to_decimal(atr_multiplier_low) * atr_value
    if low > high:  # defence-in-depth; should be unreachable given checks above
        raise ValueError(f"computed buy range inverted: low={low}, high={high}")
    return (low, high)


def buy_range_from_support(
    current_price: Decimal,
    recent_lows: list[Decimal],
    window: int = 20,
) -> tuple[Decimal, Decimal]:
    """Support-based buy range from the minimum of the last ``window`` lows.

    The support level is ``min(recent_lows[-window:])``. The returned range
    is ``(support, support * 1.02)`` — buy at-or-just-above support.

    >>> from decimal import Decimal
    >>> lows = [Decimal("170"), Decimal("168"), Decimal("172")]
    >>> buy_range_from_support(Decimal("175"), lows, window=3)
    (Decimal('168'), Decimal('171.36'))
    """
    _check_positive_price("current_price", current_price)
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")
    if not recent_lows:
        raise ValueError("recent_lows must not be empty")
    for i, low in enumerate(recent_lows):
        if low <= 0:
            raise ValueError(f"recent_lows[{i}] must be positive, got {low}")

    sample = recent_lows[-window:]
    support = min(sample)
    high = support * Decimal("1.02")
    if support > high:  # unreachable; kept for invariant clarity
        raise ValueError(f"support range inverted: low={support}, high={high}")
    return (support, high)


def buy_range_from_pullback(
    current_price: Decimal,
    sma_value: Decimal,
    pullback_pct_min: float = 0.02,
    pullback_pct_max: float = 0.05,
) -> tuple[Decimal, Decimal]:
    """Pullback-to-MA buy range: ``pullback_pct_min`` to ``pullback_pct_max`` below the SMA.

    Returns ``(low, high)`` in strictly ascending order::

        low  = sma_value * (1 - pullback_pct_max)
        high = sma_value * (1 - pullback_pct_min)

    >>> from decimal import Decimal
    >>> buy_range_from_pullback(Decimal("175"), Decimal("170"))
    (Decimal('161.50'), Decimal('166.60'))
    """
    _check_positive_price("current_price", current_price)
    _check_positive_price("sma_value", sma_value)
    _check_pct_unit("pullback_pct_min", pullback_pct_min)
    _check_pct_unit("pullback_pct_max", pullback_pct_max)
    if pullback_pct_min > pullback_pct_max:
        raise ValueError(
            f"pullback_pct_min ({pullback_pct_min}) must be <= "
            f"pullback_pct_max ({pullback_pct_max})"
        )

    one = Decimal("1")
    low = sma_value * (one - _to_decimal(pullback_pct_max))
    high = sma_value * (one - _to_decimal(pullback_pct_min))
    if low > high:  # unreachable given checks above
        raise ValueError(f"computed pullback range inverted: low={low}, high={high}")
    return (low, high)
