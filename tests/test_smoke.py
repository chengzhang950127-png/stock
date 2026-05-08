"""Smoke tests — API boots, DB engine resolves."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "env" in body


def test_public_ping_endpoint():
    with TestClient(app) as client:
        resp = client.get("/api/public/ping")
    assert resp.status_code == 200
    assert resp.json() == {"pong": "ok"}


def test_db_engine_creates_without_error():
    # Import lazily so that the in-memory SQLite URL set by conftest applies.
    from src.db.session import engine

    assert engine is not None
    assert "://" in str(engine.url)


def test_strategy_base_is_abstract():
    from src.strategies.base import StrategyBase

    assert getattr(StrategyBase, "__abstractmethods__", set()) >= {
        "screen",
        "generate_signals",
        "exit_rules",
        "get_score",
    }
