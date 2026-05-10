"""Calibration strategies for backtest engine self-validation.

NOT a production strategy library. These exist solely to validate that
the backtest engine produces correct numbers (e.g., SPY lump-sum
buy-and-hold matches yfinance public data within ±2%).

Files prefixed with ``_`` are excluded from
``scripts/verify_invariants.py``'s strategy subclass scan, so these
classes don't trip INVARIANT #6 (every concrete StrategyBase subclass
must implement all four abstract methods — they DO, but they're not
production strategies and shouldn't be discovered as such).

For real strategies, see ``src/strategies/`` (Phase 2 / WP-2.x).

**Calibration exception (per architecture.md §10.5 #2 +
src/backtest/INVARIANTS.md #B3)**: BuyAndHoldStrategy may use
T-day-close decide + T-day-close execute (no T+1 open) because it
issues exactly one BUY at T0 and never SELLs — there is no
look-ahead risk. Tests using this exemption MUST declare it in
their docstring. The actual engine still runs T+1 logic; the
"exemption" is conceptual: a calibration test that pre-loads the
account on day 0 and reads the result on day N skips the T+1 open
nuance because the open price equals the close price for the SAME
position throughout (no second fill ever happens).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from src.contracts import (
    ExitAction,
    ExitDecision,
    Market,
    Position,
    Signal,
    SignalDirection,
    Stock,
    StrategyParameters,
    StrategyType,
    currency_for_market,
)
from src.strategies.base import StrategyBase


class BuyAndHoldStrategy(StrategyBase):
    """T0 lump-sum buy of a single ticker, hold to end_date.

    CALIBRATION-ONLY. Used to verify the engine reproduces SPY 5-year
    buy-and-hold returns within ±2% of yfinance public data.

    State: ``_bought`` flag flips True after the first emitted signal
    so subsequent steps emit nothing.
    """

    name: str = "buy_and_hold"
    type: StrategyType = StrategyType.BUILT_IN  # ignored; not in production list

    def __init__(
        self,
        ticker: str,
        parameters: StrategyParameters | None = None,
        position_size_pct: float = 1.0,
    ) -> None:
        self.ticker = ticker
        self.parameters = parameters or StrategyParameters()
        self._position_size_pct = position_size_pct
        self._bought = False

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        return [s for s in universe if s.code == self.ticker]

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        if self._bought or not candidates:
            return []
        self._bought = True
        stock = candidates[0]
        return [
            Signal(
                id=f"buy-and-hold-{date.isoformat()}",
                strategy_id="buy-and-hold",
                stock_code=stock.code,
                market=stock.market,
                direction=SignalDirection.BUY,
                position_size_pct=self._position_size_pct,
                confidence=1.0,
                reason_code="LUMP_SUM_T0",
                generated_at=datetime.combine(date, datetime.min.time()),
            )
        ]

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="BUY_AND_HOLD")

    def get_score(self, stock: Stock, date: date) -> float:
        return 1.0 if stock.code == self.ticker else 0.0


def make_single_stock_universe(ticker: str, market: Market = Market.US) -> list[Stock]:
    """Convenience: build a one-stock universe for buy-and-hold runs."""
    return [
        Stock(
            code=ticker,
            market=market,
            currency=currency_for_market(market),
            name=ticker,
            market_cap=Decimal("0"),
        )
    ]
