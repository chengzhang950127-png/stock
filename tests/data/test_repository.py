"""Tests for StockRepository / PriceBarRepository round-trips."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.contracts import Currency, Market, PriceBar, Stock
from src.data.repository import PriceBarRepository, StockRepository


def _make_stock(code: str = "SPY", *, name: str = "SPDR S&P 500") -> Stock:
    return Stock(
        code=code,
        market=Market.US,
        currency=Currency.USD,
        name=name,
        industry="ETF",
        market_cap=Decimal("470000000000"),
        listed_date=date(1993, 1, 29),
    )


def _make_bar(code: str, day: date, *, close: str = "472.6") -> PriceBar:
    return PriceBar(
        code=code,
        market=Market.US,
        date=day,
        open=Decimal("471.5"),
        high=Decimal("473.1"),
        low=Decimal("470.0"),
        close=Decimal(close),
        adj_close=Decimal("471.0"),
        volume=10_000_000,
    )


def test_stock_upsert_and_get(db_session: Session) -> None:
    repo = StockRepository(db_session)
    repo.upsert(_make_stock())
    fetched = repo.get("SPY")
    assert fetched is not None
    assert fetched.code == "SPY"
    assert fetched.currency is Currency.USD
    assert fetched.market is Market.US
    assert fetched.market_cap == Decimal("470000000000")


def test_stock_upsert_is_idempotent(db_session: Session) -> None:
    repo = StockRepository(db_session)
    repo.upsert(_make_stock())
    # Second upsert with a different name updates the row in place.
    repo.upsert(_make_stock(name="SPDR S&P 500 ETF Trust (renamed)"))
    fetched = repo.get("SPY")
    assert fetched is not None
    assert fetched.name == "SPDR S&P 500 ETF Trust (renamed)"
    assert len(repo.list_by_market(Market.US)) == 1


def test_stock_list_by_market(db_session: Session) -> None:
    repo = StockRepository(db_session)
    repo.upsert(_make_stock("SPY", name="SPDR S&P 500"))
    repo.upsert(_make_stock("QQQ", name="Invesco QQQ"))
    fetched = repo.list_by_market(Market.US)
    assert {s.code for s in fetched} == {"SPY", "QQQ"}


def test_stock_get_returns_none_when_missing(db_session: Session) -> None:
    repo = StockRepository(db_session)
    assert repo.get("DOES_NOT_EXIST") is None


def test_price_bar_round_trip(db_session: Session) -> None:
    repo = PriceBarRepository(db_session)
    bars = [
        _make_bar("SPY", date(2024, 1, 2)),
        _make_bar("SPY", date(2024, 1, 3), close="473.1"),
        _make_bar("SPY", date(2024, 1, 4), close="470.0"),
    ]
    repo.upsert_many(bars)
    fetched = repo.get_range("SPY", date(2024, 1, 2), date(2024, 1, 4))
    assert len(fetched) == 3
    assert fetched[0].close == Decimal("472.6")
    assert fetched[2].close == Decimal("470.0")
    assert all(b.market is Market.US for b in fetched)


def test_price_bar_upsert_overwrites(db_session: Session) -> None:
    repo = PriceBarRepository(db_session)
    repo.upsert_many([_make_bar("SPY", date(2024, 1, 2), close="472.6")])
    repo.upsert_many([_make_bar("SPY", date(2024, 1, 2), close="999.99")])
    fetched = repo.get_range("SPY", date(2024, 1, 2), date(2024, 1, 2))
    assert len(fetched) == 1
    assert fetched[0].close == Decimal("999.99")


def test_price_bar_count(db_session: Session) -> None:
    repo = PriceBarRepository(db_session)
    repo.upsert_many(
        [_make_bar("SPY", date(2024, 1, d)) for d in (2, 3, 4)]
        + [_make_bar("QQQ", date(2024, 1, 2))]
    )
    assert repo.count() == 4
    assert repo.count(market=Market.US) == 4


def test_upsert_many_empty_is_noop(db_session: Session) -> None:
    PriceBarRepository(db_session).upsert_many([])
    StockRepository(db_session).upsert_many([])
    # Just shouldn't raise.
    assert True


def test_get_range_respects_window(db_session: Session) -> None:
    repo = PriceBarRepository(db_session)
    repo.upsert_many([_make_bar("SPY", date(2024, 1, d)) for d in (2, 3, 4, 5)])
    fetched = repo.get_range("SPY", date(2024, 1, 3), date(2024, 1, 4))
    assert {b.date for b in fetched} == {date(2024, 1, 3), date(2024, 1, 4)}


def test_universe_contains_required_symbols() -> None:
    """The V0.1 trend-momentum strategy needs SPY/QQQ + a real equity sample."""
    from src.data.universe import get_us_universe

    u = get_us_universe()
    assert "SPY" in u
    assert "QQQ" in u
    assert "TLT" in u
    assert "GLD" in u
    assert "IWM" in u
    assert "AAPL" in u
    assert len(u) >= 100
    # No accidental duplicates.
    assert len(set(u)) == len(u)


@pytest.mark.parametrize("code", ["SPY", "QQQ", "AAPL"])
def test_stock_currency_is_usd_by_construction(code: str) -> None:
    s = _make_stock(code, name=f"{code} stub")
    assert s.currency is Currency.USD
    assert s.market is Market.US
