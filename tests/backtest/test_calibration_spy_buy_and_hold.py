"""Calibration test for the buy-and-hold baseline strategy.

This test pins the **engine math** with deterministic synthetic series
whose total return / annualized return / drawdown are known a priori.
If the engine is wired correctly, ``BuyAndHoldStrategy`` should
reproduce those exact numbers (within tight rounding tolerance for
slippage + fees).

The companion **reviewer-side acceptance gate** — SPY 2020-01-01 to
2024-12-31 lump-sum buy-and-hold within ±2% of yfinance — runs against
real SPY data via the CLI and is documented in README. That gate needs
WP-1.1 data adapters (or a manually-supplied SPY CSV) and is the hard
pass/fail per WBS WP-2.7 v1.2.

DOCSTRING NOTE per architecture.md §10.5 #2 calibration exception:
BuyAndHoldStrategy issues exactly one BUY at T0 and never SELLs. The
engine still applies T+1-open execution, but with no further fills the
"T close decide / T+1 open execute" distinction has no impact on the
final result — making this strategy safe to use as a calibration
anchor without conceptual look-ahead risk.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.backtest._calibration_strategies import (
    BuyAndHoldStrategy,
    make_single_stock_universe,
)
from src.backtest.engine import BacktestEngine
from src.backtest.execution import US_DEFAULT_COST
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
    """Doubles 100→200 over 5 years → buy-and-hold total return ~100%
    (minus slippage + fee drag, which is well below 1% on a single fill)."""
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    universe = make_single_stock_universe("SYN")
    account = _build_account(start)
    strategy = BuyAndHoldStrategy(ticker="SYN")
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    assert 0.95 < result.metrics.total_return < 1.0, (
        f"Total return {result.metrics.total_return:.4f} outside expected range"
    )


def test_buy_and_hold_records_exactly_one_buy_trade() -> None:
    """Lump-sum BUY consumes essentially all cash on day 2 (T+1 of strategy fire);
    no further trades."""
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy(ticker="SYN"),
        account=_build_account(start),
        universe=make_single_stock_universe("SYN"),
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    assert len(result.trades) == 1


def test_buy_and_hold_drawdown_matches_simulated_dip() -> None:
    """Engineered V shape: 100 → 50 → 200. Max drawdown should be ~50%."""
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
    for i in range(third):
        t = i / max(third - 1, 1)
        price = 100.0 + (50.0 - 100.0) * t
        bars.append(_bar("SYN", days[i], price))
    rest = n - third
    for j in range(rest):
        t = j / max(rest - 1, 1)
        price = 50.0 + (200.0 - 50.0) * t
        bars.append(_bar("SYN", days[third + j], price))

    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy(ticker="SYN"),
        account=_build_account(date(2020, 1, 1)),
        universe=make_single_stock_universe("SYN"),
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=date(2020, 1, 1),
        end_date=end,
    )
    result = engine.run()
    assert math.isclose(result.metrics.max_drawdown, 0.50, abs_tol=0.02)


def test_buy_and_hold_annual_return_matches_geometric_expectation() -> None:
    """Doubles in 5 years → annual return ~ 2^(1/5) - 1 = 14.87%."""
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy(ticker="SYN"),
        account=_build_account(start),
        universe=make_single_stock_universe("SYN"),
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    expected = 2 ** (1 / 5) - 1
    assert math.isclose(result.metrics.annual_return, expected, abs_tol=0.005)


def test_buy_and_hold_initial_position_consumes_most_cash() -> None:
    """Sanity: residual cash is < 1% of initial capital after the first buy."""
    start, end = date(2020, 1, 1), date(2020, 6, 30)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=110.0)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy(ticker="SYN"),
        account=_build_account(start),
        universe=make_single_stock_universe("SYN"),
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    assert result.account_final.cash < Decimal("1000")


def test_buy_and_hold_first_snapshot_is_initial_cash() -> None:
    """Day-1 NAV should equal initial cash because the BUY hasn't filled yet
    (T+1 execution: BUY signal day 1, fill day 2)."""
    start, end = date(2020, 1, 1), date(2020, 1, 15)
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=110.0)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy(ticker="SYN"),
        account=_build_account(start, capital=Decimal("100000")),
        universe=make_single_stock_universe("SYN"),
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    first = result.performance_snapshots[0]
    assert first.cash == Decimal("100000.00")
    assert first.positions_value == Decimal("0.00")


def test_compounded_daily_returns_match_total_return() -> None:
    """When close == adj_close (no dividends), compounded daily_returns
    must equal metrics.total_return_with_dividends within rounding tolerance.

    Regression for r1 偏离 1 + 2: ensures the two TR paths agree when there
    is no dividend divergence. Acts as a sanity check for the adj_close
    accounting frame fix — the engine's daily_return frame is correct
    enough that compounding it back gives the close-based total return.
    """
    start, end = date(2020, 1, 1), date(2024, 12, 31)
    # Ramp 100 → 200; close == adj_close so the two TR paths should agree.
    bars = _ramp_bars("SYN", start, end, start_price=100.0, end_price=200.0)
    engine = BacktestEngine(
        strategy=BuyAndHoldStrategy(ticker="SYN"),
        account=_build_account(start),
        universe=make_single_stock_universe("SYN"),
        historical_data={"SYN": bars},
        cost_model=US_DEFAULT_COST,
        start_date=start,
        end_date=end,
    )
    result = engine.run()

    # Compound daily returns directly from snapshots — independent
    # of metrics.calculate_metrics so we're cross-checking by hand.
    compounded = math.prod(1.0 + s.daily_return for s in result.performance_snapshots) - 1.0

    assert abs(compounded - result.metrics.total_return_with_dividends) < 0.005, (
        f"compounded daily_returns ({compounded:.4f}) should match "
        f"metrics.total_return_with_dividends "
        f"({result.metrics.total_return_with_dividends:.4f})"
    )
    # And both should be near total_return (close == adj_close ⇒ no
    # dividend divergence).
    assert abs(result.metrics.total_return_with_dividends - result.metrics.total_return) < 0.01
