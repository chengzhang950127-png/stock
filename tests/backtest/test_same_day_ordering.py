"""Same-day SELL → BUY ordering and deterministic BUY tiebreak.

Per architecture.md §10.5 #9 + INVARIANT #B4.
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


class TwoBuysWithConfidencesStrategy(StrategyBase):
    """Two BUYs with controllable confidences; tests determinism of tiebreak."""

    name = "TwoBuysConfidence"
    type = StrategyType.BUILT_IN

    def __init__(
        self,
        codes_pcts_confs: list[tuple[str, float, float]],
        emit_order: list[int],
    ) -> None:
        self.parameters = StrategyParameters()
        self._codes_pcts_confs = codes_pcts_confs
        self._emit_order = emit_order
        self._fired = False

    def screen(self, universe, date):
        codes = {c for c, _, _ in self._codes_pcts_confs}
        return [s for s in universe if s.code in codes]

    def generate_signals(self, candidates, date):
        if self._fired:
            return []
        self._fired = True
        sigs: list[Signal] = []
        for idx in self._emit_order:
            code, pct, conf = self._codes_pcts_confs[idx]
            sigs.append(
                Signal(
                    id=f"sig-{code}",
                    strategy_id="two-conf",
                    stock_code=code,
                    market=Market.US,
                    direction=SignalDirection.BUY,
                    position_size_pct=pct,
                    confidence=conf,
                    reason_code="TIEBREAK",
                    generated_at=datetime.combine(date, datetime.min.time()),
                )
            )
        return sigs

    def exit_rules(self, position: Position, date):
        return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

    def get_score(self, stock: Stock, date):
        return 1.0


def _account(cash: Decimal) -> Account:
    return Account(
        id="acct-order",
        type=AccountType.SHADOW,
        strategy_id="order",
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


def _bars() -> dict:
    return {
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


def test_higher_confidence_buy_fills_first() -> None:
    """When two BUYs have different confidences, the higher one fills first
    regardless of strategy emit order."""
    # AAA: 0.3 confidence, BBB: 0.9 confidence — BBB should fill first.
    triples = [("AAA", 0.6, 0.3), ("BBB", 0.6, 0.9)]
    # Emit AAA first then BBB to test the engine sorts them, not relies on order.
    strategy = TwoBuysWithConfidencesStrategy(triples, emit_order=[0, 1])
    engine = BacktestEngine(
        strategy=strategy,
        account=_account(Decimal("100000")),
        universe=_universe(),
        historical_data=_bars(),
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buy_trades_in_order = sorted(
        [t for t in result.trades if t.direction == SignalDirection.BUY],
        key=lambda t: t.executed_at,
    )
    # Both should be on the same day (T+1 of the strategy fire). Order
    # within the day reflects (-confidence, stock_code) tiebreak.
    same_day_trades = [
        t for t in buy_trades_in_order if t.executed_at == buy_trades_in_order[0].executed_at
    ]
    assert same_day_trades[0].stock_code == "BBB", (
        f"Higher-confidence (BBB, 0.9) should execute before AAA (0.3); got order {[t.stock_code for t in same_day_trades]}"
    )


def test_equal_confidence_buys_break_tie_by_stock_code_ascending() -> None:
    """Equal confidence → alphabetical stock_code wins."""
    triples = [("BBB", 0.5, 0.7), ("AAA", 0.5, 0.7)]
    strategy = TwoBuysWithConfidencesStrategy(triples, emit_order=[0, 1])  # emit BBB first
    engine = BacktestEngine(
        strategy=strategy,
        account=_account(Decimal("100000")),
        universe=_universe(),
        historical_data=_bars(),
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    buys_sorted = sorted(
        [t for t in result.trades if t.direction == SignalDirection.BUY],
        key=lambda t: t.executed_at,
    )
    same_day = [t for t in buys_sorted if t.executed_at == buys_sorted[0].executed_at]
    assert same_day[0].stock_code == "AAA"


def test_emit_order_does_not_affect_fill_order_when_confidence_differs() -> None:
    """Determinism: same triples in different emit order produce the same
    fill order in BacktestResult.trades."""
    triples = [("AAA", 0.4, 0.3), ("BBB", 0.4, 0.9)]

    s1 = TwoBuysWithConfidencesStrategy(triples, emit_order=[0, 1])
    s2 = TwoBuysWithConfidencesStrategy(triples, emit_order=[1, 0])

    def run(strategy):
        engine = BacktestEngine(
            strategy=strategy,
            account=_account(Decimal("100000")),
            universe=_universe(),
            historical_data=_bars(),
            cost_model=US_DEFAULT_COST,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        return engine.run()

    r1 = run(s1)
    r2 = run(s2)

    buys1 = [t.stock_code for t in r1.trades if t.direction == SignalDirection.BUY]
    buys2 = [t.stock_code for t in r2.trades if t.direction == SignalDirection.BUY]
    assert buys1 == buys2, f"Non-deterministic fill order: {buys1} vs {buys2}"


def test_sell_executes_before_buy_on_same_day() -> None:
    """Setup: hold AAA, then strategy fires both an EXIT for AAA and a BUY
    for BBB on the same day. SELL releases cash first, BUY gets to use it."""
    from datetime import datetime as _dt

    class HoldThenRotateStrategy(StrategyBase):
        name = "HoldThenRotate"
        type = StrategyType.BUILT_IN

        def __init__(self) -> None:
            self.parameters = StrategyParameters()
            self._opened = False
            self._open_date: date | None = None
            self._rotated = False

        def screen(self, universe, date):
            return [s for s in universe if s.code in ("AAA", "BBB")]

        def generate_signals(self, candidates, date):
            # Day 1: BUY AAA (small).
            if not self._opened:
                self._opened = True
                self._open_date = date
                aaa = next(s for s in candidates if s.code == "AAA")
                return [
                    Signal(
                        id="sig-aaa-init",
                        strategy_id="rotate",
                        stock_code="AAA",
                        market=aaa.market,
                        direction=SignalDirection.BUY,
                        position_size_pct=0.3,
                        confidence=1.0,
                        reason_code="INIT",
                        generated_at=_dt.combine(date, _dt.min.time()),
                    )
                ]
            # Day 5: BUY BBB (this signal + EXIT below run same day)
            if (
                self._open_date is not None
                and (date - self._open_date).days >= 5
                and not self._rotated
            ):
                self._rotated = True
                bbb = next(s for s in candidates if s.code == "BBB")
                return [
                    Signal(
                        id="sig-bbb",
                        strategy_id="rotate",
                        stock_code="BBB",
                        market=bbb.market,
                        direction=SignalDirection.BUY,
                        position_size_pct=0.5,
                        confidence=1.0,
                        reason_code="ROTATE",
                        generated_at=_dt.combine(date, _dt.min.time()),
                    )
                ]
            return []

        def exit_rules(self, position, date):
            # On rotation day, EXIT AAA at the same time we BUY BBB.
            if (
                self._open_date is not None
                and (date - self._open_date).days >= 5
                and position.stock_code == "AAA"
            ):
                return ExitDecision(action=ExitAction.EXIT, reason_code="ROTATE")
            return ExitDecision(action=ExitAction.HOLD, reason_code="HOLD")

        def get_score(self, stock: Stock, date):
            return 1.0

    bars = _bars()
    strategy = HoldThenRotateStrategy()
    engine = BacktestEngine(
        strategy=strategy,
        account=_account(Decimal("100000")),
        universe=_universe(),
        historical_data=bars,
        cost_model=US_DEFAULT_COST,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )
    result = engine.run()
    # Find rotation day trades — should have a SELL of AAA and a BUY of BBB,
    # both on the same date, with SELL executing first (in trade order).
    same_day_groups: dict = {}
    for t in result.trades:
        same_day_groups.setdefault(t.executed_at.date(), []).append(t)
    rotation_day = next(
        d
        for d, ts in same_day_groups.items()
        if any(t.direction == SignalDirection.SELL for t in ts)
        and any(t.direction == SignalDirection.BUY for t in ts)
    )
    rotation_trades = same_day_groups[rotation_day]
    sell_idx = next(i for i, t in enumerate(rotation_trades) if t.direction == SignalDirection.SELL)
    buy_idx = next(i for i, t in enumerate(rotation_trades) if t.direction == SignalDirection.BUY)
    assert sell_idx < buy_idx
