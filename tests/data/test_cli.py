"""Tests for the data CLI — fetch / check exit codes and integrity logic."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

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


def test_fetch_end_to_end_writes_to_db_twice(
    monkeypatch: pytest.MonkeyPatch,
    cache_dir,
    db_session,
) -> None:
    """End-to-end fetch test — the regression gate for r1 偏离 1.

    Runs cli.fetch() twice in a row against an in-memory SQLite + a mocked
    yfinance backend. The first run misses the cache; the second hits it.
    Before the cache fix, the second run crashed with AttributeError
    because cache hits returned dicts. After the fix, both runs succeed
    and the DB row count stays correct.
    """
    import pandas as pd

    from src.data import cli as cli_mod
    from src.data.yfinance_adapter import YFinanceAdapter

    monkeypatch.setattr("src.data.cache.DEFAULT_CACHE_DIR", cache_dir)

    # Restrict universe to three tickers so the test is fast and deterministic.
    universe = ["SPY", "QQQ", "AAPL"]
    monkeypatch.setattr(cli_mod, "get_us_universe", lambda *_a, **_k: universe)

    # Stub out the yfinance HTTP boundary.
    download_calls: list[list[str]] = []

    def fake_download(codes, start: str, end: str):
        codes_list = list(codes) if isinstance(codes, list) else [codes]
        download_calls.append(codes_list)
        idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
        fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        data = {}
        for i, c in enumerate(codes_list):
            base = 100.0 + i * 5
            data[("Open", c)] = [base, base + 0.5, base - 0.3]
            data[("High", c)] = [base + 1.5, base + 1.7, base + 0.9]
            data[("Low", c)] = [base - 0.5, base - 0.4, base - 1.0]
            data[("Close", c)] = [base + 1.0, base + 1.2, base - 0.5]
            data[("Adj Close", c)] = [base + 0.9, base + 1.1, base - 0.6]
            data[("Volume", c)] = [1_000_000, 1_100_000, 900_000]
        df = pd.DataFrame(data, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df.reindex(columns=pd.MultiIndex.from_product([fields, codes_list]))

    def fake_info(code: str):
        return {
            "longName": f"{code} Test Inc.",
            "industry": "Test",
            "marketCap": 1_000_000_000,
            "firstTradeDateEpochUtc": 1_000_000_000,
        }

    monkeypatch.setattr(YFinanceAdapter, "_download_history", staticmethod(fake_download))
    monkeypatch.setattr(YFinanceAdapter, "_fetch_info", staticmethod(fake_info))

    # Hand the CLI's session_scope our test session so we can read after.
    from contextlib import contextmanager

    @contextmanager
    def _scoped():
        try:
            yield db_session
        finally:
            pass

    monkeypatch.setattr(cli_mod, "session_scope", _scoped)

    # Run #1 — cold cache.
    rc1 = cli_mod.fetch("us", 30)
    assert rc1 == EXIT_OK
    from src.data.repository import PriceBarRepository, StockRepository

    bars_after_first = PriceBarRepository(db_session).count(market=Market.US)
    stocks_after_first = len(StockRepository(db_session).list_by_market(Market.US))
    assert bars_after_first > 0
    assert stocks_after_first == len(universe)

    download_count_after_first = len(download_calls)

    # Run #2 — warm cache. This is the line that crashed before the r2 fix.
    rc2 = cli_mod.fetch("us", 30)
    assert rc2 == EXIT_OK, "second fetch must not crash on cached PriceBar dicts"

    # No additional HTTP calls should have happened (cache hit on prices).
    assert len(download_calls) == download_count_after_first, (
        "second fetch should be served entirely from cache"
    )

    # DB row counts unchanged (idempotent upsert on conflict).
    bars_after_second = PriceBarRepository(db_session).count(market=Market.US)
    assert bars_after_second == bars_after_first


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
