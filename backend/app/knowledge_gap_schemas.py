import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GapItem(BaseModel):
    project_id: uuid.UUID
    project_name: str
    question_key: str
    question: str
    query_count: int
    flagged_count: int
    not_helpful_count: int
    weak_evidence_count: int
    helpful_count: int
    unmeasured_count: int
    first_seen: datetime
    last_seen: datetime
    status: Literal["open", "resolved"]
    reopened: bool
    revision: int
    note: str | None
    resolved_at: datetime | None
    updated_at: datetime | None
    evidence_version: str


class GapEvidence(BaseModel):
    id: str
    question: str
    created_at: datetime
    feedback_rating: str | None
    feedback_note: str | None
    retrieval_similarity: float | None
    cache_layer: str | None
    not_helpful: bool
    weak_evidence: bool


class GapReport(BaseModel):
    generated_at: datetime
    window_days: int
    scanned_queries: int
    scan_limit: int
    limited: bool
    weak_similarity_threshold: float
    open_groups: int
    resolved_groups: int
    flagged_queries: int
    matched_groups: int
    items: list[GapItem]
    next_offset: int | None


class GapDetail(BaseModel):
    item: GapItem
    window_days: int
    limited: bool
    scanned_queries: int
    scan_limit: int
    weak_similarity_threshold: float
    evidence: list[GapEvidence]
    evidence_total: int
    next_offset: int | None


class GapReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "resolved"]
    note: str = Field(default="", max_length=2000)
    revision: int = Field(ge=0, le=2_147_483_646)
    evidence_version: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Notes cannot contain null characters")
        return value.strip()
