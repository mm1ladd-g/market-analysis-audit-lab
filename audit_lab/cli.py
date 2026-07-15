from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

from audit_lab.demo import seed_synthetic_demo, synthetic_demo_settings
from audit_lab.settings import Settings, get_settings
from audit_lab.stages.collect import run_collection
from audit_lab.stages.extract_claims import run_claim_extraction
from audit_lab.stages.fetch_outcomes import fetch_market_outcomes
from audit_lab.stages.finalize import (
    finalize_audit,
    get_human_review_status,
    get_publication_review_status,
    record_human_review,
    record_publication_review,
    verify_final_audit,
)
from audit_lab.stages.import_sources import import_provided_sources
from audit_lab.stages.manifest import build_manifest
from audit_lab.stages.report import build_dashboard_data, write_dashboard_data
from audit_lab.stages.score_claims import run_scoring
from audit_lab.stages.transcribe import run_transcription_fallback
from audit_lab.stages.verify import verify_audit_pack


console = Console()


def _safe_config(settings: Settings) -> dict:
    return {
        "project": settings.project_name,
        "analyst": settings.analyst_name or "<not configured>",
        "channel_url": settings.youtube_channel_url or "<not configured>",
        "channel_id": settings.youtube_channel_id or "<not configured>",
        "source_mode": settings.source_mode,
        "date_range": [str(settings.start_date), str(settings.end_date)],
        "scope": list(settings.audit_scope_categories),
        "subtitle_languages": list(settings.subtitle_languages),
        "workspace": str(settings.workspace_dir),
        "audit_mode": settings.audit_mode,
        "openai_key_present": bool(settings.openai_api_key),
        "source_rights_acknowledged": settings.source_rights_acknowledged,
        "api_cost_acknowledged": settings.api_cost_acknowledged,
        "publication_mode": settings.publication_mode,
        "public_claim_ledger": settings.public_claim_ledger,
    }


def cmd_doctor(settings: Settings) -> None:
    table = Table(title="Market Analysis Audit Lab · doctor")
    table.add_column("Check")
    table.add_column("Result")
    checks = {
        "yt-dlp": shutil.which("yt-dlp") is not None,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "deno": shutil.which("deno") is not None,
        "workspace parent": settings.workspace_dir.parent.exists(),
        "source configured": bool(
            settings.analyst_name
            and settings.youtube_channel_id
            and (settings.source_mode == "provided" or settings.youtube_channel_url)
        ),
        "rights acknowledged": settings.source_rights_acknowledged,
        "OpenAI key present": bool(settings.openai_api_key),
    }
    for name, passed in checks.items():
        table.add_row(name, "[green]ready[/green]" if passed else "[yellow]not ready / optional[/yellow]")
    console.print(table)
    console.print_json(data=_safe_config(settings))


def cmd_smoke(settings: Settings) -> None:
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    for directory in [settings.raw_dir, settings.logs_dir, settings.reports_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    probe = settings.workspace_dir / ".write-probe"
    probe.write_text("ok\n", encoding="utf-8")
    probe.unlink()
    console.print("[bold green]Configuration and workspace are usable.[/bold green]")
    console.print_json(data=_safe_config(settings))


def cmd_status(settings: Settings) -> None:
    paths = {
        "collection": settings.logs_dir / "collection_run.json",
        "manifest": settings.pack_dir / "manifest.json",
        "claims": settings.claims_dir / "extraction_run.json",
        "outcomes": settings.outcomes_dir / "claim_outcomes.json",
        "scores": settings.scores_dir / "scoring_run.json",
        "dashboard": settings.reports_dir / "dashboard_data.json",
        "final": settings.workspace_dir / "final_audit_summary.json",
    }
    console.print_json(data={
        "artifacts": {name: path.is_file() for name, path in paths.items()},
        "publication_mode": settings.publication_mode,
        "human_review": get_human_review_status(settings),
        "publication_review": get_publication_review_status(settings),
    })


def cmd_run(settings: Settings, stop_after: str) -> None:
    collect_stage = import_provided_sources if settings.source_mode == "provided" else run_collection
    stages = [
        ("collect", lambda: collect_stage(settings)),
        ("transcribe", lambda: run_transcription_fallback(settings)),
        ("manifest", lambda: build_manifest(settings)),
        ("extract-claims", lambda: run_claim_extraction(settings)),
        ("fetch-outcomes", lambda: fetch_market_outcomes(settings)),
        ("score", lambda: run_scoring(settings)),
        ("report", lambda: write_dashboard_data(settings)),
        ("finalize", lambda: finalize_audit(settings)),
    ]
    for name, stage in stages:
        console.rule(name)
        stage()
        if name == stop_after:
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Analysis Audit Lab CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in [
        "doctor", "smoke", "status", "collect", "transcribe", "manifest", "verify",
        "fetch-outcomes", "report",
    ]:
        sub.add_parser(name)
    for name in ("finalize", "verify-final"):
        final_parser = sub.add_parser(name)
        final_parser.add_argument(
            "--synthetic-demo",
            action="store_true",
            help="Use the fixed synthetic-demo configuration instead of .env",
        )
        final_parser.add_argument("--workspace", type=Path, default=Path("/workspace"))
    extract = sub.add_parser("extract-claims")
    extract.add_argument("--limit", type=int)
    extract.add_argument("--video-id", action="append", dest="video_ids")
    extract.add_argument("--force", action="store_true")
    score = sub.add_parser("score")
    score.add_argument("--limit", type=int)
    score.add_argument("--video-id", action="append", dest="video_ids")
    score.add_argument("--force", action="store_true")
    run = sub.add_parser("run")
    run.add_argument(
        "--stop-after",
        choices=[
            "collect", "transcribe", "manifest", "extract-claims", "fetch-outcomes",
            "score", "report", "finalize",
        ],
        default="finalize",
    )
    demo = sub.add_parser("demo")
    demo.add_argument("--workspace", type=Path, default=Path("/workspace"))
    review = sub.add_parser("review", help="Inspect, accept, or revoke the human publication checkpoint")
    review_sub = review.add_subparsers(dest="review_action", required=True)
    review_sub.add_parser("status")
    review_sub.add_parser(
        "publication-status",
        help="Inspect whether the exact public dashboard, PDF, and optional ledger are accepted",
    )
    for action in ("accept", "revoke"):
        action_parser = review_sub.add_parser(action)
        action_parser.add_argument("--reviewer", required=True)
        action_parser.add_argument("--notes", default="")
    publication_accept = review_sub.add_parser(
        "publication-accept",
        help="Accept the exact finished public dashboard, PDF, and optional claim ledger",
    )
    publication_accept.add_argument("--reviewer", required=True)
    publication_accept.add_argument("--notes", default="")

    args = parser.parse_args(argv)
    if args.command == "demo":
        try:
            result = seed_synthetic_demo(args.workspace)
        except RuntimeError as exc:
            console.print(f"[bold red]Demo stopped:[/bold red] {exc}")
            return 2
        console.print_json(data=result)
        return 0

    settings = (
        synthetic_demo_settings(args.workspace)
        if getattr(args, "synthetic_demo", False)
        else get_settings()
    )
    if args.command == "doctor":
        cmd_doctor(settings)
    elif args.command == "smoke":
        cmd_smoke(settings)
    elif args.command == "status":
        cmd_status(settings)
    elif args.command == "collect":
        if settings.source_mode == "provided":
            import_provided_sources(settings)
        else:
            run_collection(settings)
    elif args.command == "transcribe":
        run_transcription_fallback(settings)
    elif args.command == "manifest":
        build_manifest(settings)
    elif args.command == "verify":
        result = verify_audit_pack(settings)
        console.print_json(data=result)
        if not result.get("verified"):
            return 1
    elif args.command == "extract-claims":
        run_claim_extraction(settings, limit=args.limit, video_ids=args.video_ids, force=args.force)
    elif args.command == "fetch-outcomes":
        fetch_market_outcomes(settings)
    elif args.command == "score":
        run_scoring(settings, limit=args.limit, video_ids=args.video_ids, force=args.force)
    elif args.command == "report":
        out = write_dashboard_data(settings)
        console.print(str(out))
    elif args.command == "finalize":
        console.print(str(finalize_audit(settings)))
    elif args.command == "review":
        if args.review_action == "status":
            console.print_json(data=get_human_review_status(settings))
        elif args.review_action == "publication-status":
            console.print_json(data=get_publication_review_status(settings))
        elif args.review_action == "publication-accept":
            result = record_publication_review(
                settings,
                reviewer=args.reviewer,
                notes=args.notes,
            )
            console.print_json(data=result)
        else:
            result = record_human_review(
                settings,
                action="accepted" if args.review_action == "accept" else "revoked",
                reviewer=args.reviewer,
                notes=args.notes,
            )
            # Refresh the presentation snapshot so the reports-only web service sees
            # the new checkpoint without access to private analysis directories.
            write_dashboard_data(settings)
            console.print_json(data=result)
    elif args.command == "verify-final":
        result = verify_final_audit(settings)
        console.print_json(data=result)
        if not result.get("verified"):
            return 1
    elif args.command == "run":
        cmd_run(settings, args.stop_after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
