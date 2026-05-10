"""Behavior test: decisions and execution use bar.close, not adj_close.

Per architecture.md §10.5 #4 + INVARIANT #B1. We construct a series
where ``close`` and ``adj_close`` differ sharply, then verify the BUY
fill price tracks ``open`` / ``close`` (raw prices), not the inflated
``adj_close``.
"""

from __future__ import annotations

from datetime import date

from src.backtest.engine import BacktestEngine
from src.backtest.execution import US_DEFAULT_COST
from src.contracts import SignalDirection
from tests.backtest.conftest import StaticBuyOnceStrategy, split_close_adj_bars


def test_buy_fill_uses_open_not_adj_close(synthetic_universe, synthetic_account) -> None:
    """If decisions used adj_close, the fill price would be ~1.20x higher
    than what we observe."""
    bars = {
        "AAA": split_close_adj_bars("AAA", date(2024, 1, 1), date(2024, 1, 31)),
        "BBB": split_close_adj_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
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

    fill_bar = next(b for b in bars["AAA"] if b.date == buy.executed_at.date())
    # buy.price should be near fill_bar.open + small slippage, NOT near
    # fill_bar.adj_close (which is open * 1.20).
    distance_to_open = abs(buy.price - fill_bar.open)
    distance_to_adj = abs(buy.price - fill_bar.adj_close)
    assert distance_to_open < distance_to_adj
    # And the gap should be ~5 bps of open, not 20% of open.
    assert distance_to_open < fill_bar.open * 1 / 100  # < 1% of open


def test_position_mtm_uses_close_not_adj_close(synthetic_universe, synthetic_account) -> None:
    """Snapshot.positions_value should track close, not adj_close.

    With adj_close = close * 1.20 throughout, using adj_close would
    inflate positions_value by 20%.
    """
    bars = {
        "AAA": split_close_adj_bars("AAA", date(2024, 1, 1), date(2024, 1, 31)),
        "BBB": split_close_adj_bars("BBB", date(2024, 1, 1), date(2024, 1, 31)),
    }
    strategy = StaticBuyOnceStrategy(code="AAA", position_pct=1.0)
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

    last_snap = result.performance_snapshots[-1]
    last_bar = bars["AAA"][-1]
    # positions_value = shares * close (approximately; ignore slippage drift).
    # If MTM used adj_close, we'd see ~20% more.
    holdings_at_close = sum(t.quantity for t in result.trades if t.direction == SignalDirection.BUY)
    expected_close_based = holdings_at_close * last_bar.close
    expected_adj_based = holdings_at_close * last_bar.adj_close

    diff_to_close = abs(last_snap.positions_value - expected_close_based)
    diff_to_adj = abs(last_snap.positions_value - expected_adj_based)
    assert diff_to_close < diff_to_adj
