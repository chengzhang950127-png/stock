"""
Cross-business LLM input / output schemas.

Only schemas that are used in two or more business modules belong here.
Strategy- or feature-specific schemas (e.g. event-driven news parsing inputs)
should live next to their owning module.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

# -----------------------------------------------------------------
# Event-driven strategy: news parsing (consumer = WP-2.4 + WP-2.5)
# -----------------------------------------------------------------


class NewsItemInput(BaseModel):
    """A raw news item handed to the LLM for structured parsing."""

    headline: str
    body: str
    source: str
    published_at: date


class NewsParseOutput(BaseModel):
    """Structured fields extracted from a news item.

    Phase 0 defines only the must-have fields. WP-2.5 may extend.
    """

    is_material: bool = Field(description="Does this news plausibly move the price?")
    sentiment: float = Field(ge=-1.0, le=1.0)
    affected_tickers: list[str] = Field(default_factory=list)
    event_type: str = Field(description="e.g. 'earnings_beat', 'm_and_a', 'guidance_cut'")
    summary: str = Field(max_length=500)


# -----------------------------------------------------------------
# Investment assistant: narrative generation (consumer = WP-3.4)
# -----------------------------------------------------------------


class AssistantNarrativeInput(BaseModel):
    """Pre-computed quantitative inputs handed to the LLM for prose generation."""

    date: date
    regime_label: str
    regime_drivers: list[str]
    allocation_summary: dict[str, float]  # high-level summary, not the full nested map
    key_metrics: dict[str, float]


class AssistantNarrativeOutput(BaseModel):
    """The prose section that gets attached to ``AssistantAdvice.narrative``."""

    narrative: str = Field(max_length=2000)
    key_takeaways: list[str] = Field(default_factory=list, max_length=5)


__all__ = [
    "AssistantNarrativeInput",
    "AssistantNarrativeOutput",
    "NewsItemInput",
    "NewsParseOutput",
]
