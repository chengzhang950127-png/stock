"""Tests for the data CLI — fetch / check exit codes and integrity logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

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


def test_fetch_passes_rate_limit_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetch must wire YFINANCE_RATE_LIMIT into the adapter (else throttling
    is silently disabled, see r1 偏离 3)."""
    from src.data import cli as cli_mod
    from src.data.yfinance_adapter import YFinanceAdapter

    captured: dict[str, object] = {}

    class _CapturingAdapter(YFinanceAdapter):
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            super().__init__(**kwargs)  # type: ignore[arg-type]

        async def fetch_price_bars_bulk(self, *_a: object, **_k: object) -> dict[str, list]:
            return {}

        async def fetch_stock_metadata(self, *_a: object, **_k: object) -> object:
            raise NotImplementedError("not exercised in this test")

    fake_settings = type(
        "S",
        (),
        {"YFINANCE_RATE_LIMIT": 5},
    )()

    monkeypatch.setattr(cli_mod, "YFinanceAdapter", _CapturingAdapter)
    monkeypatch.setattr(cli_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(cli_mod, "get_us_universe", lambda *_a, **_k: [])
    # session_scope still needs a real engine; patch it to a no-op CM.
    from contextlib import contextmanager

    @contextmanager
    def _noop_session():
        class _S:
            def add(self, *_a, **_k):
                pass

            def commit(self):
                pass

            def close(self):
                pass

        yield _S()

    monkeypatch.setattr(cli_mod, "session_scope", _noop_session)

    rc = cli_mod.fetch("us", 30)
    assert rc == EXIT_OK
    assert captured.get("rate_limit_per_sec") == 5, (
        f"YFINANCE_RATE_LIMIT must reach the adapter; got {captured!r}"
    )


def test_fetch_zero_rate_limit_disables_throttling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """YFINANCE_RATE_LIMIT=0 (the .env default for tests) should pass None,
    not 0, so the throttle is disabled rather than ZeroDivisionError-ing."""
    from src.data import cli as cli_mod
    from src.data.yfinance_adapter import YFinanceAdapter

    captured: dict[str, object] = {}

    class _CapturingAdapter(YFinanceAdapter):
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            super().__init__(**kwargs)  # type: ignore[arg-type]

        async def fetch_price_bars_bulk(self, *_a: object, **_k: object) -> dict[str, list]:
            return {}

    fake_settings = type("S", (), {"YFINANCE_RATE_LIMIT": 0})()

    from contextlib import contextmanager

    @contextmanager
    def _noop_session():
        class _S:
            def commit(self):
                pass

            def close(self):
                pass

        yield _S()

    monkeypatch.setattr(cli_mod, "YFinanceAdapter", _CapturingAdapter)
    monkeypatch.setattr(cli_mod, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(cli_mod, "get_us_universe", lambda *_a, **_k: [])
    monkeypatch.setattr(cli_mod, "session_scope", _noop_session)

    cli_mod.fetch("us", 30)
    assert captured.get("rate_limit_per_sec") is None
