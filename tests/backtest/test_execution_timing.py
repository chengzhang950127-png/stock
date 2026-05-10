"""T-day decision + T+1 open execution + last-day-unexecuted boundary.

Per architecture.md §10.5 #2 + INVARIANT #B3.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.backtest.engine import BacktestEngine
from src.backtest.execution import US_DEFAULT_COST
from src.contracts import SignalDirection
from tests.backtest.conftest import StaticBuyOnceStrategy, synthetic_bars


def test_buy_fill_uses_next_day_open_not_signal_day_close(
    synthetic_universe, synthetic_account
) -> None:
    """Engine fills T-day BUY signals at T+1's bar.open (with slippage),
    NOT at T's close."""
    # open != close so we can tell them apart.
    bars = {
        "AAA": synthetic_bars(
            "AAA",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("1.00"),
            open_eq_close=False,
        ),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.5)
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buy = next(t for t in result.trades if t.direction == SignalDirection.BUY)
    fill_date = buy.executed_at.date()
    # The bar where the fill happened — fill price should reflect that bar's open.
    fill_bar = next(b for b in bars["AAA"] if b.date == fill_date)
    # Slippage: BUY pays slightly more than open.
    assert buy.price > fill_bar.open
    # And buy.price is closer to fill_bar.open than to fill_bar.close.
    assert abs(buy.price - fill_bar.open) < abs(buy.price - fill_bar.close)


def test_signal_on_end_date_is_unexecuted(synthetic_universe, synthetic_account) -> None:
    """A signal generated on end_date has no T+1 to execute on, so it lands
    in BacktestResult.unexecuted_signals."""

    # Build a strategy that fires only on the last available trading day.
    from datetime import datetime

    from src.contracts import (
        ExitAction,
        ExitDecision,
        Market,
        Signal,
        StrategyParameters,
        StrategyType,
    )
    from src.strategies.base import StrategyBase

    class FireOnLastDayStrategy(StrategyBase):
        name = "FireOnLastDay"
        type = StrategyType.BUILT_IN

        def __init__(self, target_date: date, code: str) -> None:
            self.parameters = StrategyParameters()
            self._target_date = target_date
            self._code = code

        def screen(self, universe, date):
            return [s for s in universe if s.code == self._code]

        def generate_signals(self, candidates, date):
            if date != self._target_date or not candidates:
                return []
            return [
                Signal(
                    id=f"end-{date.isoformat()}",
                    strategy_id="end-day",
                    stock_code=self._code,
                    market=Market.US,
                    direction=SignalDirection.BUY,
                    position_size_pct=0.5,
                    confidence=1.0,
                    reason_code="LAST_DAY",
                    generated_at=datetime.combine(date, datetime.min.time()),
                )
            ]

        def exit_rules(self, position, date):
            return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

        def get_score(self, stock, date):
            return 0.0

    bars = {
        "AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31)),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    last_day = bars["AAA"][-1].date

    strategy = FireOnLastDayStrategy(target_date=last_day, code="AAA")
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=last_day,
    )
    result = engine.run()
    assert len(result.unexecuted_signals) >= 1
    assert all(
        t.direction == SignalDirection.SELL or t.direction == SignalDirection.BUY
        for t in result.trades
    )
    # No BUY trade should have been emitted for the end-day signal.
    last_day_trades = [t for t in result.trades if t.executed_at.date() == last_day]
    assert (
        all(t.direction == SignalDirection.SELL for t in last_day_trades)
        or len(last_day_trades) == 0
    )


def test_first_step_has_no_pending_orders_yet(synthetic_universe, synthetic_account) -> None:
    """On day 1 there's no T-1 queue, so no fills happen during phase 1.
    Confirm by checking the first-day snapshot equals initial cash (no trades)."""
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 5))}
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.5)
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 5),
    )
    result = engine.run()
    first_snap = result.performance_snapshots[0]
    assert first_snap.cash == synthetic_account.cash
    assert first_snap.positions_value == Decimal("0.00")
