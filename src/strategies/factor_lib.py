"""
Factor library — pure-function technical factor calculations.

Every factor here is a deterministic, side-effect-free function from
``(bars, as_of, ...)`` to a numeric value (or ``None`` / ``False`` when the
input window is too short). Strategies compose these factors; the factor
library itself never touches data sources, databases, or LLMs.

Field-usage convention
----------------------
* **Price-return factors** (momentum, volatility, relative strength) use
  ``PriceBar.adj_close`` so dividends and splits do not pollute the signal.
* **Form / breakout factors** (SMA, ATR, distance from N-day high,
  ``is_above_sma``) use the raw ``PriceBar.close`` / ``high`` / ``low`` so
  the levels match what a chart shows.
* Each function's docstring restates which field it consumes.

Constants
---------
* ``TRADING_DAYS_PER_MONTH = 21``
* ``TRADING_DAYS_PER_YEAR = 252``
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from itertools import pairwise

from src.contracts import PriceBar
from src.strategies.factor_utils import (
    _align_to_date,
    _decimal_mean,
    _extract_adj_close_series,
    _extract_close_series,
    _extract_volume_series,
)

TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------


def momentum(
    bars: list[PriceBar],
    as_of: date,
    lookback_days: int,
    skip_recent_days: int = 0,
) -> float | None:
    """Total return over ``lookback_days`` ending ``skip_recent_days`` ago.

    Uses ``PriceBar.adj_close`` so corporate actions don't bias the return.

    Returns ``None`` when there are fewer than
    ``lookback_days + skip_recent_days + 1`` bars at or before ``as_of``.

    The window is ``[end - lookback_days, end]`` where ``end`` is the bar
    ``skip_recent_days`` before the most recent bar (0 = most recent bar).
    """
    if lookback_days <= 0:
        raise ValueError(f"lookback_days must be positive, got {lookback_days}")
    if skip_recent_days < 0:
        raise ValueError(f"skip_recent_days must be non-negative, got {skip_recent_days}")

    aligned = _align_to_date(bars, as_of)
    needed = lookback_days + skip_recent_days + 1
    if len(aligned) < needed:
        return None

    end_idx = len(aligned) - 1 - skip_recent_days
    start_idx = end_idx - lookback_days
    start_price = aligned[start_idx].adj_close
    end_price = aligned[end_idx].adj_close
    if start_price <= 0:
        return None
    return float(end_price / start_price) - 1.0


def momentum_12_1(bars: list[PriceBar], as_of: date) -> float | None:
    """12-month total return excluding the most recent month.

    Standard academic momentum factor. Skips the last
    ``TRADING_DAYS_PER_MONTH`` bars to avoid the well-known short-term
    reversal effect. Uses ``adj_close``.

    Returns ``None`` if fewer than ``12 * 21 + 21 + 1`` bars are available.
    """
    return momentum(
        bars,
        as_of,
        lookback_days=12 * TRADING_DAYS_PER_MONTH,
        skip_recent_days=TRADING_DAYS_PER_MONTH,
    )


def momentum_6m(bars: list[PriceBar], as_of: date) -> float | None:
    """Trailing 6-month total return on ``adj_close``.

    Returns ``None`` if fewer than ``6 * 21 + 1`` bars are available.
    """
    return momentum(bars, as_of, lookback_days=6 * TRADING_DAYS_PER_MONTH)


def momentum_3m(bars: list[PriceBar], as_of: date) -> float | None:
    """Trailing 3-month total return on ``adj_close``.

    Returns ``None`` if fewer than ``3 * 21 + 1`` bars are available.
    """
    return momentum(bars, as_of, lookback_days=3 * TRADING_DAYS_PER_MONTH)


# ---------------------------------------------------------------------------
# Moving average / breakout
# ---------------------------------------------------------------------------


def simple_moving_average(
    bars: list[PriceBar],
    as_of: date,
    window: int,
) -> Decimal | None:
    """Arithmetic mean of the last ``window`` raw closes at or before ``as_of``.

    Uses ``PriceBar.close`` (not ``adj_close``) so the level matches what a
    trader sees on a chart — chart-style breakout rules compare against this.

    Returns ``None`` when fewer than ``window`` bars are available.
    """
    if window <= 0:
        raise ValueError(f"window must be positive, got {window}")

    aligned = _align_to_date(bars, as_of)
    if len(aligned) < window:
        return None

    closes = _extract_close_series(aligned[-window:])
    return _decimal_mean(closes)


def is_above_sma(
    bars: list[PriceBar],
    as_of: date,
    sma_window: int,
) -> bool | None:
    """Return whether the latest raw close sits at or above its SMA.

    Uses ``PriceBar.close`` for both the spot price and the SMA so the
    comparison is apples-to-apples with chart levels.

    Returns ``None`` when there are not enough bars to compute the SMA.
    """
    sma = simple_moving_average(bars, as_of, sma_window)
    if sma is None:
        return None

    aligned = _align_to_date(bars, as_of)
    # _align_to_date already returned at least sma_window bars (sma is not None),
    # so aligned is non-empty.
    latest_close = aligned[-1].close
    return latest_close >= sma


def price_to_high(
    bars: list[PriceBar],
    as_of: date,
    lookback_days: int,
) -> float | None:
    """Distance of the latest close from the trailing high, as a signed fraction.

    Uses ``PriceBar.close``. Returns
    ``latest_close / max(close over lookback) - 1.0``, so the result is
    ``0.0`` when the latest close is the period high and negative otherwise.

    Returns ``None`` when fewer than ``lookback_days`` bars exist at or
    before ``as_of``.
    """
    if lookback_days <= 0:
        raise ValueError(f"lookback_days must be positive, got {lookback_days}")

    aligned = _align_to_date(bars, as_of)
    if len(aligned) < lookback_days:
        return None

    closes = _extract_close_series(aligned[-lookback_days:])
    high = max(closes)
    if high <= 0:
        return None
    latest = closes[-1]
    return float(latest / high) - 1.0


# ---------------------------------------------------------------------------
# ATR (Average True Range)
# ---------------------------------------------------------------------------


def atr(
    bars: list[PriceBar],
    as_of: date,
    period: int = 14,
) -> Decimal | None:
    """Simple-average true range over ``period`` bars.

    Uses raw ``high`` / ``low`` / ``close`` (form-style) — ATR represents
    chart-level point movement, not return volatility.

    The true range for bar ``t`` is::

        TR_t = max(high_t - low_t,
                   |high_t - close_{t-1}|,
                   |low_t  - close_{t-1}|)

    The first bar in the window has no prior close, so ``period + 1`` bars
    are required. Returns ``None`` otherwise.
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")

    aligned = _align_to_date(bars, as_of)
    if len(aligned) < period + 1:
        return None

    window = aligned[-(period + 1) :]
    true_ranges: list[Decimal] = []
    for prev, curr in pairwise(window):
        hl = curr.high - curr.low
        hc = abs(curr.high - prev.close)
        lc = abs(curr.low - prev.close)
        true_ranges.append(max(hl, hc, lc))

    return _decimal_mean(true_ranges)


# ---------------------------------------------------------------------------
# Relative strength
# ---------------------------------------------------------------------------


def relative_strength(
    bars: list[PriceBar],
    benchmark_bars: list[PriceBar],
    as_of: date,
    lookback_days: int,
) -> float | None:
    """Excess return of ``bars`` over ``benchmark_bars`` across ``lookback_days``.

    Returns ``stock_return - benchmark_return`` using ``adj_close`` on both
    sides. Each leg is computed independently; both must have at least
    ``lookback_days + 1`` bars at or before ``as_of`` or the function
    returns ``None``.
    """
    stock_return = momentum(bars, as_of, lookback_days=lookback_days)
    bench_return = momentum(benchmark_bars, as_of, lookback_days=lookback_days)
    if stock_return is None or bench_return is None:
        return None
    return stock_return - bench_return


# ---------------------------------------------------------------------------
# Volume breakout
# ---------------------------------------------------------------------------


def volume_breakout(
    bars: list[PriceBar],
    as_of: date,
    recent_window: int = 20,
    history_window: int = 60,
    *,
    threshold: float = 1.5,
) -> bool:
    """Whether average volume in ``recent_window`` exceeds the prior baseline.

    Uses ``PriceBar.volume``. Returns ``True`` when

        avg(volume over last ``recent_window`` bars) >=
            threshold * avg(volume over the ``history_window`` bars
                            immediately preceding the recent window)

    Requires ``recent_window + history_window`` bars at or before ``as_of``.
    Returns ``False`` (not ``None``) when the window is too short — the
    contract is "is there a confirmed breakout?", and absence of evidence
    is a clear "no".
    """
    if recent_window <= 0 or history_window <= 0:
        raise ValueError(
            f"recent_window and history_window must be positive, "
            f"got {recent_window=} {history_window=}"
        )
    if threshold <= 0:
        raise ValueError(f"threshold must be positive, got {threshold}")

    aligned = _align_to_date(bars, as_of)
    needed = recent_window + history_window
    if len(aligned) < needed:
        return False

    volumes = _extract_volume_series(aligned)
    recent = volumes[-recent_window:]
    history = volumes[-needed:-recent_window]

    history_avg = sum(history) / len(history)
    if history_avg <= 0:
        return False
    recent_avg = sum(recent) / len(recent)
    return recent_avg >= threshold * history_avg


# ---------------------------------------------------------------------------
# Realized volatility
# ---------------------------------------------------------------------------


def realized_volatility(
    bars: list[PriceBar],
    as_of: date,
    lookback_days: int,
    annualize: bool = True,
) -> float | None:
    """Sample standard deviation of daily log returns on ``adj_close``.

    Returns ``None`` when fewer than ``lookback_days + 1`` bars exist (we
    need ``lookback_days`` returns, which requires one extra bar for the
    base price).

    With ``annualize=True`` the result is multiplied by
    ``sqrt(TRADING_DAYS_PER_YEAR)`` to give an annualized number. The
    sample standard deviation uses Bessel's correction (``n - 1``).
    """
    if lookback_days <= 1:
        raise ValueError(f"lookback_days must be > 1, got {lookback_days}")

    aligned = _align_to_date(bars, as_of)
    if len(aligned) < lookback_days + 1:
        return None

    window = aligned[-(lookback_days + 1) :]
    closes = _extract_adj_close_series(window)
    if any(c <= 0 for c in closes):
        return None

    log_returns: list[float] = [
        math.log(float(curr) / float(prev)) for prev, curr in pairwise(closes)
    ]

    n = len(log_returns)
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
    daily_std = math.sqrt(variance)
    if not annualize:
        return daily_std
    return daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)


__all__ = [
    "TRADING_DAYS_PER_MONTH",
    "TRADING_DAYS_PER_YEAR",
    "momentum",
    "momentum_12_1",
    "momentum_6m",
    "momentum_3m",
    "simple_moving_average",
    "is_above_sma",
    "price_to_high",
    "atr",
    "relative_strength",
    "volume_breakout",
    "realized_volatility",
]
