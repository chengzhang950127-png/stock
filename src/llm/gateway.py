"""
LLM Gateway — single point of entry for every LLM call in the system.

Why this exists
---------------
INVARIANT #2: business code MUST NOT import ``openai`` / ``anthropic`` /
``litellm`` directly. Going through this Gateway gives us:

1. Pinned model versions with dated suffixes (INVARIANT #4).
2. Forced ``temperature=0.0`` for determinism (INVARIANT #5).
3. Mandatory Pydantic schema validation on every output (INVARIANT #3).
4. Auditable call logs.
5. Fail-loud behavior — never silently fall back to free-text.

Subclasses must implement :meth:`LLMGateway.complete`. Concrete
implementations (Mock for V0.1-V0.5, LiteLLM-backed for V0.6+) live alongside
this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when an LLM response cannot be parsed into ``response_schema``."""


class LLMServiceError(Exception):
    """Raised when the underlying LLM service call fails (network, 5xx, etc.)."""


class LLMGateway(ABC):
    """Abstract LLM Gateway.

    All call sites pass ``response_schema`` — there is no free-text variant
    on purpose; structured output is mandatory across the codebase.
    """

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> T:
        """Invoke the LLM and return a validated instance of ``response_schema``.

        Parameters
        ----------
        prompt:
            Fully-rendered prompt text.
        response_schema:
            Pydantic model class. The implementation MUST validate the LLM's
            output against this schema before returning. Validation failures
            raise :class:`LLMValidationError`.
        model:
            Dated model id, e.g. ``claude-3-5-sonnet-20241022``. Aliases such
            as ``claude-3-5-sonnet`` (no date) are forbidden — implementations
            should reject them at runtime.
        temperature:
            Defaults to 0.0. Non-zero values require an explicit, documented
            exception.
        max_tokens:
            Output token cap.

        Raises
        ------
        LLMValidationError
            Output failed schema validation.
        LLMServiceError
            Underlying provider call failed.
        ValueError
            Caller passed a forbidden model alias or invalid arguments.
        """
        ...

    @staticmethod
    def _validate_model_id(model: str) -> None:
        """Reject model ids that look like ``latest`` aliases.

        We require a ``-YYYYMMDD`` suffix (or a colon-versioned tag like
        ``gpt-4o-2024-08-06``). The exact regex is loose — the goal is to
        catch obvious mistakes (``claude-3-5-sonnet`` with no date), not to
        validate every possible legitimate id.
        """
        import re

        if not model:
            raise ValueError("model id must be non-empty")
        # Accept anything containing an 8-digit date or a 4-2-2 dated suffix.
        if not re.search(r"\d{8}|\d{4}-\d{2}-\d{2}", model):
            raise ValueError(
                f"model id {model!r} is missing a dated suffix; "
                "use e.g. 'claude-3-5-sonnet-20241022' (see INVARIANT #4)"
            )
