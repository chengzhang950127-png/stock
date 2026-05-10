"""Backtest engine — V0.1 implementation core.

See ``src/backtest/INVARIANTS.md`` for the two backtest-layer invariants:

* #B1 — Look-ahead bias protection (all data goes through ``PointInTimeDataView``)
* #B2 — ``close`` vs ``adj_close`` usage boundary

The vectorized engine is the single source of truth for every strategy's
performance numbers. Correctness over performance.
"""

from src.backtest.data_views import LookaheadBiasError, PointInTimeDataView
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.execution import apply_slippage, calculate_fee
from src.backtest.metrics import (
    annualised_return,
    calculate_metrics,
    calmar_ratio,
    compute_trade_stats,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    total_return_from_navs,
)

__all__ = [
    "LookaheadBiasError",
    "PointInTimeDataView",
    "BacktestEngine",
    "BacktestResult",
    "apply_slippage",
    "calculate_fee",
    "calculate_metrics",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown",
    "calmar_ratio",
    "total_return_from_navs",
    "annualised_return",
    "compute_trade_stats",
]
