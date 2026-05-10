"""position_size_pct uses NAV (cash + positions MTM) as base; cash-insufficient
BUYs scale down (partial fill), don't raise.

Per architecture.md §10.5 #8 + INVARIANT #B4.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from src.backtest.engine import BacktestEngine
from src.backtest.execution import US_DEFAULT_COST
from src.contracts import (
    Account,
    AccountType,
    Currency,
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
from tests.backtest.conftest import synthetic_bars


class TwoBuysSameDayStrategy(StrategyBase):
    """Fires two BUYs (different symbols) on the first trading day."""

    name = "TwoBuysSameDay"
    type = StrategyType.BUILT_IN

    def __init__(
        self, codes: list[str], pcts: list[float], confidences: list[float] | None = None
    ) -> None:
        self.parameters = StrategyParameters()
        self._codes = codes
        self._pcts = pcts
        self._confidences = confidences or [1.0] * len(codes)
        self._fired = False

    def screen(self, universe, date):
        return [s for s in universe if s.code in self._codes]

    def generate_signals(self, candidates, date):
        if self._fired:
            return []
        self._fired = True
        sigs: list[Signal] = []
        # Emit in REVERSE alphabetical order to test that the engine sorts them.
        for code, pct, conf in zip(
            sorted(self._codes, reverse=True),
            self._pcts,
            self._confidences,
            strict=False,
        ):
            sigs.append(
                Signal(
                    id=f"sig-{code}",
                    strategy_id="two-buys",
                    stock_code=code,
                    market=Market.US,
                    direction=SignalDirection.BUY,
                    position_size_pct=pct,
                    confidence=conf,
                    reason_code="TWO_BUYS",
                    generated_at=datetime.combine(date, datetime.min.time()),
                )
            )
        return sigs

    def exit_rules(self, position: Position, date):
        return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

    def get_score(self, stock: Stock, date):
        return 1.0 if stock.code in self._codes else 0.0


def _make_account(cash: Decimal) -> Account:
    return Account(
        id="acct-sizing",
        type=AccountType.SHADOW,
        strategy_id="sizing",
        currency=Currency.USD,
        cash=cash,
        initial_capital=cash,
        created_at=datetime(2024, 1, 1),
    )


def _universe() -> list[Stock]:
    return [
        Stock(code="AAA", market=Market.US, currency=Currency.USD, name="A"),
        Stock(code="BBB", market=Market.US, currency=Currency.USD, name="B"),
    ]


def test_position_size_pct_base_is_initial_nav_when_no_holdings() -> None:
    """First BUY at 50% of NAV — with no holdings yet, NAV = cash, so the
    notional should be ~50% of starting cash."""
    bars = {
        "AAA": synthetic_bars(
            "AAA",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("0"),
        ),
        "BBB": synthetic_bars(
            "BBB",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("0"),
        ),
    }
    strategy = TwoBuysSameDayStrategy(codes=["AAA"], pcts=[0.5])
    engine = BacktestEngine(
        strategy=strategy,
        account=_make_account(Decimal("100000")),
        universe=_universe(),
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buy = next(t for t in result.trades if t.direction == SignalDirection.BUY)
    notional = buy.quantity * buy.price
    assert Decimal("49000") <= notional <= Decimal("51000")


def test_two_50pct_buys_partial_fill_when_cash_insufficient() -> None:
    """Two signals each asking for 50% of NAV (= 60k each) total 120k > 100k cash.
    Engine should partial-fill by deducting cash as it goes; second BUY ends up
    smaller than first."""
    bars = {
        "AAA": synthetic_bars(
            "AAA",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("0"),
        ),
        "BBB": synthetic_bars(
            "BBB",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("0"),
        ),
    }
    # Both BUYs: confidence 1.0, ordering by stock_code → AAA first, BBB second.
    strategy = TwoBuysSameDayStrategy(codes=["AAA", "BBB"], pcts=[0.6, 0.6])
    engine = BacktestEngine(
        strategy=strategy,
        account=_make_account(Decimal("100000")),
        universe=_universe(),
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    # Both should fill, but second is smaller.
    aaa_buys = [
        t for t in result.trades if t.direction == SignalDirection.BUY and t.stock_code == "AAA"
    ]
    bbb_buys = [
        t for t in result.trades if t.direction == SignalDirection.BUY and t.stock_code == "BBB"
    ]
    assert len(aaa_buys) == 1
    assert len(bbb_buys) == 1
    # AAA gets ~60% of NAV first; BBB gets the leftover (~40% of original cash).
    assert aaa_buys[0].quantity > bbb_buys[0].quantity


def test_buy_does_not_raise_when_cash_completely_drained() -> None:
    """100% of NAV BUY with very low cash — engine partial-fills, no crash.

    Signal.position_size_pct is constrained to [0, 1] by the contract;
    "request more than cash supports" is naturally exercised by 1.0 of NAV
    against an already-drained account.
    """
    bars = {
        "AAA": synthetic_bars(
            "AAA",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("0"),
        ),
        "BBB": synthetic_bars(
            "BBB",
            date(2024, 1, 1),
            date(2024, 1, 31),
            start_price=Decimal("100"),
            drift_per_day=Decimal("0"),
        ),
    }
    # 100% of NAV BUY against $10k cash, $100 share price → 100 shares fillable.
    strategy = TwoBuysSameDayStrategy(codes=["AAA"], pcts=[1.0])
    engine = BacktestEngine(
        strategy=strategy,
        account=_make_account(Decimal("10000")),
        universe=_universe(),
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buys = [t for t in result.trades if t.direction == SignalDirection.BUY]
    assert len(buys) == 1
    # Notional should not exceed initial cash.
    assert (buys[0].quantity * buys[0].price) <= Decimal("10000")
