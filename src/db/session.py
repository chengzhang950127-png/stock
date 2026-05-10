"""
SQLAlchemy session / engine factory.

Phase 0 keeps the API simple — sync engine + session. Async support can be
added when the API needs it; the choice is intentionally deferred.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

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


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-manager session for non-FastAPI callers (CLIs, scripts).

    Commits stay caller-controlled; this helper only guarantees the session
    is closed on exit. Use this from synchronous scripts where ``with`` is
    cleaner than the dependency-style ``get_session`` generator.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
