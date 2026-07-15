from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimType = Literal[
    "directional",
    "level",
    "scenario",
    "risk_warning",
    "macro_context",
    "not_scoreable",
]
Direction = Literal["bullish", "bearish", "neutral", "conditional"]
Scoreability = Literal["scoreable", "conditional_scoreable", "not_scoreable"]
NormalizedHorizonHours = Literal[24, 48]
ReviewRequiredField = Literal[
    "claim_text",
    "claim_type",
    "assets",
    "levels",
    "direction",
    "condition",
    "invalidation_condition",
    "time_horizon",
    "scoreability",
]
ClaimReviewFlag = Literal[
    "ai_semantic_interpretation",
    "instruction_like_source_text",
    "unsupported_time_horizon",
]


class ClaimCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_text: str = Field(min_length=1)
    claim_type: ClaimType
    source_excerpt: str = Field(min_length=1, max_length=2000)
    source_line_start: int = Field(ge=1)
    source_line_end: int = Field(ge=1)
    assets: list[str]
    levels: list[str]
    direction: Direction
    condition: str | None
    invalidation_condition: str | None
    time_horizon: str | None
    normalized_horizon_hours: NormalizedHorizonHours | None = None
    scoreability: Scoreability
    not_scoreable_reason: str | None
    extraction_confidence: float = Field(ge=0, le=1)
    human_review_required: bool = True
    review_required_fields: list[ReviewRequiredField] = Field(default_factory=list)
    review_flags: list[ClaimReviewFlag] = Field(default_factory=list)


class ModelClaimExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str = Field(min_length=1)
    claims: list[ClaimCandidate]
    extraction_notes: list[str]
