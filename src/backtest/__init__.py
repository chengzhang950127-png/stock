"""Backtest engine — V0.1 implementation core.

See ``src/backtest/INVARIANTS.md`` for the four backtest-layer invariants:

* #B1 — close vs adj_close strict separation
* #B2 — ExecutionCostModel currency consistency
* #B3 — decision time vs execution time strict separation (T close decide / T+1 open execute)
* #B4 — position_size_pct base = NAV; same-day SELL → BUY ordering

The vectorized engine is the single source of truth for every strategy's
performance numbers. Correctness over performance.
"""

from src.backtest.data_views import LookaheadBiasError, PointInTimeDataView
from src.backtest.execution import (
    US_DEFAULT_COST,
    ExecutionCostModel,
    apply_slippage,
    calculate_fee,
)

__all__ = [
    "ExecutionCostModel",
    "US_DEFAULT_COST",
    "apply_slippage",
    "calculate_fee",
    "PointInTimeDataView",
    "LookaheadBiasError",
]
