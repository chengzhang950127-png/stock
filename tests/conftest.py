"""Shared pytest fixtures and config."""

from __future__ import annotations

import os

# Ensure tests use the mock LLM and a known APP_ENV before imports that read
# settings at module-import time.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
# Use SQLite in-memory by default so the contract / smoke tests don't need
# Postgres. Tests that exercise the real schema can override via fixture.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest

from src.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
