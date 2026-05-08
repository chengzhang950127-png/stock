"""
SQLAlchemy ORM models.

These are the persistence representations that mirror the Pydantic contracts
in :mod:`src.contracts`. Conversions between ORM and Pydantic happen at the
service boundary — the rest of the codebase consumes Pydantic models.

Phase 0 declares only the tables that downstream WPs are guaranteed to need.
Additional tables (audit logs, scheduler state, etc.) are added when the
owning WP lands.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.contracts import (
    AccountType,
    Market,
    RegimeLabel,
    SignalDirection,
    StrategyStatus,
    StrategyType,
)
from src.db.session import Base


# Convenience: reusable money column
def money_col(**kwargs):
    return mapped_column(Numeric(20, 6), **kwargs)


# ---- Reference data ----


class StockORM(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    market: Mapped[Market] = mapped_column(SQLEnum(Market), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128))
    market_cap: Mapped[Decimal | None] = money_col()
    listed_date: Mapped[date | None] = mapped_column(Date)


class PriceBarORM(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("code", "market", "date", name="uq_price_bar_code_market_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market: Mapped[Market] = mapped_column(SQLEnum(Market), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Decimal] = money_col(nullable=False)
    high: Mapped[Decimal] = money_col(nullable=False)
    low: Mapped[Decimal] = money_col(nullable=False)
    close: Mapped[Decimal] = money_col(nullable=False)
    adj_close: Mapped[Decimal] = money_col(nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)


# ---- Strategy ----


class StrategyORM(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    type: Mapped[StrategyType] = mapped_column(SQLEnum(StrategyType), nullable=False)
    status: Mapped[StrategyStatus] = mapped_column(
        SQLEnum(StrategyStatus), nullable=False, default=StrategyStatus.ACTIVE
    )
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    accounts: Mapped[list[AccountORM]] = relationship(back_populates="strategy")


# ---- Account / Position / Trade ----


class AccountORM(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[AccountType] = mapped_column(SQLEnum(AccountType), nullable=False)
    strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("strategies.id"), nullable=False, index=True
    )
    cash: Mapped[Decimal] = money_col(nullable=False)
    initial_capital: Mapped[Decimal] = money_col(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    strategy: Mapped[StrategyORM] = relationship(back_populates="accounts")
    positions: Mapped[list[PositionORM]] = relationship(back_populates="account")
    trades: Mapped[list[TradeORM]] = relationship(back_populates="account")


class PositionORM(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "stock_code", "market", name="uq_position_account_stock"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False, index=True
    )
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[Market] = mapped_column(SQLEnum(Market), nullable=False)
    quantity: Mapped[Decimal] = money_col(nullable=False)
    avg_cost: Mapped[Decimal] = money_col(nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    account: Mapped[AccountORM] = relationship(back_populates="positions")


class TradeORM(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False, index=True
    )
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market: Mapped[Market] = mapped_column(SQLEnum(Market), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(SQLEnum(SignalDirection), nullable=False)
    quantity: Mapped[Decimal] = money_col(nullable=False)
    price: Mapped[Decimal] = money_col(nullable=False)
    fee: Mapped[Decimal] = money_col(nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36), index=True)

    account: Mapped[AccountORM] = relationship(back_populates="trades")


# ---- Signal ----


class SignalORM(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("strategies.id"), nullable=False, index=True
    )
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    market: Mapped[Market] = mapped_column(SQLEnum(Market), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(SQLEnum(SignalDirection), nullable=False)
    buy_low: Mapped[Decimal | None] = money_col()
    buy_high: Mapped[Decimal | None] = money_col()
    stop_loss: Mapped[Decimal | None] = money_col()
    take_profit: Mapped[Decimal | None] = money_col()
    position_size_pct: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_narrative: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


# ---- Performance ----


class PerformanceSnapshotORM(Base):
    __tablename__ = "performance_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "date", name="uq_perf_account_date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nav: Mapped[Decimal] = money_col(nullable=False)
    cash: Mapped[Decimal] = money_col(nullable=False)
    positions_value: Mapped[Decimal] = money_col(nullable=False)
    daily_return: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_return: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)


# ---- Investment assistant ----


class AssistantAdviceORM(Base):
    __tablename__ = "assistant_advice"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    regime_label: Mapped[RegimeLabel] = mapped_column(SQLEnum(RegimeLabel), nullable=False)
    regime_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    allocation_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text)
    risk_alerts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_score: Mapped[float | None] = mapped_column(Float)


# ---- Archive ----


class PerformanceArchiveORM(Base):
    __tablename__ = "performance_archives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    archive_date: Mapped[date] = mapped_column(Date, nullable=False)
    metrics_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    full_history_payload: Mapped[list[dict]] = mapped_column(JSON, nullable=False)


__all__ = [
    "AccountORM",
    "AssistantAdviceORM",
    "PerformanceArchiveORM",
    "PerformanceSnapshotORM",
    "PositionORM",
    "PriceBarORM",
    "SignalORM",
    "StockORM",
    "StrategyORM",
    "TradeORM",
]
