"""Backtest engine — V0.1 implementation core.

See ``src/backtest/INVARIANTS.md`` for the two backtest-layer invariants:

* #B1 — Look-ahead bias protection (all data goes through ``PointInTimeDataView``)
* #B2 — ``close`` vs ``adj_close`` usage boundary

The vectorized engine is the single source of truth for every strategy's
performance numbers. Correctness over performance.
"""

from src.backtest.data_views import LookaheadBiasError, PointInTimeDataView

__all__ = [
    "LookaheadBiasError",
    "PointInTimeDataView",
]
