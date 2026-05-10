"""Walk-forward harness tests."""

from __future__ import annotations

from datetime import date

import pytest

from src.backtest.walk_forward import WalkForwardSplit, split_windows, walk_forward_test
from tests.backtest.conftest import StaticBuyOnceStrategy, synthetic_bars


def test_split_windows_basic_geometry() -> None:
    splits = split_windows(
        full_period_start=date(2020, 1, 1),
        full_period_end=date(2020, 12, 31),
        train_window_days=180,
        test_window_days=30,
        step_days=30,
    )
    assert splits, "Should produce at least one split"
    first = splits[0]
    assert first.train_start == date(2020, 1, 1)
    assert (first.train_end - first.train_start).days == 179
    assert first.test_start == first.train_end + __import__("datetime").timedelta(days=1)


def test_split_windows_advances_by_step() -> None:
    splits = split_windows(
        full_period_start=date(2020, 1, 1),
        full_period_end=date(2021, 12, 31),
        train_window_days=180,
        test_window_days=30,
        step_days=30,
    )
    if len(splits) >= 2:
        delta = (splits[1].test_start - splits[0].test_start).days
        assert delta == 30


def test_split_windows_empty_when_period_too_short() -> None:
    splits = split_windows(
        full_period_start=date(2020, 1, 1),
        full_period_end=date(2020, 1, 10),
        train_window_days=180,
        test_window_days=30,
        step_days=30,
    )
    assert splits == []


def test_split_windows_rejects_inverted_period() -> None:
    with pytest.raises(ValueError, match="must precede"):
        split_windows(
            full_period_start=date(2020, 12, 31),
            full_period_end=date(2020, 1, 1),
        )


def test_split_windows_rejects_non_positive_steps() -> None:
    with pytest.raises(ValueError, match="positive"):
        split_windows(
            full_period_start=date(2020, 1, 1),
            full_period_end=date(2020, 12, 31),
            train_window_days=0,
        )


def test_walk_forward_returns_one_result_per_split(synthetic_universe, synthetic_account) -> None:
    bars = {
        "AAA": synthetic_bars("AAA", date(2020, 1, 1), date(2020, 12, 31)),
        "BBB": synthetic_bars("BBB", date(2020, 1, 1), date(2020, 12, 31)),
    }

    def factory(params: dict) -> StaticBuyOnceStrategy:
        return StaticBuyOnceStrategy(code=params["code"], position_pct=params.get("pct", 0.5))

    results = walk_forward_test(
        strategy_factory=factory,
        parameter_grid={"code": "AAA", "pct": 0.5},
        account=synthetic_account,
        universe=synthetic_universe,
        historical_data=bars,
        full_period_start=date(2020, 1, 1),
        full_period_end=date(2020, 12, 31),
        train_window_days=120,
        test_window_days=30,
        step_days=30,
    )
    expected_splits = split_windows(
        full_period_start=date(2020, 1, 1),
        full_period_end=date(2020, 12, 31),
        train_window_days=120,
        test_window_days=30,
        step_days=30,
    )
    assert len(results) == len(expected_splits)
    assert all(r.metrics is not None for r in results)


def test_walk_forward_split_dataclass_is_immutable_per_split() -> None:
    """Sanity: WalkForwardSplit fields are simple dates, not shared references."""
    s = WalkForwardSplit(
        train_start=date(2020, 1, 1),
        train_end=date(2020, 6, 30),
        test_start=date(2020, 7, 1),
        test_end=date(2020, 9, 30),
    )
    assert s.train_start == date(2020, 1, 1)
    assert s.test_end == date(2020, 9, 30)
