from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    project_name: str = Field(default="Market Analysis Audit Lab", alias="PROJECT_NAME")
    analyst_name: str = Field(default="", alias="ANALYST_NAME")
    youtube_channel_url: str = Field(default="", alias="YOUTUBE_CHANNEL_URL")
    youtube_channel_id: str = Field(default="", alias="YOUTUBE_CHANNEL_ID")
    source_mode: str = Field(default="provided", pattern="^(provided|youtube)$", alias="SOURCE_MODE")
    provided_sources_dir: Path = Field(default=Path("/workspace/import"), alias="PROVIDED_SOURCES_DIR")
    start_date: date = Field(default=date(2024, 1, 1), alias="START_DATE")
    end_date: date = Field(default=date(2024, 1, 31), alias="END_DATE")
    max_audit_days: int = Field(default=120, ge=1, le=730, alias="MAX_AUDIT_DAYS")

    audit_mode: str = Field(default="offline", pattern="^(offline|api)$", alias="AUDIT_MODE")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_claim_model: str = Field(
        default="gpt-5.6-luna",
        validation_alias=AliasChoices("OPENAI_MODEL_CLAIM_EXTRACTION", "OPENAI_CLAIM_MODEL"),
    )
    openai_scoring_model: str = Field(
        default="gpt-5.6-terra",
        validation_alias=AliasChoices("OPENAI_MODEL_SCORING", "OPENAI_SUMMARY_MODEL"),
    )
    openai_claim_reasoning_effort: str = Field(default="low", alias="OPENAI_CLAIM_REASONING_EFFORT")
    openai_scoring_reasoning_effort: str = Field(default="low", alias="OPENAI_SCORING_REASONING_EFFORT")
    openai_max_retries: int = Field(default=2, ge=0, le=8, alias="OPENAI_MAX_RETRIES")
    openai_concurrency: int = Field(default=3, ge=1, le=8, alias="OPENAI_CONCURRENCY")
    openai_timeout_seconds: float = Field(default=180.0, gt=0, alias="OPENAI_TIMEOUT_SECONDS")
    api_cost_acknowledged: bool = Field(default=False, alias="API_COST_ACKNOWLEDGED")

    openai_claim_input_usd_per_1m: float | None = Field(default=None, ge=0, alias="OPENAI_CLAIM_INPUT_USD_PER_1M")
    openai_claim_cached_input_usd_per_1m: float | None = Field(default=None, ge=0, alias="OPENAI_CLAIM_CACHED_INPUT_USD_PER_1M")
    openai_claim_output_usd_per_1m: float | None = Field(default=None, ge=0, alias="OPENAI_CLAIM_OUTPUT_USD_PER_1M")
    openai_scoring_input_usd_per_1m: float | None = Field(default=None, ge=0, alias="OPENAI_SCORING_INPUT_USD_PER_1M")
    openai_scoring_cached_input_usd_per_1m: float | None = Field(default=None, ge=0, alias="OPENAI_SCORING_CACHED_INPUT_USD_PER_1M")
    openai_scoring_output_usd_per_1m: float | None = Field(default=None, ge=0, alias="OPENAI_SCORING_OUTPUT_USD_PER_1M")

    workspace_dir: Path = Field(default=Path("/workspace"), alias="WORKSPACE_DIR")
    max_scan_items: int = Field(default=220, ge=1, le=5000, alias="MAX_SCAN_ITEMS")
    require_subtitles_for_audit: bool = Field(default=True, alias="REQUIRE_SUBTITLES_FOR_AUDIT")
    strict_source_channel: bool = Field(default=True, alias="STRICT_SOURCE_CHANNEL")
    source_rights_acknowledged: bool = Field(default=False, alias="SOURCE_RIGHTS_ACKNOWLEDGED")
    subtitle_languages_raw: str = Field(default="fa-orig,fa-IR,fa,en-orig,en", alias="SUBTITLE_LANGUAGES")
    collect_thumbnails: bool = Field(default=False, alias="COLLECT_THUMBNAILS")
    transcription_fallback: bool = Field(default=False, alias="TRANSCRIPTION_FALLBACK")
    openai_transcription_model: str = Field(default="whisper-1", alias="OPENAI_TRANSCRIPTION_MODEL")
    transcription_language: str | None = Field(default=None, alias="TRANSCRIPTION_LANGUAGE")
    transcription_prompt: str | None = Field(default=None, alias="TRANSCRIPTION_PROMPT")
    transcription_chunk_seconds: int = Field(default=1200, ge=60, le=3600, alias="TRANSCRIPTION_CHUNK_SECONDS")
    retain_raw_audio: bool = Field(default=False, alias="RETAIN_RAW_AUDIO")

    audit_scope_categories_raw: str = Field(default="crypto,global_markets", alias="AUDIT_SCOPE_CATEGORIES")
    category_overrides_file: Path | None = Field(default=None, alias="CATEGORY_OVERRIDES_FILE")
    asset_map_file: Path | None = Field(default=None, alias="ASSET_MAP_FILE")
    price_outcome_only: bool = Field(default=True, alias="PRICE_OUTCOME_ONLY")
    international_market_provider: str = Field(default="yfinance", pattern="^(yfinance|csv)$", alias="INTERNATIONAL_MARKET_PROVIDER")
    market_csv_dir: Path | None = Field(default=None, alias="MARKET_CSV_DIR")
    report_default_language: str = Field(default="en", pattern="^(en|fa)$", alias="REPORT_DEFAULT_LANGUAGE")
    publication_mode: str = Field(default="private", pattern="^(private|public)$", alias="PUBLICATION_MODE")
    public_claim_ledger: bool = Field(default=False, alias="PUBLIC_CLAIM_LEDGER")

    @field_validator(
        "openai_api_key",
        "transcription_language",
        "transcription_prompt",
        "category_overrides_file",
        "asset_map_file",
        "market_csv_dir",
        "openai_claim_input_usd_per_1m",
        "openai_claim_cached_input_usd_per_1m",
        "openai_claim_output_usd_per_1m",
        "openai_scoring_input_usd_per_1m",
        "openai_scoring_cached_input_usd_per_1m",
        "openai_scoring_output_usd_per_1m",
        mode="before",
    )
    @classmethod
    def blank_optional_values_are_unset(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "Settings":
        if self.end_date < self.start_date:
            raise ValueError("END_DATE must be on or after START_DATE")
        days = (self.end_date - self.start_date).days + 1
        if days > self.max_audit_days:
            raise ValueError(f"Audit window is {days} days; MAX_AUDIT_DAYS is {self.max_audit_days}")
        return self

    @property
    def subtitle_languages(self) -> tuple[str, ...]:
        values = tuple(value.strip() for value in self.subtitle_languages_raw.split(",") if value.strip())
        return values or ("en",)

    @property
    def audit_scope_categories(self) -> tuple[str, ...]:
        values = tuple(value.strip() for value in self.audit_scope_categories_raw.split(",") if value.strip())
        invalid = [value for value in values if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value)]
        if invalid:
            raise ValueError("Invalid AUDIT_SCOPE_CATEGORIES: " + ", ".join(invalid))
        return values or ("crypto", "global_markets")

    def require_source_configuration(self) -> None:
        missing = []
        if not self.analyst_name.strip():
            missing.append("ANALYST_NAME")
        if self.source_mode == "youtube" and not self.youtube_channel_url.strip():
            missing.append("YOUTUBE_CHANNEL_URL")
        if not self.youtube_channel_id.strip():
            missing.append("YOUTUBE_CHANNEL_ID")
        if missing:
            raise SystemExit("Missing source configuration: " + ", ".join(missing))
        if not self.source_rights_acknowledged:
            raise SystemExit(
                "SOURCE_RIGHTS_ACKNOWLEDGED must be true. Confirm that source collection and use "
                "are permitted by applicable terms, licenses, and law."
            )

    def require_openai_configuration(self) -> None:
        if self.audit_mode != "api":
            raise SystemExit("Set AUDIT_MODE=api before running an OpenAI-backed stage.")
        if not self.openai_api_key:
            raise SystemExit("OPENAI_API_KEY is required for this stage.")
        if not self.api_cost_acknowledged:
            raise SystemExit("API_COST_ACKNOWLEDGED must be true before a paid API stage can run.")

    @property
    def openai_api_key_value(self) -> str | None:
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    @property
    def start_compact(self) -> str:
        return self.start_date.strftime("%Y%m%d")

    @property
    def end_compact(self) -> str:
        return self.end_date.strftime("%Y%m%d")

    @property
    def raw_dir(self) -> Path:
        return self.workspace_dir / "raw"

    @property
    def logs_dir(self) -> Path:
        return self.workspace_dir / "logs"

    @property
    def pack_dir(self) -> Path:
        return self.workspace_dir / "audit_pack"

    @property
    def reports_dir(self) -> Path:
        return self.workspace_dir / "reports"

    @property
    def analysis_dir(self) -> Path:
        return self.workspace_dir / "analysis"

    @property
    def claims_dir(self) -> Path:
        return self.analysis_dir / "claims"

    @property
    def outcomes_dir(self) -> Path:
        return self.analysis_dir / "outcomes"

    @property
    def scores_dir(self) -> Path:
        return self.analysis_dir / "scores"

    @property
    def review_dir(self) -> Path:
        return self.workspace_dir / "review"

    @property
    def human_review_ledger_path(self) -> Path:
        return self.review_dir / "human_review.json"

    @property
    def publication_review_ledger_path(self) -> Path:
        return self.review_dir / "publication_review.json"

    @property
    def cache_dir(self) -> Path:
        return self.workspace_dir / "cache"


def get_settings() -> Settings:
    return Settings()
