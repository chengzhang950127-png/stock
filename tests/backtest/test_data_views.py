"""PointInTimeDataView — confirms strict ``<= as_of`` filtering (#B1 / #8)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.backtest.data_views import LookaheadBiasError, PointInTimeDataView
from src.contracts import Currency, Market, PriceBar, Stock


def _bar(d: date, close: Decimal = Decimal("100")) -> PriceBar:
    return PriceBar(
        code="TEST",
        market=Market.US,
        date=d,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=1000,
    )


def _bars_jan_2024() -> list[PriceBar]:
    return [_bar(date(2024, 1, day)) for day in range(1, 11)]


def test_get_bars_filters_strictly_to_as_of() -> None:
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 5))

    returned = view.get_bars("TEST")

    assert len(returned) == 5
    assert all(b.date <= date(2024, 1, 5) for b in returned)


def test_get_bars_unknown_code_returns_empty_list() -> None:
    view = PointInTimeDataView({"TEST": _bars_jan_2024()}, [], as_of=date(2024, 1, 5))
    assert view.get_bars("NOPE") == []


def test_get_bar_on_returns_bar_for_existing_date() -> None:
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 10))

    bar = view.get_bar_on("TEST", date(2024, 1, 4))
    assert bar is not None
    assert bar.date == date(2024, 1, 4)


def test_get_bar_on_returns_none_for_missing_date_within_window() -> None:
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 10))

    assert view.get_bar_on("TEST", date(2023, 12, 25)) is None
    assert view.get_bar_on("NOPE", date(2024, 1, 5)) is None


def test_get_bar_on_raises_for_future_date() -> None:
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 3))

    with pytest.raises(LookaheadBiasError):
        view.get_bar_on("TEST", date(2024, 1, 4))


def test_as_of_property_is_exposed() -> None:
    view = PointInTimeDataView({}, [], as_of=date(2024, 6, 15))
    assert view.as_of == date(2024, 6, 15)


def test_get_universe_returns_provided_list() -> None:
    universe = [
        Stock(code="AAA", market=Market.US, currency=Currency.USD, name="A"),
        Stock(code="BBB", market=Market.US, currency=Currency.USD, name="B"),
    ]
    view = PointInTimeDataView({}, universe, as_of=date(2024, 1, 1))
    assert [s.code for s in view.get_universe()] == ["AAA", "BBB"]


def test_get_universe_returns_empty_list_when_unspecified() -> None:
    view = PointInTimeDataView({}, [], as_of=date(2024, 1, 1))
    assert view.get_universe() == []


def test_has_bar_on_respects_as_of() -> None:
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 3))

    assert view.has_bar_on("TEST", date(2024, 1, 2)) is True
    assert view.has_bar_on("TEST", date(2024, 1, 5)) is False  # future
    assert view.has_bar_on("TEST", date(2023, 12, 30)) is False  # missing


def test_lookahead_error_message_contains_context() -> None:
    """Lookahead errors must say WHICH symbol and WHICH date."""
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 3))

    with pytest.raises(LookaheadBiasError) as exc_info:
        view.get_bar_on("TEST", date(2024, 1, 9))

    msg = str(exc_info.value)
    assert "TEST" in msg
    assert "2024-01-09" in msg
    assert "2024-01-03" in msg


def test_simulated_cheating_strategy_is_blocked() -> None:
    """A pretend strategy that asks for a future bar must hit LookaheadBiasError."""
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 4))

    def cheating_strategy_lookup() -> PriceBar | None:
        return view.get_bar_on("TEST", date(2024, 1, 5))

    with pytest.raises(LookaheadBiasError):
        cheating_strategy_lookup()


def test_get_bars_does_not_share_internal_list() -> None:
    """Mutating the returned list must not corrupt the view's internal data."""
    bars = _bars_jan_2024()
    view = PointInTimeDataView({"TEST": bars}, [], as_of=date(2024, 1, 10))

    returned = view.get_bars("TEST")
    returned.clear()
    assert len(view.get_bars("TEST")) == 10
