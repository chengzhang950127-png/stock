"""Performance metrics — Sharpe, Sortino, MaxDD, Calmar, trade stats.

Inputs are typed (Decimal NAVs, float daily returns, contract Trade list)
and outputs are :class:`PerformanceMetrics`. Numpy is used internally
for reductions; we convert to float at the boundary so numpy scalar
types never leak into contract-layer payloads.

Per ``docs/architecture.md §10.5`` and ``src/backtest/INVARIANTS.md`` #B1:
``daily_return`` / ``cumulative_return`` inside :class:`PerformanceSnapshot`
are pre-computed using ``bar.adj_close``. This module consumes those
pre-computed values (and reads ``snapshot.nav`` for NAV-driven metrics)
and does NOT recompute returns from raw prices.

Annualisation assumes 252 trading days. Risk-free rate defaults to 4%
(V0.1 quick value); WP-1.3 will replace this with a 10Y Treasury yield
lookup once macro data lands.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import numpy as np

from src.contracts import (
    PerformanceMetrics,
    PerformanceSnapshot,
    SignalDirection,
    Trade,
)

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.04


def _daily_rf(annual_rf: float) -> float:
    """Convert annual risk-free rate to daily compounded rate.

    daily_rf = (1 + annual_rf) ** (1/252) - 1
    """
    return float((1.0 + annual_rf) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0)


def sharpe_ratio(
    daily_returns: list[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Annualised Sharpe ratio.

    Formula: ``(mean_excess * 252) / (std_excess * sqrt(252))``,
    simplifying to ``mean_excess / std_excess * sqrt(252)``.

    Returns 0.0 for empty / single-observation series and for
    zero-volatility series — undefined cases that shouldn't masquerade
    as enormous Sharpes via floating-point dust.
    """
    if len(daily_returns) < 2:
        return 0.0
    arr = np.asarray(daily_returns, dtype=float)
    excess = arr - _daily_rf(risk_free_rate)
    std = float(np.std(excess, ddof=1))
    if std < 1e-12:
        return 0.0
    mean = float(np.mean(excess))
    return float(mean / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(
    daily_returns: list[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Annualised Sortino ratio (downside deviation in the denominator).

    Returns 0.0 if there are no negative excess returns (undefined-but-
    pleasant case; reporting +inf would just confuse downstream).
    """
    if len(daily_returns) < 2:
        return 0.0
    arr = np.asarray(daily_returns, dtype=float)
    excess = arr - _daily_rf(risk_free_rate)
    downside = excess[excess < 0]
    if downside.size == 0:
        return 0.0
    downside_std = float(np.sqrt(np.mean(downside**2)))
    if downside_std < 1e-12:
        return 0.0
    mean = float(np.mean(excess))
    return float(mean / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(navs: list[Decimal]) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction.

    e.g. 0.25 = -25%. Returns 0.0 for empty / single-observation series
    and for non-positive series.
    """
    if len(navs) < 2:
        return 0.0
    arr = np.asarray([float(n) for n in navs], dtype=float)
    if bool(np.all(arr <= 0)):
        return 0.0
    running_peak = np.maximum.accumulate(arr)
    drawdowns = (running_peak - arr) / running_peak
    return float(np.max(drawdowns))


def calmar_ratio(annual_return: float, max_dd: float) -> float:
    """``annual_return / max_dd``. Returns 0.0 if drawdown is zero."""
    if max_dd == 0.0:
        return 0.0
    return annual_return / max_dd


def total_return_from_navs(navs: list[Decimal]) -> float:
    """Cumulative total return from start NAV to end NAV."""
    if len(navs) < 2:
        return 0.0
    start, end = float(navs[0]), float(navs[-1])
    if start == 0.0:
        return 0.0
    return end / start - 1.0


def annualised_return(total_return: float, num_days: int) -> float:
    """Annualise a cumulative return over ``num_days`` calendar days."""
    if num_days <= 0:
        return 0.0
    years = num_days / 365.25
    if years <= 0:
        return 0.0
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


@dataclass
class _OpenLot:
    """Per-symbol FIFO lot used by :func:`compute_trade_stats`."""

    opened_at: datetime
    buy_price: Decimal
    remaining_qty: Decimal


def compute_trade_stats(trades: list[Trade]) -> tuple[float, float]:
    """FIFO-match SELLs against prior BUYs to compute win rate and avg holding days.

    A "win" is a closed lot where the SELL price exceeds the BUY price
    (fees deliberately excluded — fees show up in the NAV series; this
    metric is about the directional call). A "lot" is a single BUY's
    worth of shares; partial closes split lots accordingly.

    Returns ``(win_rate, avg_holding_days)``. Empty input or an account
    with only open positions returns ``(0.0, 0.0)``.
    """
    if not trades:
        return (0.0, 0.0)

    open_lots: dict[str, deque[_OpenLot]] = defaultdict(deque)
    closed_wins = 0
    closed_total = 0
    holding_days_total = 0.0

    sorted_trades = sorted(trades, key=lambda t: t.executed_at)
    for trade in sorted_trades:
        symbol = trade.stock_code
        if trade.direction == SignalDirection.BUY:
            open_lots[symbol].append(
                _OpenLot(
                    opened_at=trade.executed_at,
                    buy_price=trade.price,
                    remaining_qty=trade.quantity,
                )
            )
        elif trade.direction == SignalDirection.SELL:
            qty_to_close = trade.quantity
            while qty_to_close > 0 and open_lots[symbol]:
                lot = open_lots[symbol][0]
                close_qty = min(lot.remaining_qty, qty_to_close)
                closed_total += 1
                if trade.price > lot.buy_price:
                    closed_wins += 1
                hold = (trade.executed_at - lot.opened_at).total_seconds() / 86400.0
                holding_days_total += hold
                lot.remaining_qty -= close_qty
                qty_to_close -= close_qty
                if lot.remaining_qty == 0:
                    open_lots[symbol].popleft()

    if closed_total == 0:
        return (0.0, 0.0)
    return (closed_wins / closed_total, holding_days_total / closed_total)


def calculate_metrics(
    snapshots: list[PerformanceSnapshot],
    trades: list[Trade] | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> PerformanceMetrics:
    """Aggregate snapshot series → :class:`PerformanceMetrics`.

    NOTE per ``docs/architecture.md §10.5``: ``snapshot.daily_return`` /
    ``snapshot.cumulative_return`` are pre-computed by the engine using
    ``bar.adj_close`` (so dividend-equivalent compounding is folded in).
    This function consumes those values directly. ``snapshot.nav`` is
    used for drawdown — NAV is built from ``shares * close``, which
    differs from total-return series by ≈ dividend reinvestment PV.
    Both numbers are correct for their respective uses.
    """
    if not snapshots:
        return PerformanceMetrics(
            total_return=0.0,
            total_return_with_dividends=0.0,
            annual_return=0.0,
            annual_return_with_dividends=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            calmar=0.0,
            win_rate=0.0,
            avg_holding_days=0.0,
        )

    navs = [s.nav for s in snapshots]
    daily_returns = [s.daily_return for s in snapshots]

    tr = total_return_from_navs(navs)
    span_days = (snapshots[-1].date - snapshots[0].date).days
    ar = annualised_return(tr, span_days)
    sharpe = sharpe_ratio(daily_returns, risk_free_rate=risk_free_rate)
    sortino = sortino_ratio(daily_returns, risk_free_rate=risk_free_rate)
    mdd = max_drawdown(navs)
    calmar = calmar_ratio(ar, mdd)

    win_rate, avg_hold = compute_trade_stats(trades or [])

    return PerformanceMetrics(
        total_return=tr,
        # Placeholder — compounded TR computation lands in the next commit
        # (this commit is purely the contract extension + stub).
        total_return_with_dividends=tr,
        annual_return=ar,
        annual_return_with_dividends=ar,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=mdd,
        calmar=calmar,
        win_rate=win_rate,
        avg_holding_days=avg_hold,
    )
