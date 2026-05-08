"""
Centralized logging configuration based on structlog.

Call :func:`configure_logging` once at process startup (FastAPI lifespan, CLI
entrypoints, scheduled jobs). Subsequent calls are no-ops.
"""

from __future__ import annotations

import logging
import sys

import structlog

from src.config import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.APP_ENV == "development":
        processors.append(structlog.dev.ConsoleRenderer(colors=False))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _configured:
        configure_logging()
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return logger  # type: ignore[no-any-return]
