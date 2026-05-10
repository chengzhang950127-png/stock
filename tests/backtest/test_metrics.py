"""Metrics — sanity-checked against analytically-known input series."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import numpy as np

from src.backtest.metrics import (
    annualised_return,
    calculate_metrics,
    calmar_ratio,
    compounded_return_from_daily,
    compute_trade_stats,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    total_return_from_navs,
)
from src.contracts import (
    Currency,
    Market,
    PerformanceSnapshot,
    SignalDirection,
    Trade,
)

# ---- Sharpe ----


def test_sharpe_zero_for_constant_returns() -> None:
    assert sharpe_ratio([0.001] * 252, risk_free_rate=0.0) == 0.0


def test_sharpe_zero_for_empty_or_singleton() -> None:
    assert sharpe_ratio([]) == 0.0
    assert sharpe_ratio([0.01]) == 0.0


def test_sharpe_matches_hand_computed() -> None:
    """Sharpe equals our hand-computed value for a deterministic series."""
    rng = np.random.default_rng(seed=42)
    returns = (rng.standard_normal(2520) * 0.01 + 0.001).tolist()
    expected = float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252))
    s = sharpe_ratio(returns, risk_free_rate=0.0)
    assert abs(s - expected) < 1e-9


# ---- Sortino ----


def test_sortino_zero_when_no_negatives() -> None:
    assert sortino_ratio([0.01, 0.02, 0.005, 0.015], risk_free_rate=0.0) == 0.0


def test_sortino_matches_hand_computed() -> None:
    rng = np.random.default_rng(seed=42)
    returns = np.asarray((rng.standard_normal(2520) * 0.01 + 0.001).tolist())
    downside = returns[returns < 0]
    expected = float(np.mean(returns) / np.sqrt(np.mean(downside**2)) * np.sqrt(252))
    s = sortino_ratio(returns.tolist(), risk_free_rate=0.0)
    assert abs(s - expected) < 1e-9


def test_sortino_zero_for_empty() -> None:
    assert sortino_ratio([]) == 0.0


# ---- Max drawdown ----


def test_max_drawdown_for_monotonic_nav_is_zero() -> None:
    navs = [Decimal(str(100 + i)) for i in range(50)]
    assert max_drawdown(navs) == 0.0


def test_max_drawdown_for_v_shape() -> None:
    navs = [Decimal("100"), Decimal("80"), Decimal("60"), Decimal("90"), Decimal("100")]
    assert abs(max_drawdown(navs) - 0.4) < 1e-9


def test_max_drawdown_zero_for_empty() -> None:
    assert max_drawdown([]) == 0.0
    assert max_drawdown([Decimal("100")]) == 0.0


def test_max_drawdown_handles_double_dip() -> None:
    navs = [
        Decimal("100"),
        Decimal("90"),
        Decimal("110"),
        Decimal("77"),  # -30% from peak 110
        Decimal("100"),
    ]
    assert abs(max_drawdown(navs) - 0.30) < 1e-9


# ---- Calmar ----


def test_calmar_zero_when_max_dd_is_zero() -> None:
    assert calmar_ratio(0.10, 0.0) == 0.0


def test_calmar_divides_annual_return_by_dd() -> None:
    assert calmar_ratio(0.10, 0.05) == 2.0


# ---- Total / annualised return ----


def test_total_return_simple() -> None:
    navs = [Decimal("100"), Decimal("105"), Decimal("110")]
    assert abs(total_return_from_navs(navs) - 0.10) < 1e-9


def test_annualised_return_one_year_horizon() -> None:
    ar = annualised_return(0.05, num_days=365)
    assert abs(ar - 0.05) < 1e-3


def test_annualised_return_zero_for_zero_days() -> None:
    assert annualised_return(0.05, num_days=0) == 0.0


# ---- Trade stats ----


def _trade(
    symbol: str,
    direction: SignalDirection,
    qty: Decimal,
    price: Decimal,
    when: datetime,
) -> Trade:
    return Trade(
        id=f"{symbol}-{when.isoformat()}-{direction.value}",
        account_id="acct-1",
        stock_code=symbol,
        market=Market.US,
        currency=Currency.USD,
        direction=direction,
        quantity=qty,
        price=price,
        fee=Decimal("1.00"),
        executed_at=when,
    )


def test_trade_stats_empty() -> None:
    assert compute_trade_stats([]) == (0.0, 0.0)


def test_trade_stats_single_winning_round_trip() -> None:
    trades = [
        _trade("AAPL", SignalDirection.BUY, Decimal("10"), Decimal("100"), datetime(2024, 1, 1)),
        _trade("AAPL", SignalDirection.SELL, Decimal("10"), Decimal("110"), datetime(2024, 1, 11)),
    ]
    win_rate, avg_hold = compute_trade_stats(trades)
    assert win_rate == 1.0
    assert abs(avg_hold - 10.0) < 1e-9


def test_trade_stats_partial_close_creates_two_lots() -> None:
    trades = [
        _trade("AAPL", SignalDirection.BUY, Decimal("100"), Decimal("100"), datetime(2024, 1, 1)),
        _trade("AAPL", SignalDirection.SELL, Decimal("60"), Decimal("110"), datetime(2024, 1, 8)),
        _trade("AAPL", SignalDirection.SELL, Decimal("40"), Decimal("90"), datetime(2024, 1, 15)),
    ]
    win_rate, _ = compute_trade_stats(trades)
    assert win_rate == 0.5


def test_trade_stats_open_position_does_not_count() -> None:
    trades = [
        _trade("AAPL", SignalDirection.BUY, Decimal("10"), Decimal("100"), datetime(2024, 1, 1)),
    ]
    assert compute_trade_stats(trades) == (0.0, 0.0)


# ---- calculate_metrics integration ----


def _snap(d: date, nav: Decimal, daily_return: float) -> PerformanceSnapshot:
    return PerformanceSnapshot(
        account_id="acct-1",
        date=d,
        nav=nav,
        cash=Decimal("0"),
        positions_value=nav,
        daily_return=daily_return,
        cumulative_return=0.0,
        drawdown=0.0,
    )


def test_calculate_metrics_empty_snapshots() -> None:
    metrics = calculate_metrics([])
    assert metrics.total_return == 0.0
    assert metrics.sharpe == 0.0


def test_calculate_metrics_populates_full_metrics() -> None:
    snapshots = [
        _snap(date(2024, 1, 1), Decimal("100"), 0.0),
        _snap(date(2024, 1, 2), Decimal("110"), 0.10),
    ]
    metrics = calculate_metrics(snapshots, trades=[])
    assert abs(metrics.total_return - 0.10) < 1e-9
    assert metrics.annual_return > 0.0


def test_calculate_metrics_max_dd_matches_max_drawdown_helper() -> None:
    snapshots = [
        _snap(date(2024, 1, 1), Decimal("100"), 0.0),
        _snap(date(2024, 1, 2), Decimal("80"), -0.20),
        _snap(date(2024, 1, 3), Decimal("90"), 0.125),
    ]
    metrics = calculate_metrics(snapshots, trades=[])
    assert abs(metrics.max_drawdown - 0.20) < 1e-9


# ---- compounded_return_from_daily ----


def test_compounded_return_from_daily_empty_returns_zero() -> None:
    assert compounded_return_from_daily([]) == 0.0


def test_compounded_return_from_daily_single_value() -> None:
    """One day at +5% → cumulative TR = +5%."""
    assert abs(compounded_return_from_daily([0.05]) - 0.05) < 1e-12


def test_compounded_return_from_daily_two_days_compounds() -> None:
    """+10% then +10% → 1.10 * 1.10 - 1 = 0.21 (not 0.20)."""
    assert abs(compounded_return_from_daily([0.10, 0.10]) - 0.21) < 1e-9


def test_compounded_return_from_daily_negatives_compound_correctly() -> None:
    """-50% then +100% → 0.5 * 2.0 - 1 = 0.0 (back to flat)."""
    assert abs(compounded_return_from_daily([-0.5, 1.0]) - 0.0) < 1e-12


# ---- TR vs TR-with-dividends divergence (Blocker 2 方案 A regression) ----


def test_total_return_vs_total_return_with_dividends_diverge_under_dividends() -> None:
    """The two TR fields are equal when daily_return matches NAV ratio
    (no-dividend regime), and divergent when daily_return is dividend-
    adjusted.

    Sanity test for Blocker 2 方案 A: confirms PerformanceMetrics carries
    BOTH price return (close-based via NAV ratio) and dividend-adjusted TR
    (compounded daily_return), and they pull apart when the input series
    has divergent close vs adj_close behaviour.
    """
    # Case 1: daily_return derived directly from nav ratio → no dividend
    # divergence → the two TR fields agree.
    no_div_snaps = [
        _snap(date(2024, 1, 1), Decimal("100"), 0.0),
        _snap(date(2024, 1, 2), Decimal("110"), 0.10),
        _snap(date(2024, 1, 3), Decimal("121"), 0.10),  # 10% on 110 = 121
    ]
    no_div_metrics = calculate_metrics(no_div_snaps, trades=[])
    assert abs(no_div_metrics.total_return - 0.21) < 1e-9
    # compounded(0.0, 0.10, 0.10) = 1.10 * 1.10 - 1 = 0.21
    assert abs(no_div_metrics.total_return_with_dividends - 0.21) < 1e-9
    # → equal within rounding tolerance.
    assert abs(
        no_div_metrics.total_return - no_div_metrics.total_return_with_dividends
    ) < 1e-9

    # Case 2: NAV is flat-ish but daily_return reflects dividend reinvestment
    # (adj_close grew faster). This is the divergence the engine produces
    # post-Blocker-1 fix.
    div_snaps = [
        _snap(date(2024, 1, 1), Decimal("100"), 0.0),
        _snap(date(2024, 1, 2), Decimal("100"), 0.05),  # NAV flat but adj +5%
        _snap(date(2024, 1, 3), Decimal("100"), 0.05),  # NAV flat but adj +5%
    ]
    div_metrics = calculate_metrics(div_snaps, trades=[])
    # NAV ratio = 0% (close-based price flat)
    assert abs(div_metrics.total_return - 0.0) < 1e-9
    # compounded daily ≈ 1.05 * 1.05 - 1 = 0.1025 (adj_close-based TR)
    assert abs(div_metrics.total_return_with_dividends - 0.1025) < 1e-9
    # → divergence ~10.25% (≈ dividend reinvestment PV in this synthetic).
    assert div_metrics.total_return_with_dividends > div_metrics.total_return
    assert (
        div_metrics.total_return_with_dividends - div_metrics.total_return
    ) > 0.05
