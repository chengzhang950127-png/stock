"""
Mock LLMGateway implementation.

Used for V0.1-V0.5 when no real LLM is wired up. Returns deterministic,
schema-compliant payloads built by best-effort introspection of the
requested ``response_schema``.

Strategy
--------
1. If ``response_schema`` is registered in :data:`FIXTURES`, return a deep
   copy of that pre-built fixture (preferred — gives realistic data).
2. Otherwise, build a default instance by walking the schema's fields and
   filling each with a type-appropriate default. This is enough to keep
   tests passing and downstream code from crashing while still surfacing
   schema mismatches loudly via Pydantic validation.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, TypeVar, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from src.llm.audit import record_call
from src.llm.gateway import LLMGateway, LLMValidationError

T = TypeVar("T", bound=BaseModel)

# Registry of pre-built fixtures keyed by schema class.
# Production code is expected to register its own fixtures from test setup
# rather than hard-coding domain types here (keeps the Mock decoupled from
# the rest of the codebase).
FIXTURES: dict[type[BaseModel], BaseModel] = {}


def register_fixture(schema: type[BaseModel], fixture: BaseModel) -> None:
    """Register a deterministic fixture for ``schema``.

    Tests / boot code can call this to wire realistic mock outputs without
    creating a tight coupling between ``src/llm/mock.py`` and domain modules.
    """
    if not isinstance(fixture, schema):
        raise TypeError(f"fixture {fixture!r} is not an instance of schema {schema.__name__}")
    FIXTURES[schema] = fixture


class MockLLMGateway(LLMGateway):
    """Deterministic, offline LLMGateway. Records every call for inspection."""

    async def complete(
        self,
        prompt: str,
        response_schema: type[T],
        *,
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> T:
        # Enforce gateway-level invariants even in the mock so that
        # violations surface during development.
        self._validate_model_id(model)
        if temperature != 0.0:
            # Mock allows non-zero but logs it for audit; production gateways
            # may choose to reject. INVARIANT #5 is enforced via static scan
            # in ``scripts/verify_invariants.py``.
            pass

        record_call(
            provider="mock",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt=prompt,
            response_schema=response_schema.__name__,
        )

        # Prefer registered fixtures.
        if response_schema in FIXTURES:
            return copy.deepcopy(FIXTURES[response_schema])  # type: ignore[return-value]

        # Otherwise, synthesize a default instance.
        try:
            return _default_instance(response_schema)
        except Exception as exc:
            raise LLMValidationError(
                f"MockLLMGateway could not build a default instance of "
                f"{response_schema.__name__}: {exc}. Register a fixture via "
                f"src.llm.mock.register_fixture."
            ) from exc


# ---------------------------------------------------------------------------
# Default-instance synthesis
# ---------------------------------------------------------------------------


def _default_instance(schema: type[T]) -> T:
    payload: dict[str, Any] = {}
    for field_name, field in schema.model_fields.items():
        payload[field_name] = _default_for_field(field)
    return schema.model_validate(payload)


def _default_for_field(field: FieldInfo) -> Any:
    if field.default is not None and field.default is not Ellipsis:
        return field.default
    if field.default_factory is not None:
        return field.default_factory()  # type: ignore[call-arg]

    annotation = field.annotation
    return _default_for_annotation(annotation)


def _default_for_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] / X | None
    if origin is type(None):
        return None
    if args and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _default_for_annotation(non_none[0])
        return None

    # Containers
    if origin in (list, tuple):
        return []
    if origin is dict:
        return {}

    # Primitives
    if annotation is str:
        return ""
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if annotation is Decimal:
        return Decimal("0")
    if annotation is date:
        return date(2000, 1, 1)
    if annotation is datetime:
        return datetime.now(tz=UTC).replace(tzinfo=None)

    # Enums
    if isinstance(annotation, type) and hasattr(annotation, "__members__"):
        first_member = next(iter(annotation.__members__.values()))
        return first_member

    # Nested Pydantic models
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _default_instance(annotation)

    # Fallback: empty string is usually parseable by Pydantic for many types.
    return ""
