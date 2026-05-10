"""
Data acquisition CLI.

Subcommands
-----------
* ``fetch``  — pull the configured universe and persist to the DB
* ``check``  — run integrity checks over what's already in the DB

Exit codes
~~~~~~~~~~
* 0 — success
* 2 — network / fetch failure
* 3 — data integrity check failed

These map cleanly onto cron / CI signals — non-zero means "human, look".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import structlog

from src.contracts import Market, PriceBar
from src.data.repository import PriceBarRepository, StockRepository
from src.data.universe import get_us_universe
from src.data.yfinance_adapter import DataFetchError, YFinanceAdapter
from src.db.session import session_scope

log = structlog.get_logger(__name__)

# Exit codes — referenced by tests and external schedulers.
EXIT_OK = 0
EXIT_NETWORK = 2
EXIT_INTEGRITY = 3


_PERIOD_DAYS = {
    "1m": 31,
    "3m": 92,
    "6m": 184,
    "1y": 366,
    "2y": 366 * 2,
    "5y": 366 * 5,
}


def _parse_period(value: str) -> int:
    if value not in _PERIOD_DAYS:
        raise argparse.ArgumentTypeError(
            f"Unknown period '{value}'. Choose from: {sorted(_PERIOD_DAYS)}"
        )
    return _PERIOD_DAYS[value]


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    message: str


def fetch(market: str, period_days: int) -> int:
    if market.lower() != "us":
        log.error("Unsupported market for V0.1", market=market)
        return EXIT_NETWORK
    end = date.today()
    start = end - timedelta(days=period_days)
    tickers = get_us_universe()
    adapter = YFinanceAdapter()

    log.info("Starting fetch", market="US", tickers=len(tickers), start=str(start), end=str(end))

    async def _run() -> tuple[int, int]:
        bars_total = 0
        stocks_written = 0
        with session_scope() as session:
            stock_repo = StockRepository(session)
            bar_repo = PriceBarRepository(session)

            sem = asyncio.Semaphore(8)

            async def one(code: str) -> tuple[str, list[PriceBar]] | None:
                async with sem:
                    try:
                        bars = await adapter.fetch_price_bars(code, start, end)
                        return code, bars
                    except DataFetchError as exc:
                        log.warning("Skipping ticker — fetch failed", code=code, error=str(exc))
                        return None

            results = await asyncio.gather(*(one(t) for t in tickers))
            for r in results:
                if r is None:
                    continue
                code, bars = r
                if not bars:
                    continue
                bar_repo.upsert_many(bars)
                bars_total += len(bars)
                # Best-effort metadata enrichment; never blocks the bar write.
                try:
                    stock = await adapter.fetch_stock_metadata(code)
                    stock_repo.upsert(stock)
                    stocks_written += 1
                except DataFetchError as exc:
                    log.warning("Metadata fetch failed", code=code, error=str(exc))
        return stocks_written, bars_total

    try:
        stocks_written, bars_total = asyncio.run(_run())
    except DataFetchError as exc:
        log.error("Fetch failed", error=str(exc))
        return EXIT_NETWORK

    log.info("Fetch complete", stocks=stocks_written, bars=bars_total)
    print(f"Fetched {stocks_written} stocks, {bars_total} bars.")
    return EXIT_OK


def check(market: str) -> int:
    if market.lower() != "us":
        log.error("Unsupported market for V0.1", market=market)
        return EXIT_INTEGRITY
    issues: list[IntegrityIssue] = []
    bar_total = 0
    stock_total = 0
    with session_scope() as session:
        stock_repo = StockRepository(session)
        bar_repo = PriceBarRepository(session)
        stocks = stock_repo.list_by_market(Market.US)
        stock_total = len(stocks)
        bar_total = bar_repo.count(market=Market.US)
        for stock in stocks:
            bars = bar_repo.get_range(stock.code, date(1970, 1, 1), date.today(), Market.US)
            issues.extend(_validate_bars(stock.code, bars))

    print(f"{stock_total} stocks, {bar_total} bars, {len(issues)} issues")
    for issue in issues[:20]:
        print(f"  [{issue.code}] {issue.message}")
    if len(issues) > 20:
        print(f"  ... and {len(issues) - 20} more")
    return EXIT_INTEGRITY if issues else EXIT_OK


def _validate_bars(code: str, bars: list[PriceBar]) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    zero = Decimal(0)
    for bar in bars:
        if bar.open <= zero or bar.high <= zero or bar.low <= zero or bar.close <= zero:
            issues.append(IntegrityIssue(code, f"Non-positive price on {bar.date}"))
            continue
        if bar.volume < 0:
            issues.append(IntegrityIssue(code, f"Negative volume on {bar.date}"))
        if bar.high < max(bar.open, bar.close, bar.low):
            issues.append(IntegrityIssue(code, f"high < max(o,c,l) on {bar.date}"))
        if bar.low > min(bar.open, bar.close, bar.high):
            issues.append(IntegrityIssue(code, f"low > min(o,c,h) on {bar.date}"))
    # Trading-day gap heuristic: flag any business-day gap > 5 days. We
    # accept holidays/weekends; only large gaps mean missing data.
    from itertools import pairwise

    for prev, curr in pairwise(bars):
        gap = (curr.date - prev.date).days
        if gap > 7:
            issues.append(
                IntegrityIssue(code, f"Gap of {gap} days between {prev.date} and {curr.date}")
            )
    return issues


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.data.cli",
        description="Market data fetch / integrity CLI.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch and persist daily bars.")
    fetch_p.add_argument("--market", default="us", help="Market code (V0.1: only 'us').")
    fetch_p.add_argument(
        "--period",
        type=_parse_period,
        default=_PERIOD_DAYS["1y"],
        help="Lookback window. Choices: 1m / 3m / 6m / 1y / 2y / 5y.",
    )

    check_p = sub.add_parser("check", help="Validate persisted bars.")
    check_p.add_argument("--market", default="us")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        return fetch(args.market, args.period)
    if args.cmd == "check":
        return check(args.market)
    parser.error(f"Unknown subcommand: {args.cmd}")
    return 1  # unreachable but mypy-friendly


if __name__ == "__main__":
    sys.exit(main())
