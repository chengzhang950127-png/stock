"""
SQLAlchemy session / engine factory.

Phase 0 keeps the API simple — sync engine + session. Async support can be
added when the API needs it; the choice is intentionally deferred.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model. Imported by Alembic env.py."""


_settings = get_settings()

engine = create_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency-style generator yielding a session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
