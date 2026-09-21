"""Evidence item models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    id: str
    ticker: str
    claim: str
    source_name: str
    source_url: str | None = None
    source_type: str = "secondary"
    published_at: str | None = None
    retrieved_at: str
    supporting_text: str | None = None
    data_points: dict[str, Any] = Field(default_factory=dict)
    reliability: float = 0.7
    freshness: float = 0.7
    directness: float = 0.7
    corroboration: float = 0.5
    research_run_id: str | None = None
