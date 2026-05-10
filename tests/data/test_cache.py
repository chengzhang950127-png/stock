"""Tests for the file JSON cache decorator."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.contracts import Currency, Market, Stock
from src.data.cache import cached, clear_cache


def test_sync_cache_hit_skips_call(cache_dir: Path) -> None:
    calls = {"n": 0}

    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.sync_hit")
    def fetch(x: int) -> int:
        calls["n"] += 1
        return x * 2

    assert fetch(5) == 10
    assert fetch(5) == 10
    assert calls["n"] == 1, "second call should hit cache"


def test_sync_cache_miss_invokes_function(cache_dir: Path) -> None:
    calls = {"n": 0}

    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.sync_miss")
    def fetch(x: int) -> int:
        calls["n"] += 1
        return x * 2

    fetch(5)
    fetch(7)  # different arg → miss
    assert calls["n"] == 2


def test_ttl_expiry_re_invokes(cache_dir: Path) -> None:
    calls = {"n": 0}

    @cached(ttl_seconds=1, cache_dir=cache_dir, namespace="t.ttl")
    def fetch(x: int) -> int:
        calls["n"] += 1
        return x

    fetch(1)
    time.sleep(1.1)
    fetch(1)
    assert calls["n"] == 2


def test_decimal_and_date_round_trip(cache_dir: Path) -> None:
    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.decimal")
    def fetch() -> dict[str, Decimal | date]:
        return {"price": Decimal("471.23"), "as_of": date(2024, 1, 2)}

    first = fetch()
    second = fetch()
    assert second == first
    assert isinstance(second["price"], Decimal)
    assert isinstance(second["as_of"], date)


def test_pydantic_model_round_trip(cache_dir: Path) -> None:
    # Importing the adapter module registers Stock / PriceBar with the cache.
    # We import here rather than at top-of-file to keep this test honest about
    # what triggers registration.
    import src.data.yfinance_adapter  # noqa: F401

    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.pydantic")
    def fetch() -> Stock:
        return Stock(
            code="SPY",
            market=Market.US,
            currency=Currency.USD,
            name="SPDR S&P 500 ETF Trust",
        )

    first = fetch()  # warms the cache
    second = fetch()  # cache hit — must come back as a real Stock
    assert isinstance(second, Stock), (
        "cache hit must return the registered Pydantic model, not a dict"
    )
    assert second == first


def test_unregistered_model_falls_back_to_dict(cache_dir: Path) -> None:
    """Models not registered round-trip as the {__model__,data} envelope.

    This is a deliberate fallback so unrelated callers don't crash if they
    forget to register; they get a clearly-tagged dict they can inspect.
    """
    from pydantic import BaseModel as _BM

    class _UnregisteredWidget(_BM):
        x: int

    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.unregistered")
    def fetch() -> _UnregisteredWidget:
        return _UnregisteredWidget(x=7)

    fetch()
    second = fetch()
    assert isinstance(second, dict)
    assert second["__model__"] == "_UnregisteredWidget"
    assert second["data"] == {"x": 7}


@pytest.mark.asyncio
async def test_async_cache_hit(cache_dir: Path) -> None:
    calls = {"n": 0}

    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.async")
    async def fetch(x: int) -> int:
        calls["n"] += 1
        return x + 100

    assert await fetch(1) == 101
    assert await fetch(1) == 101
    assert calls["n"] == 1


def test_clear_cache_removes_files(cache_dir: Path) -> None:
    @cached(ttl_seconds=60, cache_dir=cache_dir, namespace="t.clear")
    def fetch(x: int) -> int:
        return x

    fetch(1)
    fetch(2)
    removed = clear_cache(cache_dir=cache_dir)
    assert removed >= 2
