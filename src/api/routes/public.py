"""Public (unauthenticated) routes — populated by WP-4.1."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"pong": "ok"}
