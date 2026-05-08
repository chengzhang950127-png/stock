"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-08 00:00:00.000000

Hand-written initial migration covering every ORM model declared in
``src/db/models.py`` at Phase 0. Subsequent migrations should be generated
with ``alembic revision --autogenerate``.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum names — Postgres needs them registered explicitly.
MARKET = sa.Enum("US", "HK", name="market")
STRATEGY_TYPE = sa.Enum("BUILT_IN", "CUSTOM", name="strategytype")
STRATEGY_STATUS = sa.Enum("ACTIVE", "ARCHIVED", "DELETED", name="strategystatus")
ACCOUNT_TYPE = sa.Enum("SHADOW", "LIVE", name="accounttype")
SIGNAL_DIRECTION = sa.Enum("BUY", "SELL", "HOLD", name="signaldirection")
REGIME_LABEL = sa.Enum(
    "EARNINGS_DRIVEN",
    "LIQUIDITY_DRIVEN",
    "POLICY_DRIVEN",
    "RISK_OFF",
    "TRANSITIONING",
    name="regimelabel",
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (MARKET, STRATEGY_TYPE, STRATEGY_STATUS, ACCOUNT_TYPE, SIGNAL_DIRECTION, REGIME_LABEL):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "stocks",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("market", MARKET, primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("industry", sa.String(128)),
        sa.Column("market_cap", sa.Numeric(20, 6)),
        sa.Column("listed_date", sa.Date()),
    )

    op.create_table(
        "price_bars",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False, index=True),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("open", sa.Numeric(20, 6), nullable=False),
        sa.Column("high", sa.Numeric(20, 6), nullable=False),
        sa.Column("low", sa.Numeric(20, 6), nullable=False),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("adj_close", sa.Numeric(20, 6), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("code", "market", "date", name="uq_price_bar_code_market_date"),
    )

    op.create_table(
        "strategies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("type", STRATEGY_TYPE, nullable=False),
        sa.Column("status", STRATEGY_STATUS, nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime()),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", ACCOUNT_TYPE, nullable=False),
        sa.Column("strategy_id", sa.String(36), sa.ForeignKey("strategies.id"), nullable=False, index=True),
        sa.Column("cash", sa.Numeric(20, 6), nullable=False),
        sa.Column("initial_capital", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("stock_code", sa.String(32), nullable=False),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("account_id", "stock_code", "market", name="uq_position_account_stock"),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("stock_code", sa.String(32), nullable=False, index=True),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("direction", SIGNAL_DIRECTION, nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.Column("fee", sa.Numeric(20, 6), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("signal_id", sa.String(36), index=True),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy_id", sa.String(36), sa.ForeignKey("strategies.id"), nullable=False, index=True),
        sa.Column("stock_code", sa.String(32), nullable=False, index=True),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("direction", SIGNAL_DIRECTION, nullable=False),
        sa.Column("buy_low", sa.Numeric(20, 6)),
        sa.Column("buy_high", sa.Numeric(20, 6)),
        sa.Column("stop_loss", sa.Numeric(20, 6)),
        sa.Column("take_profit", sa.Numeric(20, 6)),
        sa.Column("position_size_pct", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("reason_narrative", sa.Text()),
        sa.Column("generated_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "performance_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("cash", sa.Numeric(20, 6), nullable=False),
        sa.Column("positions_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=False),
        sa.Column("cumulative_return", sa.Float(), nullable=False),
        sa.Column("drawdown", sa.Float(), nullable=False),
        sa.UniqueConstraint("account_id", "date", name="uq_perf_account_date"),
    )

    op.create_table(
        "assistant_advice",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False, unique=True, index=True),
        sa.Column("regime_label", REGIME_LABEL, nullable=False),
        sa.Column("regime_payload", sa.JSON(), nullable=False),
        sa.Column("allocation_payload", sa.JSON(), nullable=False),
        sa.Column("narrative", sa.Text()),
        sa.Column("risk_alerts", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("verification_score", sa.Float()),
    )

    op.create_table(
        "performance_archives",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(36), nullable=False, index=True),
        sa.Column("strategy_name", sa.String(128), nullable=False),
        sa.Column("archive_date", sa.Date(), nullable=False),
        sa.Column("metrics_payload", sa.JSON(), nullable=False),
        sa.Column("full_history_payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("performance_archives")
    op.drop_table("assistant_advice")
    op.drop_table("performance_snapshots")
    op.drop_table("signals")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("accounts")
    op.drop_table("strategies")
    op.drop_table("price_bars")
    op.drop_table("stocks")

    bind = op.get_bind()
    for enum in (REGIME_LABEL, SIGNAL_DIRECTION, ACCOUNT_TYPE, STRATEGY_STATUS, STRATEGY_TYPE, MARKET):
        enum.drop(bind, checkfirst=True)
