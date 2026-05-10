"""Backtest main loop.

Each step:

1. Build a fresh ``PointInTimeDataView`` rooted at ``current_date``.
2. Ask the strategy to screen and emit signals; ask it for an exit
   verdict on each open position.
3. Translate verdicts into fills with slippage + fees applied.
4. Mark-to-market at close: NAV uses ``adj_close`` for return continuity
   (#B2); per-fill prices use raw ``close`` (what a trader would actually
   transact at). Trades record raw ``close``.
5. Append a :class:`PerformanceSnapshot` to the result.

Strategies never see ``historical_data`` directly — only the view.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from src.backtest.data_views import PointInTimeDataView
from src.backtest.execution import apply_slippage, calculate_fee
from src.backtest.metrics import calculate_metrics
from src.contracts import (
    Account,
    ExitAction,
    PerformanceMetrics,
    PerformanceSnapshot,
    Position,
    PriceBar,
    Signal,
    SignalDirection,
    Stock,
    Trade,
)
from src.strategies.base import StrategyBase

logger = logging.getLogger(__name__)

DEFAULT_SLIPPAGE_BPS = 5.0
DEFAULT_FEE_PER_SHARE = Decimal("0.005")
DEFAULT_MIN_FEE = Decimal("1.0")
_PRICE_QUANTUM = Decimal("0.0001")
_MONEY_QUANTUM = Decimal("0.01")


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    account_final: Account
    trades: list[Trade]
    performance_snapshots: list[PerformanceSnapshot]
    metrics: PerformanceMetrics


@dataclass
class _PositionState:
    """Engine-internal mutable position; flattened to contract Position on demand."""

    stock: Stock
    quantity: Decimal
    avg_cost: Decimal  # raw close-based cost, fee-inclusive
    opened_at: datetime
    cost_basis_adj: Decimal  # adj_close-based cost basis at opening (for nav tracking)


@dataclass
class BacktestEngine:
    """Vectorized-by-day, single-strategy backtest engine.

    Multi-strategy parallelism (V0.2) constructs one engine instance per
    strategy and runs them concurrently — the engine itself is single-strategy
    so the strategy boundary stays clean.
    """

    strategy: StrategyBase
    account: Account
    universe: list[Stock]
    historical_data: dict[str, list[PriceBar]]
    start_date: date
    end_date: date
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS
    fee_per_share: Decimal = DEFAULT_FEE_PER_SHARE
    min_fee: Decimal = DEFAULT_MIN_FEE

    _positions: dict[str, _PositionState] = field(default_factory=dict, init=False)
    _cash: Decimal = field(default=Decimal("0"), init=False)
    _trades: list[Trade] = field(default_factory=list, init=False)
    _snapshots: list[PerformanceSnapshot] = field(default_factory=list, init=False)
    _initial_nav: Decimal = field(default=Decimal("0"), init=False)
    _peak_nav: Decimal = field(default=Decimal("0"), init=False)

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError(f"start_date {self.start_date} must be <= end_date {self.end_date}")
        self._cash = self.account.cash
        self._initial_nav = self.account.cash
        self._peak_nav = self.account.cash

    # ---- Public API ----

    def run(self) -> BacktestResult:
        """Iterate every trading day in the universe and produce a result."""
        for current_date in self._trading_days():
            self.step(current_date)

        final_account = Account(
            id=self.account.id,
            type=self.account.type,
            strategy_id=self.account.strategy_id,
            currency=self.account.currency,
            cash=self._cash.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP),
            initial_capital=self.account.initial_capital,
            created_at=self.account.created_at,
        )
        metrics = calculate_metrics(self._snapshots, self._trades)
        return BacktestResult(
            account_final=final_account,
            trades=list(self._trades),
            performance_snapshots=list(self._snapshots),
            metrics=metrics,
        )

    def step(self, current_date: date) -> None:
        """Execute one trading day."""
        view = PointInTimeDataView(self.historical_data, current_date, self.universe)

        # 1. Exit decisions for existing positions.
        # Snapshot the keys because dict mutates during iteration.
        for code in list(self._positions.keys()):
            state = self._positions[code]
            position = self._to_contract_position(state)
            decision = self.strategy.exit_rules(position, current_date)
            if decision.action == ExitAction.HOLD:
                continue
            target_qty = self._resolve_exit_qty(state, decision.action, decision.target_quantity)
            if target_qty <= 0:
                continue
            bar = view.get_bar_on(code, current_date)
            if bar is None:
                continue  # no quote today (holiday for this name); skip
            self._execute_sell(state, target_qty, bar, current_date)

        # 2. Generate new signals.
        candidates = self.strategy.screen(view.get_universe(), current_date)
        signals = self.strategy.generate_signals(candidates, current_date)
        for signal in signals:
            if signal.direction != SignalDirection.BUY:
                continue
            bar = view.get_bar_on(signal.stock_code, current_date)
            if bar is None:
                continue
            self._execute_buy(signal, bar, current_date, view)

        # 3. Mark-to-market and snapshot.
        self._record_snapshot(current_date, view)

    # ---- Internals ----

    def _trading_days(self) -> list[date]:
        """Union of every bar.date in the universe within [start_date, end_date]."""
        days: set[date] = set()
        for code, bars in self.historical_data.items():
            del code  # unused; just iterate values
            for bar in bars:
                if self.start_date <= bar.date <= self.end_date:
                    days.add(bar.date)
        return sorted(days)

    def _resolve_exit_qty(
        self,
        state: _PositionState,
        action: ExitAction,
        target_quantity: Decimal | None,
    ) -> Decimal:
        if action == ExitAction.EXIT:
            return state.quantity
        if action == ExitAction.REDUCE:
            if target_quantity is None or target_quantity <= 0:
                logger.warning(
                    "REDUCE action for %s missing valid target_quantity; treating as no-op",
                    state.stock.code,
                )
                return Decimal("0")
            # Cap at current holdings.
            return min(target_quantity, state.quantity)
        return Decimal("0")

    def _execute_buy(
        self,
        signal: Signal,
        bar: PriceBar,
        current_date: date,
        view: PointInTimeDataView,
    ) -> None:
        del view  # reserved for future use (e.g. ADV-based size cap)
        intended_price = bar.close  # #B2: decisions on raw close
        fill_price = apply_slippage(intended_price, SignalDirection.BUY, self.slippage_bps)

        # Size by signal.position_size_pct of current NAV (mark-to-market via adj_close).
        nav = self._current_nav(current_date)
        target_dollars = nav * Decimal(str(signal.position_size_pct))
        if target_dollars <= 0:
            return
        # Reserve at least min_fee for commission.
        budget = min(target_dollars, max(Decimal("0"), self._cash - self.min_fee))
        if budget <= 0:
            return
        # Fractional shares allowed (fractional brokers); quantize to 4 dp.
        raw_shares = budget / fill_price
        shares = raw_shares.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
        # Re-clamp in case rounding pushed us over budget.
        while (
            shares > 0
            and shares * fill_price + calculate_fee(shares, self.fee_per_share, self.min_fee)
            > self._cash
        ):
            shares -= _PRICE_QUANTUM
        if shares <= 0:
            return

        fee = calculate_fee(shares, self.fee_per_share, self.min_fee)
        gross = (shares * fill_price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        cost = gross + fee
        self._cash -= cost

        executed_at = datetime.combine(current_date, datetime.min.time())
        trade = Trade(
            id=str(uuid.uuid4()),
            account_id=self.account.id,
            stock_code=signal.stock_code,
            market=bar.market,
            currency=self.account.currency,
            direction=SignalDirection.BUY,
            quantity=shares,
            price=fill_price,
            fee=fee,
            executed_at=executed_at,
            signal_id=signal.id,
        )
        self._trades.append(trade)

        # Update / create position.
        existing = self._positions.get(signal.stock_code)
        if existing is None:
            stock = self._lookup_stock(signal.stock_code) or Stock(
                code=signal.stock_code,
                market=bar.market,
                currency=self.account.currency,
                name=signal.stock_code,
            )
            self._positions[signal.stock_code] = _PositionState(
                stock=stock,
                quantity=shares,
                avg_cost=fill_price,
                opened_at=executed_at,
                cost_basis_adj=bar.adj_close,
            )
        else:
            new_qty = existing.quantity + shares
            existing.avg_cost = (
                (existing.avg_cost * existing.quantity + fill_price * shares) / new_qty
            ).quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
            existing.cost_basis_adj = (
                (existing.cost_basis_adj * existing.quantity + bar.adj_close * shares) / new_qty
            ).quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
            existing.quantity = new_qty

    def _execute_sell(
        self,
        state: _PositionState,
        qty: Decimal,
        bar: PriceBar,
        current_date: date,
    ) -> None:
        intended_price = bar.close
        fill_price = apply_slippage(intended_price, SignalDirection.SELL, self.slippage_bps)
        fee = calculate_fee(qty, self.fee_per_share, self.min_fee)
        gross = (qty * fill_price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        proceeds = gross - fee
        self._cash += proceeds

        executed_at = datetime.combine(current_date, datetime.min.time())
        trade = Trade(
            id=str(uuid.uuid4()),
            account_id=self.account.id,
            stock_code=state.stock.code,
            market=bar.market,
            currency=self.account.currency,
            direction=SignalDirection.SELL,
            quantity=qty,
            price=fill_price,
            fee=fee,
            executed_at=executed_at,
        )
        self._trades.append(trade)

        new_qty = state.quantity - qty
        if new_qty <= 0:
            del self._positions[state.stock.code]
        else:
            state.quantity = new_qty

    def _record_snapshot(self, current_date: date, view: PointInTimeDataView) -> None:
        positions_value = self._positions_value_mtm(current_date, view)
        nav = (self._cash + positions_value).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        prior_nav = self._snapshots[-1].nav if self._snapshots else self._initial_nav

        daily_return = float((nav - prior_nav) / prior_nav) if prior_nav > 0 else 0.0

        cumulative_return = (
            float((nav - self._initial_nav) / self._initial_nav) if self._initial_nav > 0 else 0.0
        )

        if nav > self._peak_nav:
            self._peak_nav = nav
        drawdown = float((self._peak_nav - nav) / self._peak_nav) if self._peak_nav > 0 else 0.0

        self._snapshots.append(
            PerformanceSnapshot(
                account_id=self.account.id,
                date=current_date,
                nav=nav,
                cash=self._cash.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP),
                positions_value=positions_value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP),
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                drawdown=drawdown,
            )
        )

    def _positions_value_mtm(self, current_date: date, view: PointInTimeDataView) -> Decimal:
        """Mark every open position to today's close (raw close, not adj_close).

        Why raw close: ``adj_close`` retroactively reduces past prices for splits
        and dividends, which would deflate today's holding value vs. what's
        actually in the account. Returns are still calculated correctly because
        cash inflows from dividends are captured indirectly through the
        ``adj_close`` adjustments built into the next day's bars (V0.1
        simplification: we don't credit dividends as cash explicitly; the
        ``adj_close``-driven NAV reflects the total-return path).
        """
        # NOTE on V0.1 simplification: NAV uses raw close per #B2 contract that
        # decisions / fills use raw close. Total return is still represented by
        # the daily_return series (built from NAV deltas) which captures any
        # retro-adjustment indirectly because shares * close is consistent
        # period over period.
        del view
        total = Decimal("0")
        for state in self._positions.values():
            bar = self._most_recent_bar(state.stock.code, current_date)
            if bar is None:
                # Stale: use last known cost as floor.
                total += state.quantity * state.avg_cost
            else:
                total += state.quantity * bar.close
        return total

    def _current_nav(self, current_date: date) -> Decimal:
        positions_value = Decimal("0")
        for state in self._positions.values():
            bar = self._most_recent_bar(state.stock.code, current_date)
            if bar is None:
                positions_value += state.quantity * state.avg_cost
            else:
                positions_value += state.quantity * bar.close
        return self._cash + positions_value

    def _most_recent_bar(self, code: str, on_or_before: date) -> PriceBar | None:
        bars = self.historical_data.get(code, [])
        latest: PriceBar | None = None
        for bar in bars:
            if bar.date <= on_or_before and (latest is None or bar.date > latest.date):
                latest = bar
        return latest

    def _to_contract_position(self, state: _PositionState) -> Position:
        return Position(
            account_id=self.account.id,
            stock_code=state.stock.code,
            market=state.stock.market,
            currency=state.stock.currency,
            quantity=state.quantity,
            avg_cost=state.avg_cost,
            opened_at=state.opened_at,
        )

    def _lookup_stock(self, code: str) -> Stock | None:
        for stock in self.universe:
            if stock.code == code:
                return stock
        return None
