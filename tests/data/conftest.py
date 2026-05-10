"""
Shared fixtures for the data tests.

Why a per-test SQLite engine
----------------------------
The repo-wide ``conftest.py`` points ``DATABASE_URL`` at SQLite in-memory.
But ``src/db/session.py`` builds its engine at import time from the cached
settings, and that engine is shared across the whole process. To get a
clean schema per test, we build a fresh in-memory engine here, create the
tables, and yield a session bound to it. This matches Phase 0 conftest's
"don't depend on Postgres" rule.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import (  # noqa: F401 — register tables on Base.metadata
    AccountORM,
    AssistantAdviceORM,
    PerformanceArchiveORM,
    PerformanceSnapshotORM,
    PositionORM,
    PriceBarORM,
    SignalORM,
    StockORM,
    StrategyORM,
    TradeORM,
)
from src.db.session import Base


def _coerce_bigint_pks_to_integer_for_sqlite(metadata: sa.MetaData) -> None:
    """SQLite auto-increments INTEGER PRIMARY KEY only; BIGINT PK stays NULL.

    Production Postgres keeps BIGINT for headroom; in SQLite-backed unit
    tests we silently downgrade to INTEGER so the rowid alias kicks in.
    This is local to the test fixture — production schema is untouched.
    """
    for table in metadata.tables.values():
        for column in table.columns:
            if column.primary_key and isinstance(column.type, sa.BigInteger):
                column.type = sa.Integer()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A fresh SQLite-backed session with the full schema loaded."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )

    # SQLite needs FK enforcement turned on per-connection.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    _coerce_bigint_pks_to_integer_for_sqlite(Base.metadata)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(  # noqa: N806 — SQLAlchemy convention is PascalCase here
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Per-test cache directory so the @cached decorator never leaks state."""
    return tmp_path / "cache"
