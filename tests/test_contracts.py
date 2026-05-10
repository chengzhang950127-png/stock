"""Round-trip serialization tests for every Pydantic contract."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.contracts import (
    Account,
    AccountType,
    AssetAllocation,
    AssistantAdvice,
    Currency,
    CustomBlendParameters,
    ExitAction,
    ExitDecision,
    Market,
    PerformanceArchive,
    PerformanceMetrics,
    PerformanceSnapshot,
    Position,
    PriceBar,
    Regime,
    RegimeLabel,
    Signal,
    SignalDirection,
    Stock,
    Strategy,
    StrategyParameters,
    StrategyStatus,
    StrategyType,
    Trade,
    currency_for_market,
)


def _round_trip(model):
    cls = type(model)
    return cls.model_validate_json(model.model_dump_json())


# ---- Reference data ----


def test_stock_round_trip():
    s = Stock(code="AAPL", market=Market.US, currency=Currency.USD, name="Apple Inc.")
    assert _round_trip(s) == s


def test_price_bar_round_trip():
    bar = PriceBar(
        code="AAPL",
        market=Market.US,
        date=date(2026, 1, 2),
        open=Decimal("180.0"),
        high=Decimal("182.5"),
        low=Decimal("179.0"),
        close=Decimal("181.7"),
        adj_close=Decimal("181.7"),
        volume=12_345_678,
    )
    assert _round_trip(bar) == bar


# ---- Strategy ----


def test_custom_blend_parameters_round_trip():
    params = CustomBlendParameters(w_value=0.25, w_momentum=0.25, w_event=0.25, w_index=0.25)
    assert _round_trip(params) == params


def test_custom_blend_parameters_reject_unbalanced_weights():
    with pytest.raises(ValueError, match="Weights must sum"):
        CustomBlendParameters(w_value=0.5, w_momentum=0.1, w_event=0.1, w_index=0.1)


def test_strategy_round_trip():
    now = datetime(2026, 5, 8, 12, 0, 0)
    s = Strategy(
        id="11111111-1111-1111-1111-111111111111",
        name="value-reversal",
        type=StrategyType.BUILT_IN,
        status=StrategyStatus.ACTIVE,
        parameters=StrategyParameters(),
        created_at=now,
        updated_at=now,
    )
    assert _round_trip(s) == s


def test_exit_decision_round_trip():
    e = ExitDecision(action=ExitAction.EXIT, reason_code="STOP_LOSS_HIT")
    assert _round_trip(e) == e


# ---- Accounts / Positions / Trades ----


def test_account_round_trip():
    a = Account(
        id="11111111-1111-1111-1111-111111111111",
        type=AccountType.SHADOW,
        strategy_id="22222222-2222-2222-2222-222222222222",
        currency=Currency.USD,
        cash=Decimal("100000.00"),
        initial_capital=Decimal("100000.00"),
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert _round_trip(a) == a


def test_position_round_trip():
    p = Position(
        account_id="11111111-1111-1111-1111-111111111111",
        stock_code="AAPL",
        market=Market.US,
        currency=Currency.USD,
        quantity=Decimal("10.5"),
        avg_cost=Decimal("180.00"),
        opened_at=datetime(2026, 1, 5, 9, 30, 0),
    )
    assert _round_trip(p) == p


def test_trade_round_trip():
    t = Trade(
        id="33333333-3333-3333-3333-333333333333",
        account_id="11111111-1111-1111-1111-111111111111",
        stock_code="AAPL",
        market=Market.US,
        currency=Currency.USD,
        direction=SignalDirection.BUY,
        quantity=Decimal("10"),
        price=Decimal("180.50"),
        fee=Decimal("1.00"),
        executed_at=datetime(2026, 1, 5, 9, 30, 0),
    )
    assert _round_trip(t) == t


# ---- Currency helper ----


def test_currency_for_market_us():
    assert currency_for_market(Market.US) == Currency.USD


def test_currency_for_market_hk():
    assert currency_for_market(Market.HK) == Currency.HKD


def test_currency_enum_values():
    """ISO 4217 three-letter codes; expand this set when V1.x adds CNY."""
    assert {c.value for c in Currency} == {"USD", "HKD"}


# ---- Signals ----


def test_signal_round_trip():
    sig = Signal(
        id="44444444-4444-4444-4444-444444444444",
        strategy_id="22222222-2222-2222-2222-222222222222",
        stock_code="AAPL",
        market=Market.US,
        direction=SignalDirection.BUY,
        buy_range=(Decimal("178.00"), Decimal("182.00")),
        stop_loss=Decimal("172.00"),
        take_profit=Decimal("200.00"),
        position_size_pct=0.05,
        confidence=0.7,
        reason_code="MEAN_REVERSION",
        generated_at=datetime(2026, 5, 8, 9, 0, 0),
    )
    assert _round_trip(sig) == sig


# ---- Performance ----


def test_performance_snapshot_round_trip():
    snap = PerformanceSnapshot(
        account_id="11111111-1111-1111-1111-111111111111",
        date=date(2026, 5, 8),
        nav=Decimal("101000.00"),
        cash=Decimal("50000.00"),
        positions_value=Decimal("51000.00"),
        daily_return=0.005,
        cumulative_return=0.01,
        drawdown=0.0,
    )
    assert _round_trip(snap) == snap


def test_performance_metrics_round_trip():
    m = PerformanceMetrics(
        total_return=0.15,
        total_return_with_dividends=0.17,
        annual_return=0.18,
        annual_return_with_dividends=0.20,
        sharpe=1.4,
        sortino=1.7,
        max_drawdown=0.08,
        calmar=2.25,
        win_rate=0.55,
        avg_holding_days=12.5,
    )
    assert _round_trip(m) == m


def test_performance_metrics_round_trip_with_dividend_fields():
    """PerformanceMetrics serializes both TR fields cleanly (Blocker 2 方案 A).

    Regression test for r1 评审: confirms the contract carries
    ``total_return`` (close-based price return) and
    ``total_return_with_dividends`` (adj_close-based TR) as separate
    fields, plus their respective annualized variants.
    """
    m = PerformanceMetrics(
        total_return=0.802,  # SPY 5y close ratio ~+80%
        total_return_with_dividends=0.965,  # SPY 5y adj_close ratio ~+96.5%
        annual_return=0.125,
        annual_return_with_dividends=0.144,
        sharpe=0.9,
        sortino=1.1,
        max_drawdown=0.34,
        calmar=0.42,
        win_rate=0.0,
        avg_holding_days=0.0,
    )
    rebuilt = _round_trip(m)
    assert rebuilt == m
    # Spot-check both new fields survive serialization.
    assert rebuilt.total_return_with_dividends == 0.965
    assert rebuilt.annual_return_with_dividends == 0.144


# ---- Investment assistant ----


def test_regime_round_trip():
    r = Regime(
        date=date(2026, 5, 8),
        primary_label=RegimeLabel.LIQUIDITY_DRIVEN,
        probabilities={
            RegimeLabel.EARNINGS_DRIVEN: 0.1,
            RegimeLabel.LIQUIDITY_DRIVEN: 0.7,
            RegimeLabel.POLICY_DRIVEN: 0.1,
            RegimeLabel.RISK_OFF: 0.05,
            RegimeLabel.TRANSITIONING: 0.05,
        },
        confidence=0.7,
        drivers=["fed_pivot", "credit_spread_compression"],
    )
    assert _round_trip(r) == r


def test_asset_allocation_round_trip():
    a = AssetAllocation(
        date=date(2026, 5, 8),
        total_equity_pct=0.6,
        market_weights={Market.US: 0.7, Market.HK: 0.3},
        strategy_weights={
            "US": {"value-reversal": 0.5, "trend-momentum": 0.5},
            "HK": {"value-reversal": 1.0},
        },
    )
    assert _round_trip(a) == a


def test_assistant_advice_round_trip():
    advice = AssistantAdvice(
        id="55555555-5555-5555-5555-555555555555",
        date=date(2026, 5, 8),
        regime=Regime(
            date=date(2026, 5, 8),
            primary_label=RegimeLabel.RISK_OFF,
            probabilities={RegimeLabel.RISK_OFF: 1.0},
            confidence=0.9,
            drivers=["vix_spike"],
        ),
        allocation=AssetAllocation(
            date=date(2026, 5, 8),
            total_equity_pct=0.3,
            market_weights={Market.US: 1.0, Market.HK: 0.0},
            strategy_weights={"US": {"index-gtaa": 1.0}, "HK": {}},
        ),
        risk_alerts=["high_vol"],
        generated_at=datetime(2026, 5, 8, 9, 0, 0),
    )
    assert _round_trip(advice) == advice


# ---- Archive ----


def test_performance_archive_round_trip():
    archive = PerformanceArchive(
        strategy_id="22222222-2222-2222-2222-222222222222",
        strategy_name="value-reversal",
        archive_date=date(2026, 5, 8),
        metrics=PerformanceMetrics(
            total_return=0.0,
            total_return_with_dividends=0.0,
            annual_return=0.0,
            annual_return_with_dividends=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            calmar=0.0,
            win_rate=0.0,
            avg_holding_days=0.0,
        ),
        full_history=[],
    )
    assert _round_trip(archive) == archive
