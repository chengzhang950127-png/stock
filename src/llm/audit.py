"""
Audit hooks for LLM calls.

Phase 0 implements an in-memory ring-buffered recorder so tests can inspect
the last N calls. A persistent backend (DB table) lands in WP-1.x along with
the rest of the data layer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AuditRecord:
    timestamp: datetime
    provider: str
    model: str
    temperature: float
    max_tokens: int
    response_schema: str
    prompt_preview: str  # truncated for log hygiene
    extra: dict[str, str] = field(default_factory=dict)


# Bounded ring buffer to avoid unbounded memory growth.
_RING_SIZE = 1000
_records: deque[AuditRecord] = deque(maxlen=_RING_SIZE)


def record_call(
    *,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    prompt: str,
    response_schema: str,
    **extra: str,
) -> AuditRecord:
    """Append an audit record. Returns the record for inspection."""
    record = AuditRecord(
        timestamp=datetime.now(tz=UTC),
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_schema=response_schema,
        prompt_preview=prompt[:200],
        extra=dict(extra),
    )
    _records.append(record)
    logger.debug(
        "llm_call",
        provider=provider,
        model=model,
        schema=response_schema,
        temperature=temperature,
    )
    return record


def get_recent_calls(limit: int | None = None) -> list[AuditRecord]:
    """Return up to ``limit`` most recent records (oldest first)."""
    items = list(_records)
    if limit is not None:
        items = items[-limit:]
    return items


def clear() -> None:
    """Reset the audit buffer. Intended for tests."""
    _records.clear()
