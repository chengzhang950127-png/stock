"""Performance metrics — Sharpe, Sortino, max drawdown, Calmar, etc.

Inputs are typed (Decimal NAVs, float daily returns) and outputs are
``PerformanceMetrics``. Numpy is used internally for reductions; we
convert to float at the boundary so numpy scalar types never leak into
contract-layer payloads.

Annualisation assumes 252 trading days. Risk-free rate defaults to 4%
(V0.1 quick value); WP-1.3 will replace this with a 10Y Treasury yield
lookup once macro data lands.
"""

from __future__ import annotations

from collections import defaultdict, deque
from decimal import Decimal

import numpy as np

from src.contracts import PerformanceMetrics, PerformanceSnapshot, SignalDirection, Trade

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.04


def sharpe_ratio(
    daily_returns: list[float], risk_free_rate: float = DEFAULT_RISK_FREE_RATE
) -> float:
    """Annualised Sharpe ratio.

    Returns 0.0 for empty / single-observation series and for zero-volatility
    series (constant returns) — these have no meaningful Sharpe.
    """
    if len(daily_returns) < 2:
        return 0.0
    arr = np.asarray(daily_returns, dtype=float)
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = arr - daily_rf
    std = float(np.std(excess, ddof=1))
    # Guard against floating-point dust on constant series (std numerically ~ 1e-18).
    if std < 1e-12:
        return 0.0
    mean = float(np.mean(excess))
    return float(mean / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(
    daily_returns: list[float], risk_free_rate: float = DEFAULT_RISK_FREE_RATE
) -> float:
    """Annualised Sortino ratio (downside deviation in the denominator).

    If there are no negative excess returns, returns 0.0 — undefined-but-
    pleasant case; reporting +inf would just confuse downstream consumers.
    """
    if len(daily_returns) < 2:
        return 0.0
    arr = np.asarray(daily_returns, dtype=float)
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = arr - daily_rf
    downside = excess[excess < 0]
    if downside.size == 0:
        return 0.0
    downside_std = float(np.sqrt(np.mean(downside**2)))
    if downside_std < 1e-12:
        return 0.0
    mean = float(np.mean(excess))
    return float(mean / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(navs: list[Decimal]) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction (e.g. 0.25 = -25%).

    Returns 0.0 for empty / single-observation series.
    """
    if len(navs) < 2:
        return 0.0
    arr = np.asarray([float(n) for n in navs], dtype=float)
    if np.all(arr <= 0):
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
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def calculate_metrics(
    snapshots: list[PerformanceSnapshot],
    trades: list[Trade] | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> PerformanceMetrics:
    """Aggregate snapshot series → :class:`PerformanceMetrics`.

    ``trades`` is optional; when provided we compute trade-level
    win rate and average holding days via FIFO matching of SELLs to
    prior BUYs of the same symbol. When absent (or empty), both
    fall back to 0.0 so the ``PerformanceMetrics`` shape stays valid.
    """
    if not snapshots:
        return PerformanceMetrics(
            total_return=0.0,
            annual_return=0.0,
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
        annual_return=ar,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=mdd,
        calmar=calmar,
        win_rate=win_rate,
        avg_holding_days=avg_hold,
    )


def compute_trade_stats(trades: list[Trade]) -> tuple[float, float]:
    """FIFO-match SELLs against prior BUYs to compute win rate and avg holding days.

    A "win" is a closed lot where the SELL price exceeds the BUY price
    (fees are NOT subtracted here — fees show up in the NAV series; this
    metric is about the directional call). A "lot" is a single BUY's
    worth of shares; partial closes split lots accordingly.

    Returns ``(win_rate, avg_holding_days)``. Empty input or an account
    with only open positions returns ``(0.0, 0.0)``.
    """
    # Per-symbol queue of (executed_at, price, remaining_qty) BUY lots.
    open_lots: dict[str, deque[tuple]] = defaultdict(deque)
    closed_wins = 0
    closed_total = 0
    holding_days_total = 0.0

    sorted_trades = sorted(trades, key=lambda t: t.executed_at)
    for trade in sorted_trades:
        symbol = trade.stock_code
        if trade.direction == SignalDirection.BUY:
            open_lots[symbol].append([trade.executed_at, trade.price, trade.quantity])
        elif trade.direction == SignalDirection.SELL:
            qty_to_close = trade.quantity
            while qty_to_close > 0 and open_lots[symbol]:
                lot = open_lots[symbol][0]
                lot_opened_at, buy_price, lot_qty = lot
                close_qty = min(lot_qty, qty_to_close)
                closed_total += 1
                if trade.price > buy_price:
                    closed_wins += 1
                hold = (trade.executed_at - lot_opened_at).total_seconds() / 86400.0
                holding_days_total += hold
                lot[2] = lot_qty - close_qty
                qty_to_close -= close_qty
                if lot[2] == 0:
                    open_lots[symbol].popleft()
        # HOLD trades are not produced by the engine; ignore if present.

    if closed_total == 0:
        return (0.0, 0.0)
    return (closed_wins / closed_total, holding_days_total / closed_total)
