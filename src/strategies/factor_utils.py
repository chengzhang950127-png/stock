"""
Internal helpers used by :mod:`src.strategies.factor_lib`.

Underscore prefix marks these as **non-public**. Strategies and other callers
should depend on the named factor functions, not on these helpers, so the
factor library remains the single contract surface.

Design rules
------------
* Pure functions only — no I/O, no globals, no clocks.
* All series helpers preserve the original :class:`PriceBar` ordering after
  filtering by ``as_of`` (i.e. ascending by ``date``).
* Defensive copies are unnecessary: callers receive lists they already own,
  and these helpers never mutate the input.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.contracts import PriceBar


def _align_to_date(bars: list[PriceBar], as_of: date) -> list[PriceBar]:
    """Return ``bars`` filtered to ``date <= as_of`` and sorted ascending.

    Future-dated bars are dropped unconditionally to defend against
    look-ahead bias even when callers pass an unfiltered series.

    Returns an empty list if ``bars`` is empty.
    """
    in_window = [b for b in bars if b.date <= as_of]
    in_window.sort(key=lambda b: b.date)
    return in_window


def _extract_close_series(bars: list[PriceBar]) -> list[Decimal]:
    """Project ``bars`` to their raw close prices, preserving order."""
    return [b.close for b in bars]


def _extract_adj_close_series(bars: list[PriceBar]) -> list[Decimal]:
    """Project ``bars`` to their split/dividend-adjusted closes."""
    return [b.adj_close for b in bars]


def _extract_volume_series(bars: list[PriceBar]) -> list[int]:
    """Project ``bars`` to their share-volume integers."""
    return [b.volume for b in bars]


def _decimal_mean(values: list[Decimal]) -> Decimal:
    """Arithmetic mean of a non-empty Decimal series.

    Raises ``ZeroDivisionError`` on empty input — callers must guard against
    that explicitly so the silent-zero anti-pattern (``avg([]) == 0``) does
    not creep in.
    """
    return sum(values, Decimal(0)) / Decimal(len(values))
