"""Tests for the data CLI — fetch / check exit codes and integrity logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.contracts import Market, PriceBar
from src.data.cli import EXIT_INTEGRITY, EXIT_OK, _validate_bars


def _bar(
    day: date,
    *,
    open_: str = "100",
    high: str = "110",
    low: str = "95",
    close: str = "105",
    volume: int = 1_000,
) -> PriceBar:
    return PriceBar(
        code="SPY",
        market=Market.US,
        date=day,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        adj_close=Decimal(close),
        volume=volume,
    )


def test_validate_bars_passes_on_clean_data() -> None:
    bars = [_bar(date(2024, 1, d)) for d in (2, 3, 4)]
    issues = _validate_bars("SPY", bars)
    assert issues == []


def test_validate_bars_flags_negative_price() -> None:
    bars = [_bar(date(2024, 1, 2), close="-1")]
    issues = _validate_bars("SPY", bars)
    assert any("Non-positive" in i.message for i in issues)


def test_validate_bars_flags_inverted_high_low() -> None:
    # high < close → high < max(o,c,l)
    bars = [_bar(date(2024, 1, 2), high="50", low="40", open_="60", close="55")]
    issues = _validate_bars("SPY", bars)
    assert any("high <" in i.message for i in issues)


def test_validate_bars_flags_negative_volume() -> None:
    bars = [_bar(date(2024, 1, 2), volume=-1)]
    issues = _validate_bars("SPY", bars)
    assert any("Negative volume" in i.message for i in issues)


def test_validate_bars_flags_large_gap() -> None:
    # Two bars 30 days apart — flag.
    bars = [_bar(date(2024, 1, 2)), _bar(date(2024, 2, 2))]
    issues = _validate_bars("SPY", bars)
    assert any("Gap" in i.message for i in issues)


def test_exit_codes_are_distinct() -> None:
    # cron / CI rely on these being the documented values.
    assert EXIT_OK == 0
    assert EXIT_INTEGRITY == 3
