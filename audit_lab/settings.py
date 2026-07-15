from __future__ import annotations

import re
from ipaddress import ip_address
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PUBLIC_DISCLOSURE_PLACEHOLDERS = {
    "coming soon",
    "example",
    "n/a",
    "none",
    "placeholder",
    "replace me",
    "tbd",
    "test",
    "todo",
}
_CREDENTIAL_LIKE = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{20,})"
)
_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
)
_NON_PUBLIC_HOST_SUFFIXES = (
    ".example",
    ".home.arpa",
    ".internal",
    ".invalid",
    ".local",
    ".localhost",
    ".test",
)


def _normalized_public_hostname(value: str, *, field_name: str) -> str:
    try:
        host = value.encode("idna").decode("ascii").casefold().rstrip(".")
    except UnicodeError as exc:
        raise ValueError(f"{field_name} contains an invalid hostname") from exc
    if not host or host == "localhost" or host.endswith(_NON_PUBLIC_HOST_SUFFIXES):
        raise ValueError(f"{field_name} must use a publicly reachable hostname")
    try:
        address = ip_address(host)
    except ValueError:
        if "." not in host or not all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError(f"{field_name} contains an invalid hostname") from None
    else:
        if not address.is_global:
            raise ValueError(
                f"{field_name} must not use a private, reserved, loopback, or link-local address"
            )
    return host


def _normalized_public_https_url(value: str, *, field_name: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() for character in value)
    ):
        raise ValueError(
            f"{field_name} must be a plain HTTPS URL without credentials, query, or fragment"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} contains an invalid port") from exc
    host = _normalized_public_hostname(parsed.hostname, field_name=field_name)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit(("https", netloc, parsed.path or "/", "", ""))


def _normalized_relationship_disclosure(value: str) -> str:
    normalized = " ".join(value.split())
    if (
        len(normalized) < 40
        or len(normalized) > 1500
        or len(normalized.split()) < 6
        or normalized.casefold() in _PUBLIC_DISCLOSURE_PLACEHOLDERS
        or "<" in normalized
        or ">" in normalized
    ):
        raise ValueError(
            "AUDIT_RELATIONSHIP_DISCLOSURE must be a meaningful 6+ word disclosure "
            "between 40 and 1500 characters"
        )
    if _CREDENTIAL_LIKE.search(normalized):
        raise ValueError("AUDIT_RELATIONSHIP_DISCLOSURE must not contain a credential")
    return normalized


def _normalized_correction_contact(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 500 or _CREDENTIAL_LIKE.search(normalized):
        raise ValueError("CORRECTION_CONTACT is invalid or contains a credential")
    if _EMAIL.fullmatch(normalized):
        local, domain = normalized.rsplit("@", 1)
        public_domain = _normalized_public_hostname(domain, field_name="CORRECTION_CONTACT")
        return f"{local}@{public_domain}"
    return _normalized_public_https_url(normalized, field_name="CORRECTION_CONTACT")


def is_valid_public_accountability_record(record: Any) -> bool:
    """Validate the exact untrusted DTO admitted into a public artifact set."""
    if not isinstance(record, dict) or set(record) != {
        "relationship_disclosure",
        "correction_contact",
        "correction_contact_href",
        "correction_policy_url",
    }:
        return False
    disclosure = record.get("relationship_disclosure")
    contact = record.get("correction_contact")
    contact_href = record.get("correction_contact_href")
    policy_url = record.get("correction_policy_url")
    if not isinstance(disclosure, str) or not isinstance(contact, str):
        return False
    try:
        if _normalized_relationship_disclosure(disclosure) != disclosure:
            return False
        if _normalized_correction_contact(contact) != contact:
            return False
        expected_href = f"mailto:{contact}" if _EMAIL.fullmatch(contact) else contact
        if contact_href != expected_href:
            return False
        if policy_url is not None and (
            not isinstance(policy_url, str)
            or _normalized_public_https_url(
                policy_url,
                field_name="CORRECTION_POLICY_URL",
            )
            != policy_url
        ):
            return False
    except ValueError:
        return False
    return True


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
    audit_relationship_disclosure: str | None = Field(
        default=None,
        alias="AUDIT_RELATIONSHIP_DISCLOSURE",
    )
    correction_contact: str | None = Field(default=None, alias="CORRECTION_CONTACT")
    correction_policy_url: str | None = Field(default=None, alias="CORRECTION_POLICY_URL")

    @field_validator(
        "openai_api_key",
        "transcription_language",
        "transcription_prompt",
        "category_overrides_file",
        "asset_map_file",
        "market_csv_dir",
        "audit_relationship_disclosure",
        "correction_contact",
        "correction_policy_url",
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

    @field_validator("audit_relationship_disclosure")
    @classmethod
    def validate_audit_relationship_disclosure(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_relationship_disclosure(value)

    @field_validator("correction_contact")
    @classmethod
    def validate_correction_contact(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_correction_contact(value)

    @field_validator("correction_policy_url")
    @classmethod
    def validate_correction_policy_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 500 or _CREDENTIAL_LIKE.search(normalized):
            raise ValueError("CORRECTION_POLICY_URL is invalid or contains a credential")
        return _normalized_public_https_url(normalized, field_name="CORRECTION_POLICY_URL")

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

    def require_publication_accountability(self) -> dict[str, str | None]:
        """Return the public disclosure record or stop a public publication workflow."""
        if self.publication_mode != "public":
            raise SystemExit(
                "Public accountability fields are only required when PUBLICATION_MODE=public."
            )
        missing = []
        if not self.audit_relationship_disclosure:
            missing.append("AUDIT_RELATIONSHIP_DISCLOSURE")
        if not self.correction_contact:
            missing.append("CORRECTION_CONTACT")
        if missing:
            raise SystemExit(
                "Public publication requires meaningful accountability metadata: "
                + ", ".join(missing)
            )
        contact = self.correction_contact
        contact_href = f"mailto:{contact}" if _EMAIL.fullmatch(contact) else contact
        return {
            "relationship_disclosure": self.audit_relationship_disclosure,
            "correction_contact": contact,
            "correction_contact_href": contact_href,
            "correction_policy_url": self.correction_policy_url,
        }

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
