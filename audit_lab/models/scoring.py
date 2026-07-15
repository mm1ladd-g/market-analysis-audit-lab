from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ResultCategory = Literal[
    "correct",
    "partially_correct",
    "incorrect",
    "not_triggered",
    "not_scoreable",
    "insufficient_data",
]
TriggerStatus = Literal["not_applicable", "triggered", "not_triggered", "unclear"]
DataSufficiency = Literal["sufficient", "partial", "insufficient", "unsupported_asset"]
EvaluationWindow = Literal["24h", "48h"]


class ClaimScoreCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    result: ResultCategory
    score: float = Field(ge=0, le=1)
    counts_in_final_score: bool
    trigger_status: TriggerStatus
    data_sufficiency: DataSufficiency
    evidence_summary: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    evaluation_window: EvaluationWindow | None
    scoring_confidence: float = Field(ge=0, le=1)


class ModelVideoScoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str = Field(min_length=1)
    scores: list[ClaimScoreCandidate]
    scoring_notes: list[str]
