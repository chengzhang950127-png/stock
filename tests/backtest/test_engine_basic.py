"""End-to-end engine tests using synthetic deterministic data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.backtest.engine import BacktestEngine
from src.backtest.execution import US_DEFAULT_COST, ExecutionCostModel
from src.contracts import Currency, SignalDirection
from tests.backtest.conftest import (
    BuyAndExitAfterNDaysStrategy,
    NoOpStrategy,
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
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    assert len(result.performance_snapshots) == sum(1 for _ in bars["AAA"])


def test_engine_executes_buy_after_one_day_delay(synthetic_universe, synthetic_account) -> None:
    """T-day signal fills at T+1 open. Verify the BUY trade's executed_at
    is the day AFTER the strategy first fired."""
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
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buys = [t for t in result.trades if t.direction == SignalDirection.BUY]
    assert len(buys) == 1
    # First trading day is Jan 2 (Jan 1 = NY holiday in synth data); second
    # trading day is Jan 3. Strategy fires Jan 2; fill happens Jan 3 (T+1).
    first_day = bars["AAA"][0].date
    second_day = bars["AAA"][1].date
    assert buys[0].executed_at.date() == second_day, (
        f"Expected fill on {second_day} (T+1 of {first_day}), got {buys[0].executed_at.date()}"
    )


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
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 28),
    )
    result = engine.run()
    sells = [t for t in result.trades if t.direction == SignalDirection.SELL]
    assert len(sells) == 1
    # Drift +0.10/day → win after 10 days.
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
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    assert result.account_final.cash < synthetic_account.cash


def test_engine_rejects_inverted_date_range(synthetic_universe, synthetic_account) -> None:
    with pytest.raises(ValueError, match="must be <="):
        BacktestEngine(
            strategy=StaticBuyOnceStrategy(code="AAA"),
            account=synthetic_account,
            universe=synthetic_universe,
            historical_data={},
            cost_model=US_DEFAULT_COST,
            start_date=date(2024, 12, 31),
            end_date=date(2024, 1, 1),
        )


def test_engine_rejects_currency_mismatch(synthetic_universe, synthetic_account) -> None:
    """INVARIANT #B2: cost_model.currency != account.currency raises ValueError."""

    hkd_cost = ExecutionCostModel(
        slippage_bps=10.0,
        fee_per_share=Decimal("0.0008"),
        min_fee=Decimal("8.0"),
        currency=Currency.HKD,
    )
    with pytest.raises(ValueError, match=r"currency.*does not match"):
        BacktestEngine(
            strategy=StaticBuyOnceStrategy(code="AAA"),
            account=synthetic_account,  # USD
            universe=synthetic_universe,
            historical_data={},
            cost_model=hkd_cost,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )


def test_engine_handles_no_trade_strategy(synthetic_universe, synthetic_account) -> None:
    """A no-op strategy produces zero trades and zero return."""
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    engine = BacktestEngine(
        strategy=NoOpStrategy(),
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    assert len(result.trades) == 0
    assert result.account_final.cash == synthetic_account.cash
    assert result.metrics.total_return == 0.0


def test_engine_metrics_returned_in_result(synthetic_universe, synthetic_account) -> None:
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=0.50)
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
    assert result.metrics is not None
    assert result.metrics.total_return >= 0.0


def test_engine_trade_carries_signal_id(synthetic_universe, synthetic_account) -> None:
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    strategy = StaticBuyOnceStrategy(code="AAA")
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
    assert buy.signal_id is not None


def test_engine_trade_carries_account_currency(synthetic_universe, synthetic_account) -> None:
    """INVARIANT #B2: every Trade.currency matches account.currency."""
    bars = {"AAA": synthetic_bars("AAA", date(2024, 1, 1), date(2024, 1, 31))}
    engine = BacktestEngine(
        strategy=StaticBuyOnceStrategy(code="AAA"),
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    for t in result.trades:
        assert t.currency == synthetic_account.currency
