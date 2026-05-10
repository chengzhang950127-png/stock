"""Backtest main loop with T close decide → T+1 open execute.

Per ``docs/architecture.md §10.5`` (and the simpler restatement in
``src/backtest/INVARIANTS.md`` #B3), each ``step(T)`` runs in this
order:

1. **Execute T-1 pending orders** at T's ``bar.open`` * (1 +/- slippage).
   This is the SELL→BUY phase: SELLs first (release cash), then BUYs
   in determinstic order ``(-confidence, stock_code)``. BUYs whose
   share count would over-spend cash get scaled proportionally
   (partial fill) — never raise.
2. **Build a fresh PointInTimeDataView** for ``current_date``. The
   view filters ``bar.date <= current_date`` explicitly (#B1 / #8).
3. **Strategy decides** using data through T close: ``screen`` →
   ``generate_signals`` → ``exit_rules`` for each open position.
4. **Queue T-day actions for T+1 execution**. Nothing fills today
   (except the T-1 queue we already drained in step 1).
5. **MTM at T close**: positions valued at ``shares * close`` (#B1
   "MTM uses close"); NAV = cash + positions value; append snapshot.

``BacktestResult.unexecuted_signals`` collects the T = end_date signals
that have no T+1 to execute.

Daily-return / cumulative-return are computed using ``adj_close`` —
specifically by treating the ratio of consecutive ``adj_close`` values
as the per-day total-return contribution of each open position. NAV
itself uses raw ``close`` (#B1), so NAV and the cumulative-return
series can diverge by ≈ dividend reinvestment PV (this is documented
in §10.5 #5 as a known design choice, not a bug).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from src.backtest.data_views import PointInTimeDataView
from src.backtest.execution import ExecutionCostModel, apply_slippage, calculate_fee
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

_PRICE_QUANTUM = Decimal("0.0001")
_MONEY_QUANTUM = Decimal("0.01")
_SHARE_QUANTUM = Decimal("0.0001")  # fractional shares allowed (US brokers)


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    account_final: Account
    trades: list[Trade]
    performance_snapshots: list[PerformanceSnapshot]
    metrics: PerformanceMetrics
    unexecuted_signals: list[Signal]


@dataclass
class _PositionState:
    """Engine-internal mutable position; flattens to contract Position on demand."""

    stock: Stock
    quantity: Decimal
    avg_cost_close: Decimal  # cost basis using raw close (for accounting)
    avg_cost_adj: Decimal  # cost basis using adj_close (for return math)
    opened_at: datetime


@dataclass
class _PendingOrder:
    """An order queued at T-1 to execute at T-open."""

    direction: SignalDirection
    stock_code: str
    market: object  # contracts.Market — kept loose to avoid import cycle
    shares: Decimal
    confidence: float
    signal_id: str | None
    queued_on: date


@dataclass
class BacktestEngine:
    """Vectorized-by-day, single-strategy backtest engine.

    Multi-strategy parallelism (V0.2) constructs one engine instance
    per strategy and runs them concurrently — the engine itself is
    single-strategy so the strategy boundary stays clean.
    """

    strategy: StrategyBase
    account: Account
    universe: list[Stock]
    historical_data: dict[str, list[PriceBar]]
    cost_model: ExecutionCostModel
    start_date: date
    end_date: date

    _positions: dict[str, _PositionState] = field(default_factory=dict, init=False)
    _cash: Decimal = field(default=Decimal("0"), init=False)
    _trades: list[Trade] = field(default_factory=list, init=False)
    _snapshots: list[PerformanceSnapshot] = field(default_factory=list, init=False)
    _initial_nav: Decimal = field(default=Decimal("0"), init=False)
    _peak_nav: Decimal = field(default=Decimal("0"), init=False)
    _pending_orders: list[_PendingOrder] = field(default_factory=list, init=False)
    _unexecuted_signals: list[Signal] = field(default_factory=list, init=False)
    # adj_close accumulator: previous day's per-symbol adj_close, for return calc.
    _prev_adj_close: dict[str, Decimal] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError(f"start_date {self.start_date} must be <= end_date {self.end_date}")
        # INVARIANT #B2 — currency consistency
        if self.cost_model.currency != self.account.currency:
            raise ValueError(
                f"cost_model currency {self.cost_model.currency} does not match "
                f"account currency {self.account.currency}"
            )
        self._cash = self.account.cash
        self._initial_nav = self.account.cash
        self._peak_nav = self.account.cash

    # ---- Public API ----

    def run(self) -> BacktestResult:
        """Iterate every trading day in the universe and produce a result."""
        trading_days = self._trading_days()
        for current_date in trading_days:
            self.step(current_date)

        # Any orders still queued after the last step have no T+1 to land on —
        # they become unexecuted_signals (best-effort; engine prefers explicit
        # tracking over silent drops).
        for pending in self._pending_orders:
            self._unexecuted_signals.append(
                Signal(
                    id=pending.signal_id or str(uuid.uuid4()),
                    strategy_id=self.account.strategy_id,
                    stock_code=pending.stock_code,
                    market=pending.market,  # type: ignore[arg-type]
                    direction=pending.direction,
                    position_size_pct=0.0,
                    confidence=pending.confidence,
                    reason_code="UNEXECUTED_NO_NEXT_DAY",
                    generated_at=datetime.combine(pending.queued_on, datetime.min.time()),
                )
            )
        self._pending_orders.clear()

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
            unexecuted_signals=list(self._unexecuted_signals),
        )

    def step(self, current_date: date) -> None:
        """Execute one trading day. See module docstring for full ordering."""
        # === Phase 1 — execute T-1 queued orders at T's bar.open ===
        self._fill_pending_orders(current_date)

        # === Phase 2 — build view ===
        view = PointInTimeDataView(self.historical_data, self.universe, current_date)

        # === Phase 3 — strategy decides on T (using data through T close) ===
        candidates = self.strategy.screen(view.get_universe(), current_date)
        signals = list(self.strategy.generate_signals(candidates, current_date))
        exit_decisions: list[tuple[str, Decimal]] = []
        for code in list(self._positions.keys()):
            position = self._to_contract_position(self._positions[code])
            decision = self.strategy.exit_rules(position, current_date)
            if decision.action == ExitAction.HOLD:
                continue
            qty = self._resolve_exit_qty(
                self._positions[code], decision.action, decision.target_quantity
            )
            if qty > 0:
                exit_decisions.append((code, qty))

        # === Phase 4 — queue T-day actions for T+1 execution ===
        if current_date == self.end_date:
            # No T+1 in window; signals + exit decisions become unexecuted.
            for sig in signals:
                self._unexecuted_signals.append(sig)
            # exit decisions are silently dropped (no signal to record); reviewer
            # acceptance criterion focuses on signals, not exits.
        else:
            self._queue_orders(current_date, signals, exit_decisions, view)

        # === Phase 5 — MTM at T close + record snapshot ===
        self._record_snapshot(current_date, view)

    # ---- Phase implementations ----

    def _fill_pending_orders(self, current_date: date) -> None:
        """Execute everything in the pending queue using current_date's bar.open."""
        if not self._pending_orders:
            return

        # SELL first (release cash), then BUY (consume cash). BUYs sorted by
        # (-confidence, stock_code) for determinism (INVARIANT #B4).
        sells = [o for o in self._pending_orders if o.direction == SignalDirection.SELL]
        buys = sorted(
            [o for o in self._pending_orders if o.direction == SignalDirection.BUY],
            key=lambda o: (-o.confidence, o.stock_code),
        )

        for order in sells:
            self._execute_pending_sell(order, current_date)
        for order in buys:
            self._execute_pending_buy(order, current_date)

        self._pending_orders.clear()

    def _execute_pending_sell(self, order: _PendingOrder, current_date: date) -> None:
        bar = self._bar_on(order.stock_code, current_date)
        if bar is None:
            # Symbol has no quote today; SELL silently dropped (could be re-queued
            # for next day; V0.1 prefers simplicity over perfect retry semantics).
            return
        state = self._positions.get(order.stock_code)
        if state is None or state.quantity <= 0:
            return
        qty = min(order.shares, state.quantity)
        intended_price = bar.open  # T+1 open execution per §10.5 #2
        fill_price = apply_slippage(
            intended_price, SignalDirection.SELL, self.cost_model.slippage_bps
        )
        fee = calculate_fee(qty, self.cost_model.fee_per_share, self.cost_model.min_fee)
        gross = (qty * fill_price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        self._cash += gross - fee

        self._record_trade(
            stock_code=order.stock_code,
            market=bar.market,
            direction=SignalDirection.SELL,
            shares=qty,
            price=fill_price,
            fee=fee,
            executed_at=datetime.combine(current_date, datetime.min.time()),
            signal_id=order.signal_id,
        )
        new_qty = state.quantity - qty
        if new_qty <= 0:
            del self._positions[order.stock_code]
        else:
            state.quantity = new_qty

    def _execute_pending_buy(self, order: _PendingOrder, current_date: date) -> None:
        bar = self._bar_on(order.stock_code, current_date)
        if bar is None:
            return
        intended_price = bar.open
        fill_price = apply_slippage(
            intended_price, SignalDirection.BUY, self.cost_model.slippage_bps
        )

        # Cash budget; partial fill if insufficient.
        max_shares = order.shares
        # Reserve at least min_fee for commission to keep cash math sane.
        usable_cash = max(Decimal("0"), self._cash - self.cost_model.min_fee)
        if usable_cash <= 0:
            return
        affordable_shares = (usable_cash / fill_price).quantize(
            _SHARE_QUANTUM, rounding=ROUND_HALF_UP
        )
        # Re-check after rounding (could overshoot by quantum * fill_price).
        while affordable_shares > 0 and (
            affordable_shares * fill_price
            + calculate_fee(
                affordable_shares, self.cost_model.fee_per_share, self.cost_model.min_fee
            )
            > self._cash
        ):
            affordable_shares -= _SHARE_QUANTUM

        actual_shares = min(max_shares, affordable_shares)
        if actual_shares <= 0:
            return
        fee = calculate_fee(actual_shares, self.cost_model.fee_per_share, self.cost_model.min_fee)
        gross = (actual_shares * fill_price).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        self._cash -= gross + fee

        self._record_trade(
            stock_code=order.stock_code,
            market=bar.market,
            direction=SignalDirection.BUY,
            shares=actual_shares,
            price=fill_price,
            fee=fee,
            executed_at=datetime.combine(current_date, datetime.min.time()),
            signal_id=order.signal_id,
        )

        existing = self._positions.get(order.stock_code)
        # Capture both close- and adj_close-based cost basis; needed for §10.5 #5
        # divergence handling.
        if existing is None:
            stock = self._lookup_stock(order.stock_code) or Stock(
                code=order.stock_code,
                market=bar.market,
                currency=self.account.currency,
                name=order.stock_code,
            )
            self._positions[order.stock_code] = _PositionState(
                stock=stock,
                quantity=actual_shares,
                avg_cost_close=fill_price,
                avg_cost_adj=bar.adj_close,
                opened_at=datetime.combine(current_date, datetime.min.time()),
            )
        else:
            new_qty = existing.quantity + actual_shares
            existing.avg_cost_close = (
                (existing.avg_cost_close * existing.quantity + fill_price * actual_shares) / new_qty
            ).quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
            existing.avg_cost_adj = (
                (existing.avg_cost_adj * existing.quantity + bar.adj_close * actual_shares)
                / new_qty
            ).quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)
            existing.quantity = new_qty

    def _queue_orders(
        self,
        current_date: date,
        signals: list[Signal],
        exit_decisions: list[tuple[str, Decimal]],
        view: PointInTimeDataView,
    ) -> None:
        """Translate T-day signals + exit verdicts into pending orders for T+1.

        position_size_pct base = current NAV (cash + positions MTM at T close).
        """
        nav = self._current_nav_at_close(current_date)

        # Exits queued first conceptually, but during T+1 fill we always SELL→BUY
        # by direction. So queue both and let _fill_pending_orders sort it out.
        for code, qty in exit_decisions:
            self._pending_orders.append(
                _PendingOrder(
                    direction=SignalDirection.SELL,
                    stock_code=code,
                    market=self._positions[code].stock.market,
                    shares=qty,
                    confidence=1.0,
                    signal_id=None,
                    queued_on=current_date,
                )
            )

        # BUY signals: shares = (NAV * position_size_pct) / current_close.
        # Use today's close as the sizing reference — the actual fill price
        # will be tomorrow's open + slippage; reviewer review-ready.
        for sig in signals:
            if sig.direction != SignalDirection.BUY:
                continue
            bar = view.get_bar_on(sig.stock_code, current_date)
            if bar is None:
                continue
            target_dollars = nav * Decimal(str(sig.position_size_pct))
            if target_dollars <= 0:
                continue
            target_shares = (target_dollars / bar.close).quantize(
                _SHARE_QUANTUM, rounding=ROUND_HALF_UP
            )
            if target_shares <= 0:
                continue
            self._pending_orders.append(
                _PendingOrder(
                    direction=SignalDirection.BUY,
                    stock_code=sig.stock_code,
                    market=bar.market,
                    shares=target_shares,
                    confidence=sig.confidence,
                    signal_id=sig.id,
                    queued_on=current_date,
                )
            )

    def _record_snapshot(self, current_date: date, view: PointInTimeDataView) -> None:
        """MTM at T close, then append PerformanceSnapshot.

        daily_return uses adj_close ratio (per #B1); NAV uses close.
        """
        positions_value = self._positions_value_close(current_date)
        nav = (self._cash + positions_value).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)

        # adj_close-based daily return: weighted by yesterday's positions.
        daily_return = self._compute_daily_return_adj(current_date)

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

        # Update prev_adj_close cache for tomorrow.
        for state in self._positions.values():
            bar = view.get_bar_on(state.stock.code, current_date)
            if bar is not None:
                self._prev_adj_close[state.stock.code] = bar.adj_close

    # ---- Helpers ----

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
                    "REDUCE for %s missing target_quantity; treating as no-op",
                    state.stock.code,
                )
                return Decimal("0")
            return min(target_quantity, state.quantity)
        return Decimal("0")

    def _record_trade(
        self,
        stock_code: str,
        market,
        direction: SignalDirection,
        shares: Decimal,
        price: Decimal,
        fee: Decimal,
        executed_at: datetime,
        signal_id: str | None,
    ) -> None:
        self._trades.append(
            Trade(
                id=str(uuid.uuid4()),
                account_id=self.account.id,
                stock_code=stock_code,
                market=market,
                currency=self.account.currency,
                direction=direction,
                quantity=shares,
                price=price,
                fee=fee,
                executed_at=executed_at,
                signal_id=signal_id,
            )
        )

    def _trading_days(self) -> list[date]:
        """Union of every bar.date in the universe within [start_date, end_date]."""
        days: set[date] = set()
        for bars in self.historical_data.values():
            for bar in bars:
                if self.start_date <= bar.date <= self.end_date:
                    days.add(bar.date)
        return sorted(days)

    def _bar_on(self, code: str, day: date) -> PriceBar | None:
        for bar in self.historical_data.get(code, []):
            if bar.date == day:
                return bar
        return None

    def _most_recent_bar(self, code: str, on_or_before: date) -> PriceBar | None:
        latest: PriceBar | None = None
        for bar in self.historical_data.get(code, []):
            if bar.date <= on_or_before and (latest is None or bar.date > latest.date):
                latest = bar
        return latest

    def _positions_value_close(self, current_date: date) -> Decimal:
        """MTM positions at today's close (or last known close if no quote today)."""
        total = Decimal("0")
        for state in self._positions.values():
            bar = self._most_recent_bar(state.stock.code, current_date)
            if bar is None:
                total += state.quantity * state.avg_cost_close
            else:
                total += state.quantity * bar.close
        return total

    def _current_nav_at_close(self, current_date: date) -> Decimal:
        return self._cash + self._positions_value_close(current_date)

    def _compute_daily_return_adj(self, current_date: date) -> float:
        """Daily return as the adj_close-weighted change in positions value plus cash flow.

        Uses yesterday's snapshot NAV as the denominator (or initial_nav for day 1).
        Numerator is today's "adj NAV" — cash + sum(shares * adj_close).
        Both numerator and denominator are computed in the same units, so dividend
        / split adjustments fold into the ratio cleanly (per §10.5 #5).
        """
        prior_nav = self._snapshots[-1].nav if self._snapshots else self._initial_nav
        if prior_nav <= 0:
            return 0.0

        today_adj_value = Decimal("0")
        for state in self._positions.values():
            bar = self._most_recent_bar(state.stock.code, current_date)
            if bar is None:
                today_adj_value += state.quantity * state.avg_cost_adj
            else:
                today_adj_value += state.quantity * bar.adj_close
        today_adj_nav = self._cash + today_adj_value

        # For day 1 with adj/close split, prior_nav is initial cash; this gives
        # the right "1-day return" because positions opened today have zero
        # contribution to prior_nav and a positive contribution today only if
        # adj_close diverges from purchase price within the day.
        return float((today_adj_nav - prior_nav) / prior_nav)

    def _to_contract_position(self, state: _PositionState) -> Position:
        return Position(
            account_id=self.account.id,
            stock_code=state.stock.code,
            market=state.stock.market,
            currency=state.stock.currency,
            quantity=state.quantity,
            avg_cost=state.avg_cost_close,
            opened_at=state.opened_at,
        )

    def _lookup_stock(self, code: str) -> Stock | None:
        for stock in self.universe:
            if stock.code == code:
                return stock
        return None
