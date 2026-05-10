"""Backtest-bundled calibration strategies.

The only concrete strategy this WP is allowed to ship is
:class:`BuyAndHoldStrategy` — used as the V0.1 baseline against which
every real strategy will be measured. Real strategies live in
``src/strategies/`` and land in WP-2.2 / 2.3 / 2.4.
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
)
from src.strategies.base import StrategyBase


class BuyAndHoldParameters(StrategyParameters):
    """Buys ``ticker`` once a month at the first available trading day; never sells."""

    ticker: str
    position_size_pct: float = 1.0  # commit available cash to the ticker each buy day
    monthly: bool = True


class BuyAndHoldStrategy(StrategyBase):
    """V0.1 baseline. Buys the configured ticker on the first trading day of
    each month (or just once if ``monthly=False``); never exits.

    Useful as a calibration anchor — for SPY, total return over a
    multi-year window must reproduce Yahoo Finance's published number
    within ±0.5% (acceptance gate for WP-2.7).
    """

    name = "BuyAndHold"
    type = StrategyType.BUILT_IN

    def __init__(self, parameters: BuyAndHoldParameters) -> None:
        self.parameters = parameters
        self._last_buy_month: tuple[int, int] | None = None
        self._fired_once = False

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        target = self.parameters.ticker
        return [s for s in universe if s.code == target]

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        if not candidates:
            return []

        if self.parameters.monthly:
            current_month = (date.year, date.month)
            if self._last_buy_month == current_month:
                return []
            self._last_buy_month = current_month
        else:
            if self._fired_once:
                return []
            self._fired_once = True

        stock = candidates[0]
        return [
            Signal(
                id=f"buy-and-hold-{date.isoformat()}",
                strategy_id="buy-and-hold",
                stock_code=stock.code,
                market=stock.market,
                direction=SignalDirection.BUY,
                position_size_pct=self.parameters.position_size_pct,
                confidence=1.0,
                reason_code="MONTHLY_BUY" if self.parameters.monthly else "INITIAL_BUY",
                generated_at=datetime.combine(date, datetime.min.time()),
            )
        ]

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="BUY_AND_HOLD")

    def get_score(self, stock: Stock, date: date) -> float:
        return 1.0 if stock.code == self.parameters.ticker else 0.0


def make_single_stock_universe(ticker: str, market: Market = Market.US) -> list[Stock]:
    """Convenience: build a one-stock universe for buy-and-hold runs."""
    from src.contracts import currency_for_market

    return [
        Stock(
            code=ticker,
            market=market,
            currency=currency_for_market(market),
            name=ticker,
            market_cap=Decimal("0"),
        )
    ]
