"""LLM Gateway — single entry point for any LLM call (see INVARIANT #2)."""

from src.llm.gateway import (
    LLMGateway,
    LLMServiceError,
    LLMValidationError,
)
from src.llm.mock import MockLLMGateway

__all__ = [
    "LLMGateway",
    "LLMServiceError",
    "LLMValidationError",
    "MockLLMGateway",
    "get_gateway",
]


def get_gateway() -> LLMGateway:
    """Return the configured Gateway implementation.

    For V0.1-V0.5 this is always the Mock. From V0.6+ a real LiteLLM-backed
    gateway is wired up here based on ``settings.LLM_PROVIDER``.
    """
    from src.config import get_settings

    settings = get_settings()
    provider = settings.LLM_PROVIDER

    if provider == "mock":
        return MockLLMGateway()

    # Real providers are not implemented in Phase 0 — fall back loudly so we
    # never silently dispatch to an unintended backend.
    raise NotImplementedError(
        f"LLM provider {provider!r} is not wired up yet. "
        "Set LLM_PROVIDER=mock for now or implement the real adapter "
        "in src/llm/ before V0.6."
    )
