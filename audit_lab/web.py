from __future__ import annotations

import json
import mimetypes
import re
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from audit_lab.settings import Settings, get_settings
from audit_lab.publication import load_verified_publication_snapshot
from audit_lab.stages.report import build_dashboard_data


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
TEMPLATE_DIR = PACKAGE_DIR / "templates"

settings = get_settings()
mimetypes.add_type("font/woff2", ".woff2")
app = FastAPI(
    title="Market Analysis Audit Lab",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


LIMITATION_TRANSLATIONS = {
    (
        "Videos outside AUDIT_SCOPE_CATEGORIES remain visible in the source ledger "
        "but do not enter the score."
    ): (
        "ویدیوهای خارج از AUDIT_SCOPE_CATEGORIES در دفتر منابع "
        "حفظ می‌شوند، "
        "اما در امتیاز وارد نمی‌شوند."
    ),
    (
        "Context inputs such as liquidation maps, ETF flows, and macro explanations "
        "are not independently audited."
    ): (
        "ورودی‌های زمینه‌ای مانند نقشه‌های لیکوییدیشن، "
        "جریان ETF "
        "و توضیحات کلان "
        "به‌طور مستقل ممیزی نشده‌اند."
    ),
    (
        "Binance one-minute spot data is the crypto benchmark; another venue may differ "
        "at borderline levels."
    ): (
        "داده یک‌دقیقه‌ای بازار نقدی بایننس معیار رمزارز است؛ "
        "بازارهای دیگر ممکن است "
        "در سطوح مرزی تفاوت داشته باشند."
    ),
    (
        "International outcomes use either operator-provided CSV data or explicitly "
        "labelled Yahoo proxies."
    ): (
        "نتایج بازارهای بین‌المللی از CSV ارائه‌شده "
        "توسط اپراتور "
        "یا پروکسی‌های صریحاً "
        "برچسب‌خورده یاهو استفاده می‌کنند."
    ),
    (
        "Recent videos whose 24-hour window has not elapsed remain insufficient evidence."
    ): (
        "ویدیوهای تازه‌ای که پنجره ۲۴ساعته آن‌ها "
        "کامل نشده است، "
        "همچنان شواهد ناکافی "
        "محسوب می‌شوند."
    ),
    (
        "AI-assisted extraction and scoring require human review and are not objective "
        "ground truth."
    ): (
        "استخراج و امتیازدهی با کمک هوش مصنوعی "
        "به بازبینی انسانی "
        "نیاز دارد و حقیقت "
        "عینی و قطعی نیست."
    ),
}


def _waiting_data(message: str = "Run collection and manifest stages first.") -> dict[str, Any]:
    return {
        "status": "waiting_for_manifest",
        "project_name": settings.project_name,
        "message": message,
        "date_range": {"start": str(settings.start_date), "end": str(settings.end_date)},
        "audit_summary": None,
        "scenario_profile": None,
        "scope": None,
        "limitations": [],
    }


def _read_dashboard_data() -> dict[str, Any]:
    snapshot = settings.reports_dir / "dashboard_data.json"
    if snapshot.is_file():
        try:
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            return _waiting_data(
                "The local dashboard snapshot could not be read. Regenerate the report stage."
            )
    try:
        payload = build_dashboard_data(settings)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _waiting_data(
            "Local audit artifacts are incomplete or unreadable. Check the workspace "
            "and regenerate the report."
        )
    return payload if isinstance(payload, dict) else _waiting_data()


def _is_synthetic_demo(data: dict[str, Any]) -> bool:
    if data.get("synthetic_demo"):
        return True
    project_name = str(data.get("project_name") or "")
    if "demo" in project_name.casefold():
        return True
    return any(
        isinstance(data.get(key), dict) and bool(data[key].get("synthetic_demo"))
        for key in ("claims", "outcomes", "scores")
    )


def _prepare_view_data(
    payload: dict[str, Any],
    *,
    report_available: bool = False,
    claim_ledger_available: bool = False,
) -> dict[str, Any]:
    data = deepcopy(payload)
    data["synthetic_demo"] = _is_synthetic_demo(data)
    review_accepted = bool(
        isinstance(data.get("human_review"), dict)
        and data["human_review"].get("accepted_for_current_artifacts")
    )
    integrity_warning = data.get("status") == "integrity_warning" or bool(
        isinstance(data.get("verification"), dict)
        and data["verification"].get("verified") is False
    )
    publication_ready = (
        settings.publication_mode == "public"
        and review_accepted
        and not integrity_warning
    )
    data["publication"] = {
        "mode": settings.publication_mode,
        "requires_human_review": settings.publication_mode == "public",
        "human_review_accepted": review_accepted,
        "ready": publication_ready,
        "public_claim_ledger": bool(publication_ready and settings.public_claim_ledger),
    }
    if integrity_warning:
        data["status"] = "integrity_warning"
    elif (
        data.get("audit_summary")
        and data.get("scenario_profile")
    ):
        if settings.publication_mode == "private":
            data["status"] = "private_preview"
        elif not review_accepted:
            data["status"] = "human_review_pending"
        elif data.get("status") != "integrity_warning":
            data["status"] = "audit_complete"
    data["report_available"] = bool(publication_ready and report_available)
    data["claim_ledger_available"] = bool(
        publication_ready
        and settings.public_claim_ledger
        and claim_ledger_available
    )
    limitations = data.get("limitations") or []
    if not isinstance(limitations, list):
        limitations = []
    data["localized_limitations"] = [
        {"en": str(item), "fa": LIMITATION_TRANSLATIONS.get(str(item), str(item))}
        for item in limitations
    ]
    return data


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return value
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme.casefold(), netloc, parsed.path, "", ""))


def _redact_text(value: str, active_settings: Settings) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() in {"http", "https"}:
        return _sanitize_url(value)
    if "http://" in value.casefold() or "https://" in value.casefold():
        value = re.sub(
            r"https?://[^\s<>\"']+",
            lambda match: _sanitize_url(match.group(0)),
            value,
            flags=re.IGNORECASE,
        )
    text = value
    workspace_values = {str(active_settings.workspace_dir), str(active_settings.workspace_dir.resolve())}
    for workspace in sorted(workspace_values, key=len, reverse=True):
        if workspace and workspace != ".":
            text = text.replace(workspace.rstrip("/"), "<workspace>")
    home = str(Path.home())
    if home:
        text = text.replace(home.rstrip("/"), "<home>")
    if text.casefold().startswith("file://"):
        return "<local-file>"
    if text.startswith("/"):
        return f"<local-path>/{Path(text).name}" if Path(text).name else "<local-path>"
    if re.match(r"^[A-Za-z]:[\\/]", text):
        normalized = text.replace("\\", "/")
        return f"<local-path>/{Path(normalized).name}"
    return text


def _redact_paths(value: Any, active_settings: Settings = settings) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_paths(item, active_settings) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_paths(item, active_settings) for item in value]
    if isinstance(value, tuple):
        return [_redact_paths(item, active_settings) for item in value]
    if isinstance(value, str):
        return _redact_text(value, active_settings)
    return value


def _pick(source: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: source.get(key) for key in keys if key in source}


def _public_audit_summary(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    safe = _pick(source, (
        "score", "total_claims", "counted_claims", "not_counted_claims",
        "data_supported_claims", "resolved_claims", "not_triggered_claims",
        "score_bearing_percent", "coverage_percent", "evidence_coverage_percent",
        "resolution_percent", "activation_percent", "at_least_partial_count",
        "at_least_partial_percent", "correct_count", "partial_count", "incorrect_count",
        "weighted_points", "conclusion", "headline", "conclusion_detail", "conclusion_tone",
    ))
    safe["counted_results"] = [
        _pick(row, ("key", "label", "count", "percent"))
        for row in source.get("counted_results", []) if isinstance(row, dict)
    ]
    safe["excluded_results"] = [
        _pick(row, ("key", "label", "count", "percent_of_all"))
        for row in source.get("excluded_results", []) if isinstance(row, dict)
    ]
    category_keys = (
        "key", "label", "total_claims", "counted_claims", "evidence_coverage_percent",
        "score_bearing_percent", "resolved_claims", "score", "correct", "partial",
        "incorrect", "at_least_partial_count", "at_least_partial_percent", "not_triggered",
        "insufficient", "correct_percent", "partial_percent", "incorrect_percent",
    )
    safe["categories"] = [
        _pick(row, category_keys)
        for row in source.get("categories", []) if isinstance(row, dict)
    ]
    return safe


def _public_dashboard_dto(
    payload: dict[str, Any],
    *,
    report_available: bool = False,
    claim_ledger_available: bool = False,
) -> dict[str, Any]:
    """Return the only object contract allowed to cross the public web boundary."""
    data = _prepare_view_data(
        payload,
        report_available=report_available,
        claim_ledger_available=claim_ledger_available,
    )
    safe: dict[str, Any] = _pick(data, (
        "status", "project_name", "collection_id", "created_at_utc", "synthetic_demo",
        "report_available", "claim_ledger_available",
    ))
    if data.get("status") == "publication_unavailable":
        safe["message"] = "The verified public audit snapshot is temporarily unavailable."
    elif data.get("status") == "waiting_for_manifest":
        safe["message"] = "The public audit snapshot is not available yet."
    else:
        safe["message"] = None
    safe["date_range"] = _pick(data.get("date_range"), ("start", "end"))
    safe["summary"] = _pick(data.get("summary"), (
        "total_videos_found", "videos_included", "videos_automatically_excluded",
        "videos_manually_excluded", "missing_subtitles_found",
    ))
    safe["scope"] = _pick(data.get("scope"), (
        "categories", "category_labels", "source_videos_found", "videos_in_scope_found",
        "videos_audited", "automatic_exclusions", "manual_exclusions", "out_of_scope_videos",
        "out_of_scope_categories", "category_counts", "price_outcome_only",
    )) or None
    safe["audit_summary"] = _public_audit_summary(data.get("audit_summary"))
    safe["scenario_profile"] = (
        _pick(data.get("scenario_profile"), (
            "total_claims", "total_videos", "average_claims_per_video", "conditional_claims",
            "conditional_claim_percent", "explicit_condition_claims", "explicit_condition_percent",
            "level_claims", "level_claim_percent", "multi_level_claims", "multi_level_claim_percent",
            "invalidation_claims", "invalidation_claim_percent", "scenario_claims",
            "scenario_claim_percent", "both_directions_videos", "both_directions_video_percent",
            "invalidation_videos", "invalidation_video_percent", "ten_plus_claim_videos",
            "ten_plus_claim_video_percent",
        )) or None
    )
    outcome = data.get("outcome_summary")
    if isinstance(outcome, dict):
        safe["outcome_summary"] = _pick(outcome, (
            "complete_claims", "available_series", "provider", "snapshot_sha256",
            "market_evidence_snapshot_sha256",
        ))
        safe["outcome_summary"]["providers"] = [
            _pick(row, (
                "name", "scope", "resolution", "integrity", "series_count", "row_count",
                "raw_file_count", "checksums_verified",
            ))
            for row in outcome.get("providers", []) if isinstance(row, dict)
        ]
    else:
        safe["outcome_summary"] = None
    safe["verification"] = _pick(data.get("verification"), (
        "status", "verified", "file_hash_count", "failed_file_hash_count",
    )) or None
    safe["tamper_evidence"] = _pick(data.get("tamper_evidence"), (
        "manifest_sha256", "archive_sha256", "market_evidence_sha256", "outcome_sha256",
        "file_hash_count", "verification_status",
    ))
    safe["publication"] = _pick(data.get("publication"), (
        "mode", "requires_human_review", "human_review_accepted", "ready",
        "public_claim_ledger",
    ))
    safe["human_review"] = _pick(data.get("human_review"), (
        "status", "ledger_valid", "accepted_for_current_artifacts", "reviewed_at_utc",
        "binding_sha256",
    ))
    # Only the fixed report-stage limitation register is admitted. Unknown strings are discarded.
    known_limitations = set(LIMITATION_TRANSLATIONS)
    limitations = [
        item for item in data.get("limitations", [])
        if isinstance(item, str) and item in known_limitations
    ]
    safe["limitations"] = limitations
    safe["localized_limitations"] = [
        {"en": item, "fa": LIMITATION_TRANSLATIONS[item]} for item in limitations
    ]
    return _redact_paths(safe)


def _public_claim(claim: Any) -> dict[str, Any] | None:
    if not isinstance(claim, dict):
        return None
    return _pick(claim, (
        "claim_id", "video_id", "upload_date", "category", "claim_text", "source_excerpt",
        "source_line_start", "source_line_end", "assets", "levels", "direction", "claim_type",
        "condition", "invalidation_condition", "time_horizon", "normalized_horizon_hours",
        "scoreability", "not_scoreable_reason", "extraction_confidence",
    ))


def _public_score(score: Any) -> dict[str, Any] | None:
    if not isinstance(score, dict):
        return None
    return _pick(score, (
        "claim_id", "video_id", "upload_date", "category", "result", "score",
        "counts_in_final_score", "trigger_status", "data_sufficiency", "evidence_summary",
        "reasoning", "evaluation_window", "scoring_confidence",
    ))


def _public_outcome(outcome: Any) -> dict[str, Any] | None:
    if not isinstance(outcome, dict):
        return None
    safe = _pick(outcome, (
        "claim_id", "video_id", "category", "published_at_utc", "published_at_source", "status",
    ))
    asset_keys = ("asset", "series_key", "provider", "venue", "symbol", "interval", "proxy_note", "status")
    window_keys = (
        "hours", "status", "complete", "bar_count", "open", "high", "low", "close",
        "return_pct", "max_up_pct", "max_down_pct", "level_events",
    )
    assets = []
    for asset in outcome.get("assets", []):
        if not isinstance(asset, dict):
            continue
        public_asset = _pick(asset, asset_keys)
        public_asset["window_24h"] = _pick(asset.get("window_24h"), window_keys)
        public_asset["window_48h"] = _pick(asset.get("window_48h"), window_keys)
        assets.append(public_asset)
    safe["assets"] = assets
    return safe


def _publication_unavailable_data() -> dict[str, Any]:
    return {
        "status": "publication_unavailable",
        "project_name": "Market Analysis Audit Lab",
        "message": "The verified public audit snapshot is unavailable.",
        "date_range": {},
        "audit_summary": None,
        "scenario_profile": None,
        "scope": None,
        "limitations": [],
    }


def _dashboard_boundary() -> tuple[dict[str, Any], dict[str, Any] | None]:
    if settings.publication_mode != "public":
        return _read_dashboard_data(), None
    snapshot = load_verified_publication_snapshot(settings)
    if snapshot is None:
        return _publication_unavailable_data(), None
    return snapshot["dashboard"], snapshot


@app.middleware("http")
async def publication_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; "
        "object-src 'none'; img-src 'self' data:; font-src 'self'; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'",
    )
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if settings.publication_mode != "public":
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    if request.url.path.startswith("/api/") or request.url.path in {"/", "/report"}:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    payload, snapshot = _dashboard_boundary()
    data = _public_dashboard_dto(
        payload,
        report_available=bool(snapshot and snapshot.get("report")),
        claim_ledger_available=bool(snapshot and snapshot.get("claim_artifacts")),
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"data": data},
    )


@app.get("/health", response_class=JSONResponse)
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "market-analysis-audit-lab",
        "workspace_ready": settings.workspace_dir.is_dir(),
    }


@app.get("/api/dashboard", response_class=JSONResponse)
def dashboard_api() -> dict[str, Any]:
    payload, snapshot = _dashboard_boundary()
    return _public_dashboard_dto(
        payload,
        report_available=bool(snapshot and snapshot.get("report")),
        claim_ledger_available=bool(snapshot and snapshot.get("claim_artifacts")),
    )


@app.get("/api/claims", response_class=JSONResponse)
def claims_api(
    result: str | None = None,
    category: str | None = None,
    counted: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    payload, snapshot = _dashboard_boundary()
    dashboard_data = _public_dashboard_dto(
        payload,
        report_available=bool(snapshot and snapshot.get("report")),
        claim_ledger_available=bool(snapshot and snapshot.get("claim_artifacts")),
    )
    if not (
        snapshot is not None
        and settings.publication_mode == "public"
        and bool(getattr(settings, "public_claim_ledger", False))
        and dashboard_data.get("publication", {}).get("ready")
    ):
        raise HTTPException(status_code=404, detail="Not found")
    artifacts = snapshot.get("claim_artifacts")
    if not isinstance(artifacts, dict):
        raise HTTPException(status_code=404, detail="Claim ledger is not available")
    try:
        claim_rows = [
            json.loads(line)
            for line in artifacts["claims"].decode("utf-8").splitlines()
            if line.strip()
        ]
        score_rows = [
            json.loads(line)
            for line in artifacts["scores"].decode("utf-8").splitlines()
            if line.strip()
        ]
        outcome_payload = json.loads(artifacts["outcomes"])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="Claim ledger could not be read") from None

    scores = {row.get("claim_id"): row for row in score_rows if row.get("claim_id")}
    outcomes = {
        row.get("claim_id"): row
        for row in outcome_payload.get("claims", [])
        if isinstance(row, dict) and row.get("claim_id")
    }
    scope = set(settings.audit_scope_categories)
    rows: list[dict[str, Any]] = []
    for claim in claim_rows:
        if not isinstance(claim, dict) or claim.get("category") not in scope:
            continue
        score = scores.get(claim.get("claim_id"))
        if result is not None and (score or {}).get("result") != result:
            continue
        if category is not None and claim.get("category") != category:
            continue
        if counted is not None and bool((score or {}).get("counts_in_final_score")) != counted:
            continue
        rows.append({
            "claim": _public_claim(claim),
            "score": _public_score(score),
            "outcome": _public_outcome(outcomes.get(claim.get("claim_id"))),
        })
    rows.sort(key=lambda row: (
        row["claim"].get("upload_date", ""),
        row["claim"].get("claim_id", ""),
    ))
    response = {
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "filters": {"result": result, "category": category, "counted": counted},
        "items": rows[offset:offset + limit],
    }
    return _redact_paths(response)


@app.head("/report", response_class=Response)
@app.get("/report", response_class=Response)
def report() -> Response:
    payload, snapshot = _dashboard_boundary()
    dashboard_data = _public_dashboard_dto(
        payload,
        report_available=bool(snapshot and snapshot.get("report")),
        claim_ledger_available=bool(snapshot and snapshot.get("claim_artifacts")),
    )
    if not (
        settings.publication_mode == "public"
        and dashboard_data.get("publication", {}).get("ready")
    ):
        raise HTTPException(status_code=404, detail="Not found")
    verified_report = snapshot.get("report") if snapshot else None
    if not verified_report:
        raise HTTPException(status_code=404, detail="PDF report is not available")
    report_bytes, _report_name = verified_report
    return Response(
        content=report_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="audit-report.pdf"'},
    )
