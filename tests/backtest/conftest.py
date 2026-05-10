"""Shared fixtures for backtest tests."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from src.contracts import (
    Account,
    AccountType,
    Currency,
    ExitAction,
    ExitDecision,
    Market,
    Position,
    PriceBar,
    Signal,
    SignalDirection,
    Stock,
    StrategyParameters,
    StrategyType,
)
from src.strategies.base import StrategyBase

# Skip US market holidays / weekends in synthetic data — we use NYSE working days.
_WEEKEND = {5, 6}


def _trading_day(d: date) -> bool:
    return d.weekday() not in _WEEKEND


def synthetic_bars(
    code: str,
    start: date,
    end: date,
    start_price: Decimal = Decimal("100"),
    drift_per_day: Decimal = Decimal("0.10"),
) -> list[PriceBar]:
    """Build a deterministic ramp of bars, weekdays only.

    ``drift_per_day`` is added linearly to the close every trading day.
    open/high/low set around close so OHLC invariants hold.
    """
    bars: list[PriceBar] = []
    cur = start
    price = start_price
    while cur <= end:
        if _trading_day(cur):
            close = price.quantize(Decimal("0.01"))
            bars.append(
                PriceBar(
                    code=code,
                    market=Market.US,
                    date=cur,
                    open=close,
                    high=(close * Decimal("1.001")).quantize(Decimal("0.01")),
                    low=(close * Decimal("0.999")).quantize(Decimal("0.01")),
                    close=close,
                    adj_close=close,
                    volume=1_000_000,
                )
            )
            price += drift_per_day
        cur += timedelta(days=1)
    return bars


def sinusoidal_bars(
    code: str,
    start: date,
    end: date,
    base: Decimal = Decimal("100"),
    amplitude: Decimal = Decimal("10"),
    period_days: int = 50,
) -> list[PriceBar]:
    """Build a deterministic sinusoidal series — useful for win/loss alternation."""
    bars: list[PriceBar] = []
    cur = start
    i = 0
    while cur <= end:
        if _trading_day(cur):
            close = (
                base + amplitude * Decimal(str(math.sin(2 * math.pi * i / period_days)))
            ).quantize(Decimal("0.01"))
            bars.append(
                PriceBar(
                    code=code,
                    market=Market.US,
                    date=cur,
                    open=close,
                    high=(close * Decimal("1.001")).quantize(Decimal("0.01")),
                    low=(close * Decimal("0.999")).quantize(Decimal("0.01")),
                    close=close,
                    adj_close=close,
                    volume=1_000_000,
                )
            )
            i += 1
        cur += timedelta(days=1)
    return bars


@pytest.fixture
def synthetic_universe() -> list[Stock]:
    return [
        Stock(code="AAA", market=Market.US, currency=Currency.USD, name="A Inc."),
        Stock(code="BBB", market=Market.US, currency=Currency.USD, name="B Inc."),
    ]


@pytest.fixture
def synthetic_account() -> Account:
    return Account(
        id="acct-test",
        type=AccountType.SHADOW,
        strategy_id="strat-test",
        currency=Currency.USD,
        cash=Decimal("100000.00"),
        initial_capital=Decimal("100000.00"),
        created_at=datetime(2024, 1, 1),
    )


class StaticBuyOnceStrategy(StrategyBase):
    """Buys ``code`` on the first trading day, holds forever.

    Useful as a minimal end-to-end strategy that doesn't need the
    factor library or any signal logic.
    """

    name = "StaticBuyOnce"
    type = StrategyType.BUILT_IN

    def __init__(self, code: str, position_pct: float = 0.5) -> None:
        self.parameters = StrategyParameters()
        self._code = code
        self._position_pct = position_pct
        self._fired = False

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        return [s for s in universe if s.code == self._code]

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        if self._fired or not candidates:
            return []
        self._fired = True
        return [
            Signal(
                id=f"sig-{date.isoformat()}",
                strategy_id="strat-test",
                stock_code=self._code,
                market=Market.US,
                direction=SignalDirection.BUY,
                position_size_pct=self._position_pct,
                confidence=1.0,
                reason_code="STATIC_BUY",
                generated_at=datetime.combine(date, datetime.min.time()),
            )
        ]

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="STATIC_HOLD")

    def get_score(self, stock: Stock, date: date) -> float:
        return 1.0 if stock.code == self._code else 0.0


class BuyAndExitAfterNDaysStrategy(StrategyBase):
    """Buy on day 1, fully exit after ``hold_days`` trading days.

    Used to exercise the SELL path and trade-stat calculation.
    """

    name = "BuyAndExitAfterNDays"
    type = StrategyType.BUILT_IN

    def __init__(self, code: str, hold_days: int = 5, position_pct: float = 0.5) -> None:
        self.parameters = StrategyParameters()
        self._code = code
        self._hold_days = hold_days
        self._position_pct = position_pct
        self._fired = False
        self._opened_on: date | None = None

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        return [s for s in universe if s.code == self._code]

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        if self._fired or not candidates:
            return []
        self._fired = True
        self._opened_on = date
        return [
            Signal(
                id=f"sig-{date.isoformat()}",
                strategy_id="strat-test",
                stock_code=self._code,
                market=Market.US,
                direction=SignalDirection.BUY,
                position_size_pct=self._position_pct,
                confidence=1.0,
                reason_code="STATIC_BUY",
                generated_at=datetime.combine(date, datetime.min.time()),
            )
        ]

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        if self._opened_on and (date - self._opened_on).days >= self._hold_days:
            return ExitDecision(action=ExitAction.EXIT, reason_code="HOLD_PERIOD_OVER")
        return ExitDecision(action=ExitAction.HOLD, reason_code="WAITING")

    def get_score(self, stock: Stock, date: date) -> float:
        return 1.0


class CheatingFutureReadStrategy(StrategyBase):
    """Asks the data view for a future bar — must be blocked by LookaheadBiasError.

    Used by ``test_no_lookahead.py`` to confirm the engine actively
    refuses lookahead.
    """

    name = "CheatingFutureRead"
    type = StrategyType.BUILT_IN

    def __init__(self) -> None:
        self.parameters = StrategyParameters()

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        return universe

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        return []

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

    def get_score(self, stock: Stock, date: date) -> float:
        return 0.0


class DataAccessAuditStrategy(StrategyBase):
    """Records every (code, date) it reads, so a test can assert no lookahead."""

    name = "DataAccessAudit"
    type = StrategyType.BUILT_IN

    def __init__(self, view_provider) -> None:
        self.parameters = StrategyParameters()
        self._view_provider = view_provider
        self.reads: list[tuple[str, date]] = []

    def _peek_view(self, code: str, date: date) -> None:
        view = self._view_provider()
        if view is None:
            return
        for bar in view.get_bars(code):
            self.reads.append((code, bar.date))

    def screen(self, universe: list[Stock], date: date) -> list[Stock]:
        for s in universe:
            self._peek_view(s.code, date)
        return list(universe)

    def generate_signals(self, candidates: list[Stock], date: date) -> list[Signal]:
        return []

    def exit_rules(self, position: Position, date: date) -> ExitDecision:
        return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

    def get_score(self, stock: Stock, date: date) -> float:
        return 0.0
