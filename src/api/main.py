"""FastAPI application entrypoint.

Phase 0 ships only ``/health``. Real routes are registered by WP-4.x.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import public
from src.config import get_settings
from src.utils.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger(__name__)
    settings = get_settings()
    logger.info("api.startup", env=settings.APP_ENV, llm_provider=settings.LLM_PROVIDER)
    yield
    logger.info("api.shutdown")


app = FastAPI(
    title="Quant System API",
    version="0.0.1",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().APP_ENV}


app.include_router(public.router, prefix="/api/public", tags=["public"])
