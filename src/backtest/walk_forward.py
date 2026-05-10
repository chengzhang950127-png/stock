"""Walk-forward validation harness — interface signature only (V0.1).

V0.1 has no parameter-search use case (single strategy, no hyperparams),
so the body is intentionally ``NotImplementedError``. The signature is
locked here so V0.5's custom-blended strategy can plug in without
restructuring calling code.

Per WBS WP-2.7 (v1.2): "walk_forward 仅锁接口签名留 V0.5 才填实现".
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.strategies.base import StrategyBase


def walk_forward_test(
    strategy_class: type[StrategyBase],
    parameter_grid: dict[str, list[Any]],
    full_period_start: date,
    full_period_end: date,
    train_window_days: int = 730,
    test_window_days: int = 90,
    step_days: int = 90,
) -> list:  # list[BacktestResult] once V0.5 implements
    """Train on rolling window, test on subsequent window.

    NOT IMPLEMENTED IN V0.1. Interface locked here so downstream code
    can reference the signature. Filled in V0.5 for custom-strategy
    parameter optimization.

    Calling this in V0.1 raises :class:`NotImplementedError`.
    """
    raise NotImplementedError(
        "walk_forward_test is deferred to V0.5 custom-strategy WP. "
        "Interface is locked for forward compatibility."
    )
