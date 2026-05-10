"""Point-in-time data view — the engine's anti-lookahead gatekeeper.

Strategies access historical data ONLY through ``PointInTimeDataView``,
never through the raw ``historical_data`` dict. The view is rebuilt each
simulation step with ``as_of = current_date``; ``get_bars`` returns
ONLY bars on or before ``as_of``.

See ``docs/INVARIANTS.md`` #8 (project-level look-ahead protection) +
``src/backtest/INVARIANTS.md`` #B1 (close vs adj_close usage boundary).
"""

from __future__ import annotations

from datetime import date

from src.contracts import PriceBar, Stock


class LookaheadBiasError(Exception):
    """Raised when strategy code attempts to access data after as_of."""


class PointInTimeDataView:
    """Wraps historical data with an ``as_of`` date.

    Strategies access data ONLY through this view during backtest.
    ``get_bars(code)`` returns ONLY bars where ``bar.date <= as_of``,
    with explicit filtering inside the method (NOT relying on the
    caller to truncate). ``get_bar_on(code, day)`` raises
    :class:`LookaheadBiasError` if ``day > self.as_of``.

    See ``docs/architecture.md §10.5`` + ``docs/INVARIANTS.md #8`` +
    ``src/backtest/INVARIANTS.md #B1``.

    Constructor signature: ``(all_bars, universe, as_of)``. ``universe``
    is positional and required; per v1.2 §10.5 the engine always knows
    the universe by the time it builds a view.
    """

    def __init__(
        self,
        all_bars: dict[str, list[PriceBar]],
        universe: list[Stock],
        as_of: date,
    ) -> None:
        self._all_bars = all_bars
        self._universe = list(universe)
        self._as_of = as_of

    @property
    def as_of(self) -> date:
        return self._as_of

    def get_bars(self, code: str) -> list[PriceBar]:
        """Return ALL bars for ``code`` where ``bar.date <= self.as_of``.

        Filtering is EXPLICIT inside this method — never rely on the
        caller. Even if ``all_bars[code]`` happens to be truncated, the
        comprehension below runs anyway. This is invariant #B1 / #8
        and is non-negotiable.
        """
        if code not in self._all_bars:
            return []
        return [b for b in self._all_bars[code] if b.date <= self._as_of]

    def get_bar_on(self, code: str, day: date) -> PriceBar | None:
        """Return the bar for ``code`` on exactly ``day`` if it exists.

        Raises :class:`LookaheadBiasError` if ``day > self.as_of`` —
        this is the canonical lookahead pattern the view exists to
        block. Returns ``None`` if the bar is missing on a non-trading
        day or if ``code`` is unknown.
        """
        if day > self._as_of:
            raise LookaheadBiasError(
                f"Attempted to read bar for {code} on {day}, but as_of is "
                f"{self._as_of}. Strategy code must not access future data."
            )
        for bar in self._all_bars.get(code, []):
            if bar.date == day:
                return bar
        return None

    def get_universe(self) -> list[Stock]:
        """Return the universe as of ``self.as_of``.

        V0.1: static universe (same across all dates within a backtest run).
        V1.x (WP-1.6): point-in-time index membership tracking.
        """
        return list(self._universe)

    def has_bar_on(self, code: str, day: date) -> bool:
        """Cheap presence check that respects ``as_of``."""
        if day > self._as_of:
            return False
        return any(b.date == day for b in self._all_bars.get(code, []))
