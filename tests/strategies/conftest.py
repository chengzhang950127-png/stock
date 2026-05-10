"""Fixtures and helpers shared across factor / strategy tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.contracts import Market, PriceBar


def _bar(
    d: date,
    close: Decimal,
    *,
    code: str = "TEST",
    market: Market = Market.US,
    open_: Decimal | None = None,
    high: Decimal | None = None,
    low: Decimal | None = None,
    adj_close: Decimal | None = None,
    volume: int = 1_000_000,
) -> PriceBar:
    open_ = open_ if open_ is not None else close
    high = high if high is not None else close
    low = low if low is not None else close
    adj_close = adj_close if adj_close is not None else close
    return PriceBar(
        code=code,
        market=market,
        date=d,
        open=open_,
        high=high,
        low=low,
        close=close,
        adj_close=adj_close,
        volume=volume,
    )


@pytest.fixture
def make_bar() -> Callable[..., PriceBar]:
    """Factory for a single :class:`PriceBar` with sensible defaults."""
    return _bar


@pytest.fixture
def linear_up_bars() -> list[PriceBar]:
    """300 bars where close rises from 100 by 0.10/day. ``adj_close == close``."""
    start = date(2023, 1, 2)
    return [
        _bar(
            start + timedelta(days=i),
            close=Decimal("100") + Decimal(str(i)) / Decimal("10"),
            high=Decimal("100") + Decimal(str(i)) / Decimal("10") + Decimal("0.5"),
            low=Decimal("100") + Decimal(str(i)) / Decimal("10") - Decimal("0.5"),
        )
        for i in range(300)
    ]


@pytest.fixture
def flat_bars() -> list[PriceBar]:
    """120 bars at constant 100.00 — momentum / vol = 0."""
    start = date(2023, 1, 2)
    return [
        _bar(
            start + timedelta(days=i),
            close=Decimal("100"),
        )
        for i in range(120)
    ]
