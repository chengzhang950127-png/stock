"""
Contract center — every cross-module data structure lives here.

All Work Packages depend on these models. Before introducing a new model,
check whether an existing one (or a small extension) already covers it.

Conventions
-----------
* Pydantic v2 syntax. ``model_config`` is declarative.
* Money / quantity fields use ``Decimal`` to avoid float drift.
* Dates use ``datetime.date``; instants use timezone-naive ``datetime``
  representing UTC. Persist instants in DB as ``TIMESTAMPTZ``.
* Enums are subclasses of ``str, Enum`` so they serialize as strings.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# ====================================================================
# Enums
# ====================================================================


class Market(str, Enum):
    US = "US"
    HK = "HK"


class Currency(str, Enum):
    """ISO 4217 三字母代码。V1.x 港股 A 股扩展时再加 CNY。"""

    USD = "USD"
    HKD = "HKD"


class StrategyType(str, Enum):
    BUILT_IN = "BUILT_IN"
    CUSTOM = "CUSTOM"


class StrategyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class AccountType(str, Enum):
    SHADOW = "SHADOW"  # virtual / paper account
    LIVE = "LIVE"  # may be paper or real, but represents user-managed capital


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class ExitAction(str, Enum):
    HOLD = "HOLD"  # keep the position
    REDUCE = "REDUCE"  # partial close
    EXIT = "EXIT"  # full close


class RegimeLabel(str, Enum):
    EARNINGS_DRIVEN = "EARNINGS_DRIVEN"
    LIQUIDITY_DRIVEN = "LIQUIDITY_DRIVEN"
    POLICY_DRIVEN = "POLICY_DRIVEN"
    RISK_OFF = "RISK_OFF"
    TRANSITIONING = "TRANSITIONING"


# ====================================================================
# Market → currency mapping
# ====================================================================


_MARKET_CURRENCY: dict[Market, Currency] = {
    Market.US: Currency.USD,
    Market.HK: Currency.HKD,
}


def currency_for_market(market: Market) -> Currency:
    """Map a market to its native trading currency.

    This is the single source of truth — no business code may inline
    ``if market == Market.US: return Currency.USD`` style branching.
    """
    return _MARKET_CURRENCY[market]


# ====================================================================
# Reference data
# ====================================================================


class Stock(BaseModel):
    """A tradeable instrument identifier + static descriptive fields."""

    model_config = ConfigDict(frozen=True)

    code: str  # e.g. "AAPL", "0700.HK"
    market: Market
    currency: Currency
    name: str
    industry: str | None = None
    market_cap: Decimal | None = None
    listed_date: date | None = None


class PriceBar(BaseModel):
    """A single OHLCV bar (daily granularity by default)."""

    code: str
    market: Market
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal  # split- and dividend-adjusted close
    volume: int


# ====================================================================
# Strategy
# ====================================================================


class StrategyParameters(BaseModel):
    """
    Container for strategy-specific parameters.

    Concrete strategy classes can subclass this with strongly-typed fields.
    The ``extra="allow"`` policy lets us round-trip unknown keys through JSONB
    without losing data, which is useful when an older strategy version is
    loaded by newer code (forward compatibility).
    """

    model_config = ConfigDict(extra="allow")


class CustomBlendParameters(StrategyParameters):
    """Parameters for the user-defined four-factor blended strategy (V0.5+)."""

    w_value: float = Field(ge=0.0, le=1.0)
    w_momentum: float = Field(ge=0.0, le=1.0)
    w_event: float = Field(ge=0.0, le=1.0)
    w_index: float = Field(ge=0.0, le=1.0)

    def model_post_init(self, __context: object) -> None:
        total = self.w_value + self.w_momentum + self.w_event + self.w_index
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


class Strategy(BaseModel):
    """
    Strategy metadata persisted in the DB.

    The ``parameters`` field is the typed container. At the ORM boundary it
    is serialized to JSONB; business code should always pass and accept
    ``StrategyParameters`` (or subclasses), never raw dicts.
    """

    id: str  # UUID v4
    name: str
    type: StrategyType
    status: StrategyStatus
    parameters: StrategyParameters
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ExitDecision(BaseModel):
    """A strategy's verdict for an existing position on a given day."""

    action: ExitAction
    reason_code: str  # e.g. "STOP_LOSS_HIT", "TAKE_PROFIT_HIT", "REGIME_SHIFT"
    target_quantity: Decimal | None = None  # required iff action == REDUCE


# ====================================================================
# Accounts, positions, trades
# ====================================================================


class Account(BaseModel):
    id: str
    type: AccountType
    strategy_id: str
    currency: Currency
    cash: Decimal
    initial_capital: Decimal
    created_at: datetime


class Position(BaseModel):
    """An open holding. ``quantity`` is Decimal to allow fractional shares."""

    account_id: str
    stock_code: str
    market: Market
    currency: Currency
    quantity: Decimal
    avg_cost: Decimal
    opened_at: datetime


class Trade(BaseModel):
    """An executed (or simulated) order fill."""

    id: str
    account_id: str
    stock_code: str
    market: Market
    currency: Currency
    direction: SignalDirection
    quantity: Decimal
    price: Decimal
    fee: Decimal
    executed_at: datetime
    signal_id: str | None = None


# ====================================================================
# Signals
# ====================================================================


class Signal(BaseModel):
    """A strategy's intent to buy / sell on a given day."""

    id: str
    strategy_id: str
    stock_code: str
    market: Market
    direction: SignalDirection
    buy_range: tuple[Decimal, Decimal] | None = None  # (low, high)
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    position_size_pct: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: str  # quantitative trigger code
    reason_narrative: str | None = None  # human-readable, may be LLM-generated (V0.6+)
    generated_at: datetime


# ====================================================================
# Performance
# ====================================================================


class PerformanceSnapshot(BaseModel):
    """Daily snapshot of an account's performance state."""

    account_id: str
    date: date
    nav: Decimal
    cash: Decimal
    positions_value: Decimal
    daily_return: float
    cumulative_return: float
    drawdown: float


class PerformanceMetrics(BaseModel):
    """Aggregate metrics computed over a window."""

    total_return: float
    annual_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    win_rate: float
    avg_holding_days: float


# ====================================================================
# Investment assistant
# ====================================================================


class Regime(BaseModel):
    """The market regime classification for a given day."""

    date: date
    primary_label: RegimeLabel
    probabilities: dict[RegimeLabel, float]
    confidence: float
    drivers: list[str]


class AssetAllocation(BaseModel):
    """Three-tier asset allocation recommendation."""

    date: date
    total_equity_pct: float = Field(ge=0.0, le=1.0)  # cash vs equity
    market_weights: dict[Market, float]  # US vs HK
    strategy_weights: dict[str, dict[str, float]]  # market -> strategy_name -> weight


class AssistantAdvice(BaseModel):
    """A single dated piece of advice from the investment assistant."""

    id: str
    date: date
    regime: Regime
    allocation: AssetAllocation
    narrative: str | None = None  # populated only from V0.6+
    risk_alerts: list[str]
    generated_at: datetime
    # Post-hoc verification (filled by the verifier job, not at generation time)
    verified_at: datetime | None = None
    verification_score: float | None = None


# ====================================================================
# Archive
# ====================================================================


class PerformanceArchive(BaseModel):
    """Final performance snapshot stored when a strategy is archived."""

    strategy_id: str
    strategy_name: str
    archive_date: date
    metrics: PerformanceMetrics
    full_history: list[PerformanceSnapshot]


# ====================================================================
# Public re-exports
# ====================================================================

__all__ = [
    # enums
    "Market",
    "Currency",
    "StrategyType",
    "StrategyStatus",
    "AccountType",
    "SignalDirection",
    "ExitAction",
    "RegimeLabel",
    # helpers
    "currency_for_market",
    # reference data
    "Stock",
    "PriceBar",
    # strategy
    "StrategyParameters",
    "CustomBlendParameters",
    "Strategy",
    "ExitDecision",
    # accounts / positions / trades
    "Account",
    "Position",
    "Trade",
    # signals
    "Signal",
    # performance
    "PerformanceSnapshot",
    "PerformanceMetrics",
    # assistant
    "Regime",
    "AssetAllocation",
    "AssistantAdvice",
    # archive
    "PerformanceArchive",
]
