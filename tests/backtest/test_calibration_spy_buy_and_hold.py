"""Calibration test for the buy-and-hold baseline strategy.

This test pins the **engine math** with a deterministic synthetic series
whose end-to-end total return is known a priori. If the engine is wired
correctly, ``BuyAndHoldStrategy`` should reproduce that exact number
(within tight rounding tolerance accounting for slippage + fees).

The companion **reviewer-side acceptance gate** — SPY 2020-2024 within
±0.5% of Yahoo Finance — runs with real SPY data via the CLI and is
documented in README "Backtest engine — known limitations". That gate
needs WP-1.1 data adapters (or a manually-supplied SPY CSV) and is the
hard pass/fail for WP-2.7.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.backtest.engine import BacktestEngine
from src.backtest.strategies import (
    BuyAndHoldParameters,
    BuyAndHoldStrategy,
    make_single_stock_universe,
)
from src.contracts import Account, AccountType, Currency, Market, PriceBar


def _bar(ticker: str, d: date, close: float) -> PriceBar:
    cd = Decimal(f"{close:.4f}")
    return PriceBar(
        code=ticker,
        market=Market.US,
        date=d,
        open=cd,
        high=cd,
        low=cd,
        close=cd,
        adj_close=cd,
        volume=1_000_000,
    )


def _ramp_bars(
    ticker: str,
    start: date,
    end: date,
    start_price: float,
    end_price: float,
) -> list[PriceBar]:
    """Linear ramp from ``start_price`` (on first trading day) to ``end_price``
    (on last trading day). Weekdays only.
    """
    days: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    n = len(days)
    if n == 0:
        return []
    bars: list[PriceBar] = []
    for i, d in enumerate(days):
        # closed-form linear interpolation
        t = i / (n - 1) if n > 1 else 0.0
        price = start_price + (end_price - start_price) * t
        bars.append(_bar(ticker, d, price))
    return bars


def _build_account(start: date, capital: Decimal = Decimal("100000.00")) -> Account:
    return Account(
        id="calib-account",
        type=AccountType.SHADOW,
        strategy_id="buy-and-hold",
        currency=Currency.USD,
        cash=capital,
        initial_capital=capital,
        created_at=datetime.combine(start, datetime.min.time()),
    )


def test_buy_and_hold_total_return_matches_price_ramp() -> None:
    """Synthetic price doubles over 5 years → buy-and-hold total return ~100%
    (minus tiny slippage + fee drag).
    """
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    universe = make_single_stock_universe("SYN")
    account = _build_account(start)
    strategy = BuyAndHoldStrategy(parameters=BuyAndHoldParameters(ticker="SYN", monthly=True))
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={"SYN": bars},
        start_date=start,
        end_date=end,
    )
    result = engine.run()

    # Expectation: invest essentially all $100k at ~$100, sell at ~$200.
    # 5 bps slippage on the buy plus $1 min commission → < 0.1% drag.
    assert 0.95 < result.metrics.total_return < 1.0, (
        f"Total return {result.metrics.total_return:.4f} outside expected range"
    )


def test_buy_and_hold_no_trades_after_initial_buy() -> None:
    """With position_size_pct=1.0 and a single ticker, all cash is committed
    on month one. Subsequent monthly signals find no cash and produce no
    fills — the engine should record exactly one BUY trade.
    """
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    universe = make_single_stock_universe("SYN")
    account = _build_account(start)
    strategy = BuyAndHoldStrategy(parameters=BuyAndHoldParameters(ticker="SYN", monthly=True))
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={"SYN": bars},
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    assert len(result.trades) == 1


def test_buy_and_hold_drawdown_matches_simulated_dip() -> None:
    """Engineered V shape: 100 → 50 → 200. Max drawdown should be 50% +/- 1%."""
    days: list[date] = []
    cur = date(2020, 1, 1)
    end = date(2024, 12, 31)
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    n = len(days)
    third = n // 3
    bars: list[PriceBar] = []
    # Phase 1: $100 → $50 over first third
    for i in range(third):
        t = i / max(third - 1, 1)
        price = 100.0 + (50.0 - 100.0) * t
        bars.append(_bar("SYN", days[i], price))
    # Phase 2: $50 → $200 over remaining
    rest = n - third
    for j in range(rest):
        t = j / max(rest - 1, 1)
        price = 50.0 + (200.0 - 50.0) * t
        bars.append(_bar("SYN", days[third + j], price))

    universe = make_single_stock_universe("SYN")
    account = _build_account(date(2020, 1, 1))
    strategy = BuyAndHoldStrategy(parameters=BuyAndHoldParameters(ticker="SYN", monthly=True))
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={"SYN": bars},
        start_date=date(2020, 1, 1),
        end_date=end,
    )
    result = engine.run()

    # NAV tracks SYN price after the initial buy. NAV = shares * close.
    # Peak ~ initial $100k, trough ~ $50k → DD ~ 50%.
    assert math.isclose(result.metrics.max_drawdown, 0.50, abs_tol=0.02), (
        f"Max drawdown {result.metrics.max_drawdown:.4f} should be ~50%"
    )


def test_buy_and_hold_annual_return_matches_geometric_expectation() -> None:
    """Synthetic doubles in 5 years → annual return ~ 2^(1/5) - 1 = 14.87%."""
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    universe = make_single_stock_universe("SYN")
    account = _build_account(start)
    strategy = BuyAndHoldStrategy(parameters=BuyAndHoldParameters(ticker="SYN", monthly=True))
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={"SYN": bars},
        start_date=start,
        end_date=end,
    )
    result = engine.run()

    expected = 2 ** (1 / 5) - 1
    assert math.isclose(result.metrics.annual_return, expected, abs_tol=0.005), (
        f"Annual return {result.metrics.annual_return:.4f} should be ~{expected:.4f}"
    )


def test_buy_and_hold_initial_position_consumes_most_cash() -> None:
    """Sanity: residual cash is < 1% of initial capital after the first buy."""
    start, end = date(2020, 1, 1), date(2020, 6, 30)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=110.0)
    universe = make_single_stock_universe("SYN")
    account = _build_account(start)
    strategy = BuyAndHoldStrategy(parameters=BuyAndHoldParameters(ticker="SYN", monthly=True))
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={"SYN": bars},
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    assert result.account_final.cash < Decimal("1000")
