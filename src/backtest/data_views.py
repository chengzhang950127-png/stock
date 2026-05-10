"""Point-in-time data view — the engine's anti-lookahead gatekeeper.

Strategies see history strictly through ``PointInTimeDataView``, not the
full ``historical_data`` dict. The view is rebuilt each simulation step
with ``as_of = current_date``; ``get_bars`` returns ONLY bars on or before
``as_of``.

See ``src/backtest/INVARIANTS.md`` #B1 for the rationale.
"""

from __future__ import annotations

from datetime import date

from src.contracts import PriceBar, Stock


class LookaheadBiasError(Exception):
    """Raised when strategy code attempts to access future data."""


class PointInTimeDataView:
    """Wraps historical data with an ``as_of`` date.

    Any access to data after ``as_of`` is filtered out (or, for explicit
    "give me bar at date X" lookups beyond ``as_of``, raises
    :class:`LookaheadBiasError`). Strategies are PROHIBITED from accessing
    data outside this view during backtest; the engine constructs a fresh
    view per simulation step.
    """

    def __init__(
        self,
        all_bars: dict[str, list[PriceBar]],
        as_of: date,
        universe: list[Stock] | None = None,
    ) -> None:
        self._all_bars = all_bars
        self._as_of = as_of
        self._universe = universe or []

    @property
    def as_of(self) -> date:
        return self._as_of

    def get_bars(self, code: str) -> list[PriceBar]:
        """Return ALL bars for ``code`` where ``bar.date <= self.as_of``.

        Explicit filter — never returns the raw list even if it happens to
        already be truncated. This is the contract the engine relies on.
        """
        bars = self._all_bars.get(code, [])
        return [b for b in bars if b.date <= self._as_of]

    def get_bar_on(self, code: str, day: date) -> PriceBar | None:
        """Return the bar for ``code`` on exactly ``day`` if it exists.

        Raises :class:`LookaheadBiasError` if ``day > self.as_of`` — the
        caller is asking about a future date through the view, which is
        the canonical lookahead pattern this class exists to block.
        Returns ``None`` if the bar is missing on a non-trading day or
        the symbol simply has no data on that date.
        """
        if day > self._as_of:
            raise LookaheadBiasError(
                f"Attempted to read bar for {code} on {day}, but as_of is {self._as_of}. "
                "Strategy code must not access future data."
            )
        for bar in self._all_bars.get(code, []):
            if bar.date == day:
                return bar
        return None

    def get_universe(self) -> list[Stock]:
        """Return the universe as of ``self.as_of``.

        V0.1: static universe (the same list for the entire backtest run).
        V1.x: replace with point-in-time index membership lookup once
        WP-1.6 lands. See README "Backtest engine — known limitations".
        """
        return list(self._universe)

    def has_bar_on(self, code: str, day: date) -> bool:
        """Cheap presence check that respects ``as_of``."""
        if day > self._as_of:
            return False
        return any(b.date == day for b in self._all_bars.get(code, []))
