"""Integration test for invariant #B1 — strategies cannot read future data.

Two angles:

* a strategy that audits every bar.date it accesses through the view, and
  asserts none exceeds the engine's current step-date.
* a strategy that explicitly tries to read a future bar — must raise
  :class:`LookaheadBiasError`.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.backtest.data_views import LookaheadBiasError, PointInTimeDataView
from src.backtest.engine import BacktestEngine
from src.contracts import (
    ExitAction,
    ExitDecision,
    Position,
    Signal,
    Stock,
    StrategyParameters,
    StrategyType,
)
from src.strategies.base import StrategyBase
from tests.backtest.conftest import synthetic_bars


class AuditedReadStrategy(StrategyBase):
    """Reads bars through a view passed in via ``set_view`` each step.

    To plug into the engine, we wrap the engine's ``step`` to set a fresh
    view on the strategy before each call. The strategy then records every
    bar.date it sees.
    """

    name = "AuditedRead"
    type = StrategyType.BUILT_IN

    def __init__(self) -> None:
        self.parameters = StrategyParameters()
        self.reads: list[tuple[date, str, date]] = []  # (step_date, code, bar_date)
        self._current_view: PointInTimeDataView | None = None

    def set_view(self, view: PointInTimeDataView) -> None:
        self._current_view = view

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        if self._current_view is not None:
            for s in universe:
                for bar in self._current_view.get_bars(s.code):
                    self.reads.append((date, s.code, bar.date))
        return list(universe)

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        return []

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

    def get_score(self, stock: Stock, date: date) -> float:
        return 0.0


def test_no_strategy_read_exceeds_step_as_of(synthetic_universe, synthetic_account) -> None:
    """Run a strategy that records every bar it reads; assert no future bars."""
    bars = {
        "AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 3, 31)),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 3, 31)),
    }
    strategy = AuditedReadStrategy()

    # Monkey-patch the engine to inject the fresh view into the strategy each step.
    original_step = BacktestEngine.step

    def stepping(self, current_date: date) -> None:
        view = PointInTimeDataView(self.historical_data, current_date, self.universe)
        strategy.set_view(view)
        original_step(self, current_date)

    BacktestEngine.step = stepping  # type: ignore[method-assign]
    try:
        engine = BacktestEngine(
            strategy=strategy,
            account=synthetic_account,
            universe=synthetic_universe,
            historical_data=bars,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
        )
        engine.run()
    finally:
        BacktestEngine.step = original_step  # type: ignore[method-assign]

    assert strategy.reads, "Strategy should have recorded reads"
    violations = [
        (step_date, code, bar_date)
        for step_date, code, bar_date in strategy.reads
        if bar_date > step_date
    ]
    assert violations == [], f"Lookahead violations found: {violations[:5]}"


def test_view_blocks_explicit_future_lookup() -> None:
    """A strategy asking for tomorrow's bar via get_bar_on must hit LookaheadBiasError."""
    bars_aaa = synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))
    view = PointInTimeDataView({"AAA": bars_aaa}, as_of=date(2024, 1, 10))

    with pytest.raises(LookaheadBiasError):
        view.get_bar_on("AAA", date(2024, 1, 11))


def test_get_bars_truncates_silently_to_as_of() -> None:
    """get_bars never returns future data — the view is the gatekeeper."""
    bars_aaa = synthetic_bars("AAA", date(2024, 1, 1), date(2024, 3, 31))
    view = PointInTimeDataView({"AAA": bars_aaa}, as_of=date(2024, 2, 15))

    returned = view.get_bars("AAA")
    assert returned, "Should return at least some bars"
    assert max(b.date for b in returned) <= date(2024, 2, 15)
