"""Tests for the LLM Gateway abstract + Mock implementation."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from src.llm import audit
from src.llm.gateway import LLMGateway
from src.llm.mock import MockLLMGateway, register_fixture


class _SampleSchema(BaseModel):
    """Tiny schema used to exercise default-instance synthesis."""

    name: str = ""
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[str] = []


class _ConstrainedSchema(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)


@pytest.fixture(autouse=True)
def _clear_audit():
    audit.clear()
    yield
    audit.clear()


async def test_mock_returns_default_instance_when_no_fixture():
    gateway = MockLLMGateway()
    out = await gateway.complete("hello", _SampleSchema)
    assert isinstance(out, _SampleSchema)
    assert out.name == ""
    assert out.score == 0.0


async def test_mock_uses_registered_fixture():
    gateway = MockLLMGateway()
    fixture = _SampleSchema(name="fixture", score=0.8, tags=["a", "b"])
    register_fixture(_SampleSchema, fixture)
    try:
        out = await gateway.complete("hello", _SampleSchema)
        assert out == fixture
    finally:
        from src.llm.mock import FIXTURES

        FIXTURES.pop(_SampleSchema, None)


async def test_mock_records_audit_call():
    gateway = MockLLMGateway()
    await gateway.complete("audit test", _SampleSchema)
    records = audit.get_recent_calls()
    assert len(records) == 1
    assert records[0].provider == "mock"
    assert records[0].response_schema == "_SampleSchema"


async def test_mock_rejects_undated_model_id():
    gateway = MockLLMGateway()
    with pytest.raises(ValueError, match="dated suffix"):
        await gateway.complete("x", _SampleSchema, model="claude-3-5-sonnet")


async def test_mock_accepts_dated_model_id():
    gateway = MockLLMGateway()
    out = await gateway.complete(
        "x",
        _SampleSchema,
        model="claude-3-5-sonnet-20241022",
    )
    assert isinstance(out, _SampleSchema)


def test_gateway_validate_model_id_static():
    LLMGateway._validate_model_id("claude-3-5-sonnet-20241022")
    LLMGateway._validate_model_id("gpt-4o-2024-08-06")
    with pytest.raises(ValueError):
        LLMGateway._validate_model_id("claude-latest")
    with pytest.raises(ValueError):
        LLMGateway._validate_model_id("")
