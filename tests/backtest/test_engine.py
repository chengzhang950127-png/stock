"""End-to-end engine tests using synthetic deterministic data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.backtest.engine import BacktestEngine
from src.contracts import SignalDirection
from tests.backtest.conftest import (
    BuyAndExitAfterNDaysStrategy,
    StaticBuyOnceStrategy,
    synthetic_bars,
)


def test_engine_run_produces_snapshot_per_trading_day(
    synthetic_universe, synthetic_account
) -> None:
    bars = {
        "AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31)),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    strategy = StaticBuyOnceStrategy(code="AAA")
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()

    # Jan 2024: 22 weekdays
    expected_days = sum(1 for b in bars["AAA"])
    assert len(result.performance_snapshots) == expected_days


def test_engine_executes_buy_on_signal(synthetic_universe, synthetic_account) -> None:
    bars = {
        "AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31)),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.5)
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()

    buy_trades = [t for t in result.trades if t.direction == SignalDirection.BUY]
    assert len(buy_trades) == 1
    assert buy_trades[0].stock_code == "AAA"
    assert buy_trades[0].quantity > 0


def test_engine_buy_then_exit_creates_round_trip(synthetic_universe, synthetic_account) -> None:
    bars = {
        "AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 2, 28)),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 2, 28)),
    }
    strategy = BuyAndExitAfterNDaysStrategy(code="AAA", hold_days=10)
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 28),
    )
    result = engine.run()

    sells = [t for t in result.trades if t.direction == SignalDirection.SELL]
    assert len(sells) == 1, "Strategy should fully exit exactly once"
    # Drift is +0.10/day; over 10 days that's a positive return → win.
    assert result.metrics.win_rate == 1.0


def test_engine_cash_decreases_after_buy(synthetic_universe, synthetic_account) -> None:
    bars = {
        "AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31)),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.5)
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()

    assert result.account_final.cash < synthetic_account.cash


def test_engine_rejects_inverted_date_range(synthetic_universe, synthetic_account) -> None:
    import pytest

    with pytest.raises(ValueError, match="must be <="):
        BacktestEngine(
            strategy=StaticBuyOnceStrategy(code="AAA"),
            account=synthetic_account,
            universe=synthetic_universe,
            historical_data={},
            start_date=date(2024, 12, 31),
            end_date=date(2024, 1, 1),
        )


def test_engine_handles_no_trade_strategy(synthetic_universe, synthetic_account) -> None:
    """A strategy that never buys produces a flat NAV series."""
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

    class NoOpStrategy(StrategyBase):
        name = "NoOp"
        type = StrategyType.BUILT_IN

        def __init__(self) -> None:
            self.parameters = StrategyParameters()

        def screen(self, universe: list[Stock], date) -> list[Stock]:
            return []

        def generate_signals(self, candidates, date) -> list[Signal]:
            return []

        def exit_rules(self, position: Position, date) -> ExitDecision:
            return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

        def get_score(self, stock: Stock, date) -> float:
            return 0.0

    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    engine = BacktestEngine(
        strategy=NoOpStrategy(),
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()

    assert len(result.trades) == 0
    assert result.account_final.cash == synthetic_account.cash
    assert result.metrics.total_return == 0.0


def test_engine_respects_buy_budget_constraint(synthetic_universe, synthetic_account) -> None:
    """Per-position dollar budget honors signal.position_size_pct of NAV."""
    bars = {
        "AAA": synthetic_bars(
            "AAA", date(2024, 1, 1), date(2024, 1, 31), start_price=Decimal("10.00")
        ),
        "BBB": synthetic_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.10)  # 10% of NAV
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buy = next(t for t in result.trades if t.direction == SignalDirection.BUY)
    notional = buy.quantity * buy.price
    # 10% of $100k = $10k, well within tolerance for fees / slippage rounding
    assert Decimal("9000") <= notional <= Decimal("10100")


def test_engine_metrics_returned_in_result(synthetic_universe, synthetic_account) -> None:
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.50)
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()

    assert result.metrics is not None
    assert result.metrics.total_return >= 0.0  # ramp data => non-negative


def test_engine_trade_carries_signal_id(synthetic_universe, synthetic_account) -> None:
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    strategy = StaticBuyOnceStrategy(code="AAA")
    engine = BacktestEngine(
        strategy=strategy,
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buy = next(t for t in result.trades if t.direction == SignalDirection.BUY)
    assert buy.signal_id is not None
    assert buy.signal_id.startswith("sig-")
