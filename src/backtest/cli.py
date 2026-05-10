"""Command-line entry point for backtest runs.

Usage::

    python -m src.backtest.cli run \\
        --strategy buy_and_hold \\
        --ticker SPY \\
        --period 2020-2024 \\
        --csv path/to/spy.csv \\
        --output report.json

The ``--csv`` flag accepts a CSV with header row
``date,open,high,low,close,adj_close,volume`` (Yahoo Finance's standard
download format works as-is). For SPY calibration runs the reviewer
points it at a fresh download from WP-1.1's data adapter.

Without ``--csv``, the CLI falls back to a deterministic synthetic
series — useful for smoke-testing the pipeline but obviously NOT a
calibration substitute.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.strategies import (
    BuyAndHoldParameters,
    BuyAndHoldStrategy,
    make_single_stock_universe,
)
from src.contracts import Account, AccountType, Currency, PriceBar

logger = logging.getLogger("src.backtest.cli")

INITIAL_CAPITAL = Decimal("100000.00")


def _parse_period(period: str) -> tuple[date, date]:
    """Accept either ``YYYY-YYYY`` or ``YYYY-MM-DD:YYYY-MM-DD``."""
    if ":" in period:
        start_s, end_s = period.split(":", 1)
        return date.fromisoformat(start_s), date.fromisoformat(end_s)
    if "-" in period and len(period) == 9:
        start_year_s, end_year_s = period.split("-", 1)
        return date(int(start_year_s), 1, 1), date(int(end_year_s), 12, 31)
    raise ValueError(f"Cannot parse period {period!r}; use YYYY-YYYY or YYYY-MM-DD:YYYY-MM-DD")


def _load_csv_bars(path: Path, ticker: str) -> list[PriceBar]:
    """Load bars from a Yahoo-Finance-style CSV."""
    from src.contracts import Market

    def _pick(row: dict[str, str], *keys: str) -> str:
        for k in keys:
            v = row.get(k)
            if v is not None and v != "":
                return v
        raise KeyError(f"None of {keys} present in row {row}")

    bars: list[PriceBar] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = date.fromisoformat(_pick(row, "date", "Date")[:10])
            close = _pick(row, "close", "Close")
            adj_close = _pick(row, "adj_close", "Adj Close", "close", "Close")
            volume_raw = _pick(row, "volume", "Volume")
            bars.append(
                PriceBar(
                    code=ticker,
                    market=Market.US,
                    date=d,
                    open=Decimal(_pick(row, "open", "Open")),
                    high=Decimal(_pick(row, "high", "High")),
                    low=Decimal(_pick(row, "low", "Low")),
                    close=Decimal(close),
                    adj_close=Decimal(adj_close),
                    volume=int(float(volume_raw)),
                )
            )
    bars.sort(key=lambda b: b.date)
    return bars


def _synthetic_bars(ticker: str, start: date, end: date) -> list[PriceBar]:
    """Deterministic ramp — diagnostic-only fallback."""
    from src.contracts import Market

    bars: list[PriceBar] = []
    cur = start
    price = Decimal("100.00")
    while cur <= end:
        if cur.weekday() < 5:
            close = price.quantize(Decimal("0.01"))
            bars.append(
                PriceBar(
                    code=ticker,
                    market=Market.US,
                    date=cur,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adj_close=close,
                    volume=1_000_000,
                )
            )
            price += Decimal("0.05")
        cur += timedelta(days=1)
    return bars


def _serialize_result(result: BacktestResult) -> dict:
    """Render a BacktestResult into a JSON-friendly dict."""

    def _money(d: Decimal) -> str:
        return f"{d:.2f}"

    return {
        "account_final": {
            "id": result.account_final.id,
            "cash": _money(result.account_final.cash),
            "currency": result.account_final.currency.value,
        },
        "metrics": {
            "total_return": result.metrics.total_return,
            "annual_return": result.metrics.annual_return,
            "sharpe": result.metrics.sharpe,
            "sortino": result.metrics.sortino,
            "max_drawdown": result.metrics.max_drawdown,
            "calmar": result.metrics.calmar,
            "win_rate": result.metrics.win_rate,
            "avg_holding_days": result.metrics.avg_holding_days,
        },
        "trades_count": len(result.trades),
        "snapshots_count": len(result.performance_snapshots),
        "first_snapshot": (
            {
                "date": result.performance_snapshots[0].date.isoformat(),
                "nav": _money(result.performance_snapshots[0].nav),
            }
            if result.performance_snapshots
            else None
        ),
        "last_snapshot": (
            {
                "date": result.performance_snapshots[-1].date.isoformat(),
                "nav": _money(result.performance_snapshots[-1].nav),
            }
            if result.performance_snapshots
            else None
        ),
    }


def cmd_run(args: argparse.Namespace) -> int:
    if args.strategy != "buy_and_hold":
        sys.stderr.write(
            f"Strategy {args.strategy!r} is not bundled with the backtest CLI. "
            "Real strategies live in src/strategies/ — invoke the engine directly.\n"
        )
        return 2

    start, end = _parse_period(args.period)
    ticker = args.ticker.upper()

    if args.csv:
        bars = _load_csv_bars(Path(args.csv), ticker)
        bars = [b for b in bars if start <= b.date <= end]
        if not bars:
            sys.stderr.write(f"No bars in {args.csv} fall within {start}..{end}. Aborting.\n")
            return 3
    else:
        sys.stderr.write(
            "WARNING: --csv not provided. Using synthetic bars; calibration vs. "
            "Yahoo Finance is meaningless.\n"
        )
        bars = _synthetic_bars(ticker, start, end)

    universe = make_single_stock_universe(ticker)
    account = Account(
        id="cli-account",
        type=AccountType.SHADOW,
        strategy_id="buy-and-hold",
        currency=Currency.USD,
        cash=INITIAL_CAPITAL,
        initial_capital=INITIAL_CAPITAL,
        created_at=datetime.combine(start, datetime.min.time()),
    )
    parameters = BuyAndHoldParameters(ticker=ticker, monthly=True)
    strategy = BuyAndHoldStrategy(parameters=parameters)
    engine = BacktestEngine(
        strategy=strategy,
        account=account,
        universe=universe,
        historical_data={ticker: bars},
        start_date=start,
        end_date=end,
    )
    result = engine.run()
    payload = _serialize_result(result)

    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2))
        print(f"Wrote {args.output}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="src.backtest.cli", description="V0.1 backtest CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a single backtest")
    run.add_argument("--strategy", required=True, choices=["buy_and_hold"])
    run.add_argument("--ticker", required=True)
    run.add_argument("--period", required=True, help="YYYY-YYYY or YYYY-MM-DD:YYYY-MM-DD")
    run.add_argument("--csv", help="Path to CSV bars (Yahoo Finance-style)")
    run.add_argument("--output", help="Write JSON report here (default: stdout)")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    parser.error(f"Unknown command {args.cmd}")
    return 1  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
