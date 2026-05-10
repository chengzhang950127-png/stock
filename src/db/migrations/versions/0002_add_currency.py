"""add currency

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09 00:00:00.000000

Adds a NOT NULL ``currency`` column (ISO 4217, three-letter) to the four
money-bearing tables introduced in 0001: ``stocks``, ``accounts``,
``positions``, ``trades``. Phase 0.5 promotes currency from a comment on
``Stock.market_cap`` to a first-class field; this is the schema landing.

Three-step pattern (ADD → UPDATE → SET NOT NULL)
------------------------------------------------
We deliberately avoid ``op.add_column(..., server_default=...)`` followed by
a separate "drop the default" call. ``server_default`` semantics differ
subtly between SQLite and Postgres (and between Postgres major versions on
how the default is materialized), and "set then unset" leaves an audit
question of whether old rows were touched.

Instead we:

1. ADD the column as nullable (no default).
2. Backfill via raw ``UPDATE`` derived from the existing ``market`` column —
   the single source of truth for what currency belongs to what market.
   On an empty Phase 0 DB this is a no-op; on real data it is the actual
   migration step.
3. ALTER COLUMN ... SET NOT NULL once every row has a value.
4. Add a CHECK constraint pinning ``currency`` to the V0.x value set.

This is verbose but unambiguous and replays cleanly on both dialects.

SQLite quirk
------------
SQLite does not support ``ALTER COLUMN ... SET NOT NULL`` directly. Alembic's
``batch_alter_table`` issues a copy-and-rename that we lean on here so the
same migration works against both backends.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables that have a `market` column we can backfill currency from.
TABLES_WITH_MARKET: list[tuple[str, str]] = [
    ("stocks", "ck_stocks_currency_iso4217"),
    ("positions", "ck_positions_currency_iso4217"),
    ("trades", "ck_trades_currency_iso4217"),
]

# Tables without `market` — currency must come from another source. In Phase
# 0 the schema is empty, so there is nothing to backfill; we just NOT-NULL
# the freshly-added column. If a future migration runs against non-empty
# data, accounts.currency must already be populated by an earlier step or
# this migration will fail at SET NOT NULL — which is the desired loud
# failure mode.
TABLES_WITHOUT_MARKET: list[tuple[str, str]] = [
    ("accounts", "ck_accounts_currency_iso4217"),
]

ALL_TABLES: list[tuple[str, str]] = TABLES_WITH_MARKET + TABLES_WITHOUT_MARKET

# market value -> currency value. Source of truth lives in
# ``src.contracts.currency_for_market``; we mirror it here because Alembic
# migrations must be self-contained (they can't import live application code
# whose semantics may drift in later revisions).
MARKET_TO_CURRENCY: dict[str, str] = {"US": "USD", "HK": "HKD"}

ALLOWED_CURRENCIES: tuple[str, ...] = ("USD", "HKD")


def _backfill_sql() -> str:
    """Build a CASE expression that maps ``market`` to its native currency."""
    cases = " ".join(
        f"WHEN market = '{m}' THEN '{c}'" for m, c in MARKET_TO_CURRENCY.items()
    )
    return f"CASE {cases} END"


def upgrade() -> None:
    backfill = _backfill_sql()

    # Step 1: add nullable column on every table.
    for table, _ in ALL_TABLES:
        op.add_column(table, sa.Column("currency", sa.String(3), nullable=True))

    # Step 2a: backfill currency from market on the tables that have one.
    for table, _ in TABLES_WITH_MARKET:
        op.execute(f"UPDATE {table} SET currency = {backfill}")

    # Step 2b: tables without a market column require currency to be
    # populated by the application layer or by a separate data migration.
    # Phase 0 is empty so the SET NOT NULL below holds trivially; assert
    # this loudly to fail any future replay against non-empty data.
    for table, _ in TABLES_WITHOUT_MARKET:
        result = op.get_bind().execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE currency IS NULL")
        ).scalar()
        if result and result > 0:
            raise RuntimeError(
                f"{table!r} has {result} rows without currency. "
                f"Backfill them via a data migration before re-running 0002."
            )

    # Step 3: tighten to NOT NULL and add CHECK on every table. SQLite needs
    # batch mode for the NOT NULL flip; CHECK syntax is dialect-portable.
    allowed = ", ".join(f"'{v}'" for v in ALLOWED_CURRENCIES)
    for table, ck_name in ALL_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("currency", existing_type=sa.String(3), nullable=False)
            batch.create_check_constraint(ck_name, f"currency IN ({allowed})")


def downgrade() -> None:
    # Reverse order: drop CHECK, drop column.
    for table, ck_name in ALL_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(ck_name, type_="check")
            batch.drop_column("currency")
