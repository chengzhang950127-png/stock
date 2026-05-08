"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-08 00:00:00.000000

Hand-written initial migration covering every ORM model declared in
``src/db/models.py`` at Phase 0. Subsequent migrations should be generated
with ``alembic revision --autogenerate``.

Postgres vs SQLite enum handling
--------------------------------
Postgres needs ``CREATE TYPE foo AS ENUM (...)`` before any table can
reference the type. SQLite has no native enum — ``sa.Enum`` falls back to
``VARCHAR + CHECK`` there. So the upgrade does dialect-aware creation:

1. On Postgres, emit ``CREATE TYPE`` once per enum at the top of upgrade().
2. Column-level ``sa.Enum(..., create_type=False)`` references the type
   without re-emitting ``CREATE TYPE`` (which would fail with
   ``DuplicateObject`` on Postgres).
3. On SQLite, the explicit creation is skipped; ``create_type=False`` is
   harmless because there is no native type to create.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Single source of truth for enum values. Used both for explicit CREATE TYPE
# on Postgres and for column references via _enum() below.
ENUMS: list[tuple[str, tuple[str, ...]]] = [
    ("market", ("US", "HK")),
    ("strategytype", ("BUILT_IN", "CUSTOM")),
    ("strategystatus", ("ACTIVE", "ARCHIVED", "DELETED")),
    ("accounttype", ("SHADOW", "LIVE")),
    ("signaldirection", ("BUY", "SELL", "HOLD")),
    (
        "regimelabel",
        (
            "EARNINGS_DRIVEN",
            "LIQUIDITY_DRIVEN",
            "POLICY_DRIVEN",
            "RISK_OFF",
            "TRANSITIONING",
        ),
    ),
]
_ENUM_VALUES: dict[str, tuple[str, ...]] = dict(ENUMS)


def _enum(name: str) -> sa.Enum:
    """Reference an enum by name without (re)creating it."""
    return sa.Enum(*_ENUM_VALUES[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Pre-create types so subsequent op.create_table() calls can reference
        # them without re-emitting CREATE TYPE.
        for name, values in ENUMS:
            sa.Enum(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "stocks",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("market", _enum("market"), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("industry", sa.String(128)),
        sa.Column("market_cap", sa.Numeric(20, 6)),
        sa.Column("listed_date", sa.Date()),
    )

    op.create_table(
        "price_bars",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False, index=True),
        sa.Column("market", _enum("market"), nullable=False),
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
        sa.Column("type", _enum("strategytype"), nullable=False),
        sa.Column("status", _enum("strategystatus"), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime()),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", _enum("accounttype"), nullable=False),
        sa.Column(
            "strategy_id",
            sa.String(36),
            sa.ForeignKey("strategies.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("cash", sa.Numeric(20, 6), nullable=False),
        sa.Column("initial_capital", sa.Numeric(20, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("stock_code", sa.String(32), nullable=False),
        sa.Column("market", _enum("market"), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("avg_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "account_id", "stock_code", "market", name="uq_position_account_stock"
        ),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("stock_code", sa.String(32), nullable=False, index=True),
        sa.Column("market", _enum("market"), nullable=False),
        sa.Column("direction", _enum("signaldirection"), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=False),
        sa.Column("fee", sa.Numeric(20, 6), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("signal_id", sa.String(36), index=True),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.String(36),
            sa.ForeignKey("strategies.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("stock_code", sa.String(32), nullable=False, index=True),
        sa.Column("market", _enum("market"), nullable=False),
        sa.Column("direction", _enum("signaldirection"), nullable=False),
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
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id"),
            nullable=False,
            index=True,
        ),
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
        sa.Column("regime_label", _enum("regimelabel"), nullable=False),
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
    if bind.dialect.name == "postgresql":
        for name, values in reversed(ENUMS):
            sa.Enum(*values, name=name).drop(bind, checkfirst=True)
