"""Walk-forward harness — skeleton.

V0.1 has no parameter-search use case (single strategy, no hyperparams),
but the V0.5 custom-blended strategy will need this exact loop. We ship
the contract now so V0.5 can plug in without rewriting calling code.

The skeleton accepts a strategy factory + parameter grid and returns one
:class:`BacktestResult` per (train_window, test_window) split. The
"train" leg is currently a no-op — V0.5 will replace it with grid search
that picks the best parameters by Sharpe on the train window before
running them on the test window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from src.backtest.engine import BacktestEngine, BacktestResult
from src.contracts import Account, PriceBar, Stock
from src.strategies.base import StrategyBase

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardSplit:
    """A single train / test window pair."""

    train_start: date
    train_end: date
    test_start: date
    test_end: date


def split_windows(
    full_period_start: date,
    full_period_end: date,
    train_window_days: int = 730,
    test_window_days: int = 90,
    step_days: int = 90,
) -> list[WalkForwardSplit]:
    """Generate rolling train / test windows over the full period.

    Each split is ``[train_start, train_end] / [test_start, test_end]``
    where ``train_end`` is the last day before ``test_start`` and
    ``test_start`` advances by ``step_days`` per iteration.
    """
    if full_period_start >= full_period_end:
        raise ValueError(
            f"full_period_start {full_period_start} must precede end {full_period_end}"
        )
    if train_window_days <= 0 or test_window_days <= 0 or step_days <= 0:
        raise ValueError("train / test / step day counts must all be positive")

    splits: list[WalkForwardSplit] = []
    cursor = full_period_start + timedelta(days=train_window_days)
    while cursor + timedelta(days=test_window_days) <= full_period_end:
        train_start = cursor - timedelta(days=train_window_days)
        train_end = cursor - timedelta(days=1)
        test_start = cursor
        test_end = cursor + timedelta(days=test_window_days - 1)
        splits.append(
            WalkForwardSplit(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        cursor += timedelta(days=step_days)
    return splits


def walk_forward_test(
    strategy_factory: Callable[[dict], StrategyBase],
    parameter_grid: dict,
    account: Account,
    universe: list[Stock],
    historical_data: dict[str, list[PriceBar]],
    full_period_start: date,
    full_period_end: date,
    train_window_days: int = 730,
    test_window_days: int = 90,
    step_days: int = 90,
) -> list[BacktestResult]:
    """Run a walk-forward backtest using ``parameter_grid``.

    V0.1 implementation: the "train" leg is a no-op — we instantiate the
    strategy once with the grid passed verbatim and run it on each test
    window. V0.5 (custom-blended strategy) will fan out across grid
    combinations on each train window, pick the winner by in-sample
    Sharpe, then run that on the test window.

    Returns one :class:`BacktestResult` per split, ordered by test window
    start date.
    """
    splits = split_windows(
        full_period_start,
        full_period_end,
        train_window_days=train_window_days,
        test_window_days=test_window_days,
        step_days=step_days,
    )

    # TODO(V0.5): for each split, grid-search on train window and replace
    # the verbatim parameter_grid below with the winning combination.
    chosen_params = parameter_grid

    results: list[BacktestResult] = []
    for split in splits:
        strategy = strategy_factory(chosen_params)
        engine = BacktestEngine(
            strategy=strategy,
            account=account,
            universe=universe,
            historical_data=historical_data,
            start_date=split.test_start,
            end_date=split.test_end,
        )
        results.append(engine.run())
    return results
