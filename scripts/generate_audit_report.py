#!/usr/bin/env python3
"""Generate a generic bilingual market-analysis audit PDF.

The input is ``<workspace>/reports/dashboard_data.json`` and the stable output
is ``<workspace>/reports/audit-report.pdf``. The Persian edition always comes
first, followed by the English edition. The document reports only what is
present in the dashboard payload and handles waiting, partial, warning, and
complete audit states without inventing missing results.

The output deliberately describes all percentages as scenario-outcome
alignment. It is not a trading win rate, profitability analysis, investment
advice, or certification of an analyst, method, or source.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import arabic_reshaper
from bidi.algorithm import get_display
from fontTools.ttLib import TTFont as FontToolsFont
from fontTools.varLib.instancer import instantiateVariableFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
FONT_WOFF2 = ROOT / "audit_lab" / "static" / "fonts" / "Vazirmatn.woff2"
FONT_LICENSE = ROOT / "audit_lab" / "static" / "fonts" / "OFL.txt"
DEFAULT_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))

INK = colors.HexColor("#10231D")
DARK = colors.HexColor("#06150F")
DARK_2 = colors.HexColor("#0B241B")
GREEN = colors.HexColor("#00D58A")
GREEN_DARK = colors.HexColor("#158463")
MINT = colors.HexColor("#D5F5E9")
PAPER = colors.HexColor("#F5F6F1")
WHITE = colors.white
MUTED = colors.HexColor("#5C6C65")
LINE = colors.HexColor("#D6DFD9")
SOFT = colors.HexColor("#EAEFEA")
AMBER = colors.HexColor("#E6A93A")
AMBER_SOFT = colors.HexColor("#FFF1D4")
CORAL = colors.HexColor("#D8645B")
CORAL_SOFT = colors.HexColor("#FBE7E4")
BLUE = colors.HexColor("#4D91D7")

DISCLAIMER_EN = (
    "Scenario-outcome alignment is not a trading win rate, profitability proof, "
    "investment advice, or certification of an analyst, source, or method."
)
DISCLAIMER_FA = (
    "هم‌راستایی سناریو با نتیجه، نرخ برد معاملاتی، اثبات سودآوری، توصیه سرمایه‌گذاری "
    "یا گواهی کیفیت تحلیل‌گر، منبع یا روش نیست."
)
SYNTHETIC_EN = "SYNTHETIC DEMO - FICTIONAL DATA - NOT EVIDENCE ABOUT A REAL PERSON OR MARKET"
SYNTHETIC_FA = "نسخه نمایشی ساختگی - داده‌ها واقعی نیستند - این گزارش درباره شخص یا بازار واقعی نیست"

ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


class InvariantCanvas(Canvas):
    """ReportLab canvas with stable document IDs and timestamps."""

    def __init__(self, *args, **kwargs):
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_int(value: Any) -> str:
    return f"{_int(value):,}"


def _fmt_count(value: Any) -> str:
    return "-" if value is None or value == "" else _fmt_int(value)


def _fmt_pct(value: Any, empty: str = "-") -> str:
    number = _float(value)
    return f"{number:.1f}%" if number is not None else empty


def _escape(value: Any) -> str:
    return html.escape(_text(value), quote=False)


def _has_arabic(value: Any) -> bool:
    return bool(ARABIC_RE.search(_text(value)))


def _detect_synthetic(data: Mapping[str, Any]) -> bool:
    nested = [data, _mapping(data.get("claims")), _mapping(data.get("outcomes")), _mapping(data.get("scores"))]
    if any(bool(item.get("synthetic_demo")) for item in nested):
        return True
    identity = " ".join(
        [
            _text(data.get("project_name")),
            _text(data.get("analyst_name")),
            _text(_mapping(data.get("channel")).get("id")),
            _text(_mapping(data.get("channel")).get("url")),
        ]
    ).lower()
    return any(token in identity for token in ("synthetic", "fictional", "demo_not_real", "example.invalid"))


def _status_en(status: str) -> str:
    return {
        "waiting_for_manifest": "Waiting for source manifest",
        "collection_verified": "Collection recorded; analysis pending",
        "claims_complete": "Claims extracted; outcome scoring pending",
        "integrity_warning": "Integrity warning - inspect the evidence pack",
        "audit_complete": "Audit complete for the declared scope",
    }.get(status, status.replace("_", " ").title() or "Status unavailable")


def _status_fa(status: str) -> str:
    return {
        "waiting_for_manifest": "در انتظار مانیفست منبع",
        "collection_verified": "مجموعه ثبت شده و تحلیل هنوز در انتظار است",
        "claims_complete": "ادعاها استخراج شده‌اند و امتیازدهی نتیجه در انتظار است",
        "integrity_warning": "هشدار یکپارچگی؛ بسته شواهد باید بررسی شود",
        "audit_complete": "ممیزی برای دامنه اعلام‌شده کامل است",
    }.get(status, "وضعیت: " + (status.replace("_", " ") or "نامشخص"))


def _category_en(value: Any) -> str:
    key = _text(value)
    return {
        "crypto": "Crypto",
        "global_markets": "International markets",
        "local_markets": "Local markets",
    }.get(key, key.replace("_", " ").title() or "Unspecified")


def _category_fa(value: Any) -> str:
    key = _text(value)
    return {
        "crypto": "کریپتو",
        "global_markets": "بازارهای بین‌المللی",
        "local_markets": "بازارهای محلی",
    }.get(key, key.replace("_", " ") or "نامشخص")


def _convert_vazirmatn(source: Path, destination: Path, weight: int) -> None:
    font = FontToolsFont(str(source))
    if "fvar" in font:
        font = instantiateVariableFont(font, {"wght": weight}, inplace=False)
    font.flavor = None
    font.save(str(destination))
    font.close()


def _register_fonts(temp_dir: Path) -> None:
    if not FONT_WOFF2.is_file():
        raise FileNotFoundError(f"bundled Vazirmatn font is missing: {FONT_WOFF2}")
    if not FONT_LICENSE.is_file():
        raise FileNotFoundError(f"Vazirmatn OFL license is missing: {FONT_LICENSE}")
    regular = temp_dir / "Vazirmatn-Regular.ttf"
    bold = temp_dir / "Vazirmatn-Bold.ttf"
    _convert_vazirmatn(FONT_WOFF2, regular, 400)
    _convert_vazirmatn(FONT_WOFF2, bold, 700)
    if "Vazirmatn" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Vazirmatn", str(regular)))
    if "Vazirmatn-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("Vazirmatn-Bold", str(bold)))


def _visual_fa(value: Any) -> str:
    return get_display(arabic_reshaper.reshape(_text(value)), base_dir="R")


class RTLText(Flowable):
    """Persian text with line-by-line shaping and deterministic RTL wrapping."""

    def __init__(
        self,
        value: Any,
        *,
        font: str = "Vazirmatn",
        size: float = 9,
        leading: float | None = None,
        color=INK,
        space_before: float = 0,
        space_after: float = 0,
    ):
        super().__init__()
        self.value = _text(value)
        self.font = font
        self.size = size
        self.leading = leading or size * 1.55
        self.color = color
        self.spaceBefore = space_before
        self.spaceAfter = space_after
        self.width = 1
        self.height = self.leading
        self.lines: list[str] = []

    def _logical_lines(self, width: float) -> list[str]:
        output: list[str] = []
        for paragraph in self.value.replace("\r", "").split("\n"):
            words = paragraph.split()
            if not words:
                output.append("")
                continue
            line = words[0]
            for word in words[1:]:
                candidate = f"{line} {word}"
                if pdfmetrics.stringWidth(_visual_fa(candidate), self.font, self.size) <= width:
                    line = candidate
                else:
                    output.append(line)
                    line = word
            output.append(line)
        return output or [""]

    def wrap(self, avail_width, avail_height):
        self.width = max(1, avail_width)
        self.lines = [_visual_fa(line) if line else "" for line in self._logical_lines(self.width)]
        self.height = max(self.leading, len(self.lines) * self.leading)
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(self.color)
        canvas.setFont(self.font, self.size)
        y = self.height - self.size
        for line in self.lines:
            if line:
                canvas.drawRightString(self.width, y, line)
            y -= self.leading
        canvas.restoreState()


class PageBackground(Flowable):
    """Paint the internal English-edition cover before its content."""

    def __init__(self, synthetic: bool):
        super().__init__()
        self.synthetic = synthetic

    def wrap(self, avail_width, avail_height):
        return 0, 0

    def drawOn(self, canvas, x, y, _sW=0):
        _paint_dark_background(canvas)
        if self.synthetic:
            _paint_synthetic_banner(canvas, SYNTHETIC_EN)


class ProgressBar(Flowable):
    def __init__(self, label: str, value: Any, *, rtl: bool = False, accent=GREEN_DARK):
        super().__init__()
        self.label = label
        self.value = max(0.0, min(100.0, _float(value) or 0.0))
        self.rtl = rtl
        self.accent = accent
        self.width = 1
        self.height = 31

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        return avail_width, self.height

    def draw(self):
        c = self.canv
        y = 21
        c.setFillColor(INK)
        if self.rtl:
            c.setFont("Vazirmatn-Bold", 8.2)
            c.drawRightString(self.width, y, _visual_fa(self.label))
            c.setFont("Helvetica-Bold", 8.2)
            c.drawString(0, y, f"{self.value:.1f}%")
        else:
            c.setFont("Helvetica-Bold", 8.2)
            c.drawString(0, y, self.label)
            c.drawRightString(self.width, y, f"{self.value:.1f}%")
        c.setFillColor(SOFT)
        c.roundRect(0, 4, self.width, 7, 3.5, fill=1, stroke=0)
        bar_width = max(4, self.width * self.value / 100)
        c.setFillColor(self.accent)
        x = self.width - bar_width if self.rtl else 0
        c.roundRect(x, 4, bar_width, 7, 3.5, fill=1, stroke=0)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle("cover_kicker", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.5, leading=12, textColor=GREEN, spaceAfter=8),
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=31, leading=35, textColor=WHITE, alignment=TA_LEFT, spaceAfter=11),
        "cover_subtitle": ParagraphStyle("cover_subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=11.5, leading=17, textColor=colors.HexColor("#C5D6CE"), spaceAfter=12),
        "cover_meta": ParagraphStyle("cover_meta", parent=base["Normal"], fontName="Helvetica", fontSize=8.4, leading=13, textColor=colors.HexColor("#A8BCB2")),
        "eyebrow": ParagraphStyle("eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=GREEN_DARK, spaceAfter=5),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=INK, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=INK, spaceBefore=7, spaceAfter=7),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=INK, spaceAfter=4),
        "lead": ParagraphStyle("lead", parent=base["Normal"], fontName="Helvetica", fontSize=10.5, leading=16, textColor=colors.HexColor("#31463E"), spaceAfter=10),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=8.7, leading=13, textColor=INK, spaceAfter=6),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.4, leading=10.5, textColor=MUTED),
        "metric_number": ParagraphStyle("metric_number", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=19, leading=22, textColor=INK, spaceAfter=2),
        "metric_label": ParagraphStyle("metric_label", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.8, leading=10.5, textColor=GREEN_DARK, spaceAfter=2),
        "metric_note": ParagraphStyle("metric_note", parent=base["Normal"], fontName="Helvetica", fontSize=6.9, leading=9.4, textColor=MUTED),
        "table_head": ParagraphStyle("table_head", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.1, leading=9, textColor=WHITE),
        "table": ParagraphStyle("table", parent=base["Normal"], fontName="Helvetica", fontSize=7.1, leading=9.4, textColor=INK),
        "hash": ParagraphStyle("hash", parent=base["Code"], fontName="Courier", fontSize=6.2, leading=8.2, textColor=INK),
        "link": ParagraphStyle("link", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=GREEN_DARK),
    }


def _fa(value: Any, level: str = "body", *, color=None) -> RTLText:
    specs = {
        "cover_kicker": ("Vazirmatn-Bold", 8.8, 14, GREEN, 0, 7),
        "cover_title": ("Vazirmatn-Bold", 29, 41, WHITE, 0, 11),
        "cover_subtitle": ("Vazirmatn", 11.5, 18, colors.HexColor("#C5D6CE"), 0, 12),
        "cover_meta": ("Vazirmatn", 8.3, 13.5, colors.HexColor("#A8BCB2"), 0, 0),
        "eyebrow": ("Vazirmatn-Bold", 8.2, 12, GREEN_DARK, 0, 5),
        "h1": ("Vazirmatn-Bold", 22, 32, INK, 0, 10),
        "h2": ("Vazirmatn-Bold", 14, 21, INK, 7, 7),
        "h3": ("Vazirmatn-Bold", 10, 15, INK, 2, 4),
        "lead": ("Vazirmatn", 10.5, 17, colors.HexColor("#31463E"), 0, 10),
        "body": ("Vazirmatn", 8.7, 14, INK, 0, 6),
        "small": ("Vazirmatn", 7.4, 11.5, MUTED, 0, 0),
        "metric_label": ("Vazirmatn-Bold", 7.8, 11.5, GREEN_DARK, 0, 2),
        "metric_note": ("Vazirmatn", 6.9, 10, MUTED, 0, 0),
        "table_head": ("Vazirmatn-Bold", 7.1, 10, WHITE, 0, 0),
        "table": ("Vazirmatn", 7.1, 10, INK, 0, 0),
    }
    font, size, leading, default_color, before, after = specs[level]
    return RTLText(value, font=font, size=size, leading=leading, color=color or default_color, space_before=before, space_after=after)


def _ltr_dynamic(value: Any, style: ParagraphStyle, *, align=TA_RIGHT) -> Paragraph:
    local = ParagraphStyle(f"dynamic_{style.name}_{align}", parent=style, alignment=align)
    return Paragraph(_escape(value), local)


def _dynamic_fa(value: Any, fa_level: str, en_style: ParagraphStyle) -> Flowable:
    return _fa(value, fa_level) if _has_arabic(value) else _ltr_dynamic(value, en_style)


def _metric_card_en(st: dict[str, ParagraphStyle], value: str, label: str, note: str) -> Table:
    table = Table([[[Paragraph(_escape(value), st["metric_number"]), Paragraph(_escape(label), st["metric_label"]), Paragraph(_escape(note), st["metric_note"])]]], colWidths=[52 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WHITE), ("BOX", (0, 0), (-1, -1), 0.55, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table


def _metric_card_fa(st: dict[str, ParagraphStyle], value: str, label: str, note: str) -> Table:
    num_style = ParagraphStyle("fa_metric_number", parent=st["metric_number"], alignment=TA_RIGHT)
    table = Table([[[Paragraph(_escape(value), num_style), _fa(label, "metric_label"), _fa(note, "metric_note")]]], colWidths=[52 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), WHITE), ("BOX", (0, 0), (-1, -1), 0.55, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table


def _metric_grid(cards: list[Table]) -> Table:
    rows = [cards[index : index + 3] for index in range(0, len(cards), 3)]
    while rows and len(rows[-1]) < 3:
        rows[-1].append(Spacer(1, 1))
    table = Table(rows, colWidths=[(A4[0] - 32 * mm) / 3] * 3)
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table


def _callout_en(st: dict[str, ParagraphStyle], title: str, body: str, *, accent=GREEN_DARK, background=MINT) -> Table:
    title_style = ParagraphStyle("callout_title_en", parent=st["h3"], spaceBefore=0, spaceAfter=3)
    body_style = ParagraphStyle("callout_body_en", parent=st["body"], spaceAfter=0)
    table = Table([[[Paragraph(_escape(title), title_style), Paragraph(_escape(body), body_style)]]], colWidths=[A4[0] - 36 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), background), ("LINEBEFORE", (0, 0), (0, -1), 4, accent), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    return table


def _callout_fa(title: str, body: str, *, accent=GREEN_DARK, background=MINT) -> Table:
    table = Table([[[_fa(title, "h3"), _fa(body, "body")]]], colWidths=[A4[0] - 36 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), background), ("LINEAFTER", (0, 0), (0, -1), 4, accent), ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    return table


def _table(rows: list[list[Any]], widths: list[float], *, rtl: bool = False) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="RIGHT" if rtl else "LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE), ("GRID", (0, 0), (-1, -1), 0.35, LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "RIGHT" if rtl else "LEFT"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5)]))
    return table


def _bullets_en(st: dict[str, ParagraphStyle], items: Iterable[str]) -> list[Paragraph]:
    return [Paragraph(f'<font color="#158463">+</font>&nbsp;&nbsp;{_escape(item)}', st["body"]) for item in items]


def _bullets_fa(items: Iterable[str]) -> list[Table]:
    rows: list[Table] = []
    for item in items:
        line = Table([[_fa(item, "body"), Paragraph("+", ParagraphStyle("fa_plus", fontName="Helvetica-Bold", fontSize=9, textColor=GREEN_DARK, alignment=TA_RIGHT))]], colWidths=[A4[0] - 43 * mm, 5 * mm], hAlign="RIGHT")
        line.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        rows.append(line)
    return rows


def _heading_en(st: dict[str, ParagraphStyle], number: str, title: str, intro: str | None = None) -> list[Flowable]:
    output: list[Flowable] = [Paragraph(f"SECTION {number}", st["eyebrow"]), Paragraph(_escape(title), st["h1"])]
    if intro:
        output.append(Paragraph(_escape(intro), st["lead"]))
    return output


def _heading_fa(number: str, title: str, intro: str | None = None) -> list[Flowable]:
    output: list[Flowable] = [_fa(f"بخش {number}", "eyebrow"), _fa(title, "h1")]
    if intro:
        output.append(_fa(intro, "lead"))
    return output


def _paint_dark_background(canvas) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillAlpha(0.10)
    canvas.setFillColor(GREEN)
    canvas.circle(width - 12 * mm, height - 22 * mm, 60 * mm, fill=1, stroke=0)
    canvas.circle(width + 8 * mm, 28 * mm, 82 * mm, fill=1, stroke=0)
    canvas.setFillAlpha(1)
    canvas.setStrokeColor(colors.HexColor("#18382C"))
    canvas.setLineWidth(0.35)
    for offset in range(0, 240, 22):
        canvas.line(0, 15 * mm + offset, width, 5 * mm + offset)
    canvas.restoreState()


def _paint_synthetic_banner(canvas, text: str) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(AMBER)
    canvas.rect(0, height - 9 * mm, width, 9 * mm, fill=1, stroke=0)
    canvas.setFillColor(DARK)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawCentredString(width / 2, height - 5.8 * mm, text)
    canvas.restoreState()


def _paint_cover(canvas, doc, synthetic: bool) -> None:
    _paint_dark_background(canvas)
    if synthetic:
        _paint_synthetic_banner(canvas, SYNTHETIC_EN)
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#829C91"))
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(16 * mm, 10 * mm, "PERSIAN FIRST  |  ENGLISH SECOND  |  EVIDENCE REPORT")
    canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, "GENERIC MARKET ANALYSIS AUDIT")
    canvas.setTitle("Bilingual Market Analysis Audit Report - Persian First, English Second")
    canvas.setAuthor("Market Analysis Audit Report Generator")
    canvas.setSubject(DISCLAIMER_EN)
    canvas.setKeywords("market analysis audit, scenario outcome alignment, bilingual, Persian, English")
    canvas.restoreState()


def _paint_page(canvas, doc, synthetic: bool) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.line(16 * mm, height - 13 * mm, width - 16 * mm, height - 13 * mm)
    canvas.setFillColor(GREEN_DARK)
    canvas.setFont("Helvetica-Bold", 6.8)
    canvas.drawString(16 * mm, height - 10 * mm, "MARKET ANALYSIS AUDIT / FA + EN")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.8)
    canvas.drawRightString(width - 16 * mm, height - 10 * mm, "SCENARIO-OUTCOME EVIDENCE")
    if synthetic:
        canvas.setFillColor(AMBER_SOFT)
        canvas.rect(16 * mm, height - 19 * mm, width - 32 * mm, 4.5 * mm, fill=1, stroke=0)
        canvas.setFillColor(CORAL)
        canvas.setFont("Helvetica-Bold", 6.5)
        canvas.drawCentredString(width / 2, height - 17.4 * mm, SYNTHETIC_EN)
    canvas.setStrokeColor(LINE)
    canvas.line(16 * mm, 11 * mm, width - 16 * mm, 11 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.5)
    footer = "SYNTHETIC DEMO / FICTIONAL DATA" if synthetic else "Evidence report - not investment advice or certification"
    canvas.drawString(16 * mm, 7 * mm, footer)
    canvas.drawRightString(width - 16 * mm, 7 * mm, f"PAGE {doc.page:02d}")
    canvas.restoreState()


def _scope_metrics(data: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    return _mapping(data.get("scope")), _mapping(data.get("audit_summary")), _mapping(data.get("scenario_profile"))


def _fa_limitation(value: str) -> str:
    lower = value.lower()
    if "outside audit_scope_categories" in lower or "outside" in lower and "scope" in lower:
        return "ویدیوهای خارج از دامنه اعلام‌شده در دفتر منبع باقی می‌مانند اما وارد شاخص نمی‌شوند."
    if "liquidation" in lower or "etf" in lower or "macro" in lower:
        return "ورودی‌های زمینه‌ای مانند نقشه لیکوییدیشن، جریان ETF و توضیح کلان مستقل ممیزی نمی‌شوند."
    if "binance" in lower or "venue" in lower:
        return "داده یک بازار مرجع ممکن است در مرزهای دقیق با بازار دیگر تفاوت داشته باشد."
    if "yahoo" in lower or "proxy" in lower or "csv" in lower:
        return "ابزار یا پروکسی بین‌المللی فقط نگاشت مستند خود را پشتیبانی می‌کند و دقت آن محدود است."
    if "24-hour" in lower or "24 hour" in lower or "recent" in lower:
        return "پنجره نتیجه ناقص، شواهد ناکافی باقی می‌ماند و به نتیجه مطلوب یا نامطلوب تبدیل نمی‌شود."
    if "ai-assisted" in lower or "ground truth" in lower or "human review" in lower:
        return "استخراج و داوری هوش‌مصنوعی‌یار به بازبینی انسانی نیاز دارد و حقیقت عینی یا گواهی کیفیت نیست."
    return "محدودیت ثبت‌شده در داده منبع: " + value


METHODOLOGY_EN = [
    ("Collection", "Collect public source records within the declared date and category boundaries; retain exclusions in the ledger."),
    ("Transcript evidence", "Normalize available subtitles or transcripts and preserve source references and hashes. Missing evidence stays missing."),
    ("Claim extraction", "Identify falsifiable forward-looking claims while preserving conditions, levels, horizons, and invalidations."),
    ("Outcome evidence", "Map supported assets to documented market series and retain provider, interval, window completeness, and timestamps."),
    ("Deterministic filters", "Do not score context-only claims, unsupported assets, incomplete windows, or conditional scenarios whose trigger did not occur."),
    ("Scenario scoring", "Fully aligned = 1.0, partly aligned = 0.5, missed = 0.0. Other statuses do not enter the counted denominator."),
    ("Integrity", "Hashes show whether recorded files changed. They do not certify factual truth, analyst skill, or investment quality."),
]

METHODOLOGY_FA = [
    ("جمع‌آوری", "رکوردهای عمومی در مرز تاریخ و دسته اعلام‌شده جمع‌آوری می‌شوند و موارد خارج از دامنه در دفتر منبع باقی می‌مانند."),
    ("شواهد متن", "زیرنویس یا متن موجود نرمال می‌شود و ارجاع منبع و هش حفظ می‌شوند؛ شاهد مفقود، مفقود باقی می‌ماند."),
    ("استخراج ادعا", "ادعاهای آینده‌نگر و قابل ابطال همراه با شرط، سطح، افق و ابطال استخراج می‌شوند."),
    ("شواهد نتیجه", "دارایی پشتیبانی‌شده به سری بازار مستند نگاشت می‌شود و ارائه‌دهنده، فاصله، کامل‌بودن پنجره و زمان حفظ می‌شوند."),
    ("فیلتر قطعی", "زمینه آموزشی، دارایی پشتیبانی‌نشده، پنجره ناقص یا شرط فعال‌نشده وارد امتیاز نمی‌شود."),
    ("امتیاز سناریو", "هم‌راستایی کامل برابر 1، نسبی برابر 0.5 و عدم هم‌راستایی برابر صفر است؛ سایر وضعیت‌ها وارد مخرج نمی‌شوند."),
    ("یکپارچگی", "هش فقط تغییر فایل ثبت‌شده را نشان می‌دهد و حقیقت، مهارت تحلیل‌گر یا کیفیت سرمایه‌گذاری را گواهی نمی‌کند."),
]


def _build_farsi(data: Mapping[str, Any], st: dict[str, ParagraphStyle], synthetic: bool) -> list[Flowable]:
    scope, audit, profile = _scope_metrics(data)
    status = _text(data.get("status"), "unknown")
    date_range = _mapping(data.get("date_range"))
    channel = _mapping(data.get("channel"))
    outcome = _mapping(data.get("outcome_summary"))
    verification = _mapping(data.get("verification"))
    hashes = _mapping(data.get("tamper_evidence"))
    project = _text(data.get("project_name"), "Market Analysis Audit Lab")
    analyst = _text(data.get("analyst_name"), "نام تحلیل‌گر ثبت نشده است")
    story: list[Flowable] = []

    # Cover
    story.extend([Spacer(1, 14 * mm)])
    if synthetic:
        story.extend([_fa(SYNTHETIC_FA, "cover_kicker", color=AMBER), Spacer(1, 4 * mm)])
    story.extend([
        _fa("گزارش دو زبانه شواهد / فارسی سپس انگلیسی", "cover_kicker"),
        _fa("گزارش ممیزی تحلیل بازار", "cover_title"),
        _fa("مرور شفاف و داده‌محور ادعاهای آینده‌نگر در برابر شواهد بعدی بازار؛ با نمایش روشن دامنه، وضعیت، روش و محدودیت‌ها.", "cover_subtitle"),
        Spacer(1, 5 * mm),
        _callout_fa("اصل تفسیر", DISCLAIMER_FA, accent=CORAL, background=CORAL_SOFT),
        Spacer(1, 8 * mm),
        _fa("پروژه", "cover_kicker"),
        _dynamic_fa(project, "cover_meta", st["cover_meta"]),
        Spacer(1, 3 * mm),
        _fa("منبع تحلیل", "cover_kicker"),
        _dynamic_fa(analyst, "cover_meta", st["cover_meta"]),
        Spacer(1, 3 * mm),
        _fa(f"وضعیت: {_status_fa(status)}", "cover_meta"),
        _fa(f"بازه ثبت‌شده: {_text(date_range.get('start'), 'نامشخص')} تا {_text(date_range.get('end'), 'نامشخص')}", "cover_meta"),
        _fa(f"شناسه مجموعه: {_text(data.get('collection_id'), 'در دسترس نیست')}", "cover_meta"),
        PageBreak(),
    ])

    # Status, scope, and results
    story.extend(_heading_fa("01", "وضعیت، دامنه و نتیجه قابل گزارش", "این صفحه فقط داده موجود در payload را گزارش می‌کند و برای مرحله‌های در انتظار یا ناقص، نتیجه‌ای اختراع نمی‌کند."))
    status_cards = [
        _metric_card_fa(st, _fmt_count(scope.get("source_videos_found")), "ویدیوی منبع", "همه رکوردهای پیدا شده در بازه"),
        _metric_card_fa(st, _fmt_count(scope.get("videos_audited")), "ویدیوی داخل ممیزی", "ویدیوهای واردشده در دامنه اعلام‌شده"),
        _metric_card_fa(st, _fmt_count(audit.get("total_claims")), "ادعای ساختاریافته", "ادعاهای موجود در خروجی فعلی"),
    ]
    story.append(_metric_grid(status_cards))
    story.extend([Spacer(1, 2 * mm), _callout_fa("وضعیت اجرای فعلی", _status_fa(status), accent=AMBER if status != "audit_complete" else GREEN_DARK, background=AMBER_SOFT if status != "audit_complete" else MINT)])
    categories = _list(scope.get("categories"))
    if categories:
        story.extend([Spacer(1, 5 * mm), _fa("دامنه اعلام‌شده", "h2"), _fa("، ".join(_category_fa(item) for item in categories), "body")])
    metadata_rows = [
        [_fa("مقدار", "table_head"), _fa("فیلد", "table_head")],
        [_dynamic_fa(_text(date_range.get("start"), "نامشخص"), "table", st["table"]), _fa("شروع بازه", "table")],
        [_dynamic_fa(_text(date_range.get("end"), "نامشخص"), "table", st["table"]), _fa("پایان بازه", "table")],
        [_dynamic_fa(_text(channel.get("id"), "ثبت نشده"), "table", st["table"]), _fa("شناسه کانال", "table")],
        [_fa(_fmt_count(scope.get("out_of_scope_videos")), "table"), _fa("ویدیوی خارج از دامنه", "table")],
    ]
    story.extend([Spacer(1, 3 * mm), _table(metadata_rows, [112 * mm, 54 * mm], rtl=True), Spacer(1, 6 * mm)])
    counted = _int(audit.get("counted_claims"))
    if audit and counted > 0:
        result_cards = [
            _metric_card_fa(st, _fmt_int(counted), "سناریوی فعال و قابل‌بررسی", "فقط این سناریوها وارد مخرج نتیجه شده‌اند"),
            _metric_card_fa(st, _fmt_pct(audit.get("at_least_partial_percent")), "حداقل هم‌راستایی نسبی", "هم‌راستایی کامل به‌علاوه نسبی"),
            _metric_card_fa(st, _fmt_pct(audit.get("score")), "شاخص وزنی هم‌راستایی", "کامل 1، نسبی 0.5 و عدم هم‌راستایی صفر"),
        ]
        story.append(_metric_grid(result_cards))
        result_rows = [
            [_fa("تعداد", "table_head"), _fa("برچسب", "table_head")],
            [Paragraph(_fmt_int(audit.get("correct_count")), st["table"]), _fa("هم‌راستایی کامل", "table")],
            [Paragraph(_fmt_int(audit.get("partial_count")), st["table"]), _fa("هم‌راستایی نسبی", "table")],
            [Paragraph(_fmt_int(audit.get("incorrect_count")), st["table"]), _fa("عدم هم‌راستایی", "table")],
        ]
        story.extend([Spacer(1, 3 * mm), _table(result_rows, [45 * mm, 121 * mm], rtl=True)])
    else:
        story.append(_callout_fa("هنوز شاخصی وجود ندارد", "تا زمانی که سناریوهای فعال با شواهد کافی داوری نشوند، درصد یا شاخص هم‌راستایی گزارش نمی‌شود.", accent=BLUE, background=colors.HexColor("#E7F0F8")))
    story.extend([Spacer(1, 5 * mm), _callout_fa("این شاخص چه چیزی نیست", DISCLAIMER_FA, accent=CORAL, background=CORAL_SOFT), PageBreak()])

    # Evidence profile and method
    story.extend(_heading_fa("02", "پروفایل شواهد و روش", "ساختار سناریو، پوشش داده و قواعد داوری باید جدا از هر نتیجه نهایی دیده شوند."))
    if profile:
        cards = [
            _metric_card_fa(st, _fmt_pct(profile.get("explicit_condition_percent")), "شرط صریح", "سهم ادعاهای دارای شرط قابل آزمون"),
            _metric_card_fa(st, _fmt_pct(profile.get("level_claim_percent")), "سطح قیمت", "سهم ادعاهای دارای سطح عددی"),
            _metric_card_fa(st, _fmt_pct(profile.get("invalidation_video_percent")), "ابطال در سطح ویدیو", "سهم ویدیوهای دارای مفهوم ابطال"),
        ]
        story.append(_metric_grid(cards))
        for label, key, accent in [
            ("ادعاهای دارای شرط صریح", "explicit_condition_percent", GREEN_DARK),
            ("ادعاهای دارای سطح قیمت", "level_claim_percent", BLUE),
            ("ویدیوهای دارای دو مسیر", "both_directions_video_percent", AMBER),
        ]:
            story.append(ProgressBar(label, profile.get(key), rtl=True, accent=accent))
    else:
        story.append(_callout_fa("پروفایل ادعا در دسترس نیست", "این مرحله هنوز اجرا نشده یا payload فعلی این بخش را ندارد.", accent=BLUE, background=colors.HexColor("#E7F0F8")))
    story.extend([Spacer(1, 5 * mm), _fa("روش عملیاتی", "h2")])
    method_rows = [[_fa("قاعده", "table_head"), _fa("مرحله", "table_head")]]
    for label, body in METHODOLOGY_FA:
        method_rows.append([_fa(body, "table"), _fa(label, "table")])
    story.append(_table(method_rows, [131 * mm, 35 * mm], rtl=True))
    story.extend([Spacer(1, 6 * mm), _callout_fa("هوش مصنوعی کمک می‌کند؛ شاهد مرجع باقی می‌ماند", "استخراج و داوری هوش‌مصنوعی‌یار به بازبینی انسانی نیاز دارد. متن منبع و داده بازار بر خروجی مدل مقدم‌اند.")])
    story.append(PageBreak())

    # Market data, limitations, integrity
    story.extend(_heading_fa("03", "داده بازار، محدودیت‌ها و یکپارچگی", "وضوح داده، موارد محاسبه‌نشده و هش فایل‌ها مرز تفسیر گزارش را تعیین می‌کنند."))
    if outcome:
        providers = _list(outcome.get("providers"))
        story.append(_metric_grid([
            _metric_card_fa(st, _fmt_int(outcome.get("available_series")), "سری بازار", "سری‌های موجود در payload فعلی"),
            _metric_card_fa(st, _fmt_int(outcome.get("complete_claims")), "ادعای دارای پنجره کامل", "ادعاهایی با حداقل یک پنجره نتیجه کامل"),
            _metric_card_fa(st, _fmt_int(sum(_int(_mapping(item).get("row_count")) for item in providers)), "ردیف قیمت", "جمع ردیف‌های ارائه‌دهندگان ثبت‌شده"),
        ]))
        if providers:
            provider_rows = [[_fa("ردیف", "table_head"), _fa("سری", "table_head"), _fa("وضوح", "table_head"), _fa("ارائه‌دهنده", "table_head")]]
            for raw in providers[:8]:
                item = _mapping(raw)
                provider_rows.append([Paragraph(_fmt_int(item.get("row_count")), st["table"]), Paragraph(_fmt_int(item.get("series_count")), st["table"]), _dynamic_fa(_text(item.get("resolution"), "نامشخص"), "table", st["table"]), _dynamic_fa(_text(item.get("name"), "ثبت نشده"), "table", st["table"])])
            story.extend([Spacer(1, 4 * mm), _table(provider_rows, [28 * mm, 24 * mm, 34 * mm, 80 * mm], rtl=True)])
    else:
        story.append(_callout_fa("شواهد بازار هنوز در دسترس نیست", "نبود داده نتیجه به‌عنوان نتیجه مطلوب یا نامطلوب تفسیر نمی‌شود.", accent=BLUE, background=colors.HexColor("#E7F0F8")))
    limitations = [_text(item) for item in _list(data.get("limitations")) if _text(item)]
    if not limitations:
        limitations = [
            "AI-assisted extraction and scoring require human review and are not objective ground truth.",
            "Incomplete outcome windows remain insufficient evidence.",
            "Market-data providers or proxies may differ at exact boundary levels.",
        ]
    story.extend([Spacer(1, 6 * mm), _fa("محدودیت‌های ثبت‌شده", "h2"), *_bullets_fa(_fa_limitation(item) for item in limitations)])
    story.extend([Spacer(1, 5 * mm), _fa("یکپارچگی فایل", "h2")])
    hash_items = [
        ("مانیفست", hashes.get("manifest_sha256")),
        ("آرشیو", hashes.get("archive_sha256")),
        ("شواهد بازار", hashes.get("market_evidence_sha256")),
        ("نتیجه", hashes.get("outcome_sha256")),
    ]
    hash_rows = [[Paragraph("SHA-256", st["table_head"]), _fa("اثر", "table_head")]]
    for label, value in hash_items:
        if _text(value):
            hash_rows.append([Paragraph(_escape(value), st["hash"]), _fa(label, "table")])
    if len(hash_rows) > 1:
        story.append(_table(hash_rows, [117 * mm, 49 * mm], rtl=True))
    else:
        story.append(_fa("هش‌های اثر در payload فعلی موجود نیستند.", "body"))
    integrity_status = _text(verification.get("status"), _text(hashes.get("verification_status"), "در دسترس نیست"))
    story.extend([Spacer(1, 5 * mm), _callout_fa("وضعیت یکپارچگی فایل", f"وضعیت ثبت‌شده: {integrity_status}. این وضعیت فقط سازگاری فایل ثبت‌شده را نشان می‌دهد و صحت تحلیل یا مهارت شخص را گواهی نمی‌کند.", accent=AMBER, background=AMBER_SOFT)])
    if synthetic:
        story.extend([Spacer(1, 5 * mm), _callout_fa("نسخه نمایشی ساختگی", SYNTHETIC_FA, accent=CORAL, background=CORAL_SOFT)])
    story.extend([Spacer(1, 6 * mm), _fa("نتیجه مسئولانه", "h2"), _fa("این سند فقط وضعیت و شواهد ثبت‌شده در payload را خلاصه می‌کند. تصمیم مالی نیازمند قضاوت مستقل، مدیریت ریسک و بررسی منبع است.", "body")])
    return story


def _build_english(data: Mapping[str, Any], st: dict[str, ParagraphStyle], synthetic: bool) -> list[Flowable]:
    scope, audit, profile = _scope_metrics(data)
    status = _text(data.get("status"), "unknown")
    date_range = _mapping(data.get("date_range"))
    channel = _mapping(data.get("channel"))
    outcome = _mapping(data.get("outcome_summary"))
    verification = _mapping(data.get("verification"))
    hashes = _mapping(data.get("tamper_evidence"))
    project = _text(data.get("project_name"), "Market Analysis Audit Lab")
    analyst = _text(data.get("analyst_name"), "Source analyst not supplied")
    story: list[Flowable] = [PageBackground(synthetic), Spacer(1, 14 * mm)]

    if synthetic:
        story.extend([Paragraph(SYNTHETIC_EN, ParagraphStyle("synthetic_cover", parent=st["cover_kicker"], textColor=AMBER)), Spacer(1, 4 * mm)])
    story.extend([
        Paragraph("FULL EVIDENCE REPORT / ENGLISH EDITION", st["cover_kicker"]),
        Paragraph("Market Analysis<br/>Audit Report", st["cover_title"]),
        Paragraph("A neutral, data-driven review of forward-looking analysis claims against later market evidence, with explicit scope, status, methodology, and limitations.", st["cover_subtitle"]),
        Spacer(1, 5 * mm),
        _callout_en(st, "Interpretation rule", DISCLAIMER_EN, accent=CORAL, background=CORAL_SOFT),
        Spacer(1, 8 * mm),
        Paragraph("PROJECT", st["cover_kicker"]),
        Paragraph(_escape(project), st["cover_meta"]),
        Spacer(1, 3 * mm),
        Paragraph("ANALYSIS SOURCE", st["cover_kicker"]),
        Paragraph(_escape(analyst), st["cover_meta"]),
        Spacer(1, 3 * mm),
        Paragraph(f"Status: {_escape(_status_en(status))}", st["cover_meta"]),
        Paragraph(f"Recorded range: {_escape(date_range.get('start') or 'unknown')} to {_escape(date_range.get('end') or 'unknown')}", st["cover_meta"]),
        Paragraph(f"Collection ID: {_escape(data.get('collection_id') or 'not available')}", st["cover_meta"]),
        PageBreak(),
    ])

    story.extend(_heading_en(st, "01", "Status, scope, and reportable result", "This page reports only fields present in the payload. Waiting and partial stages do not receive an invented score."))
    story.append(_metric_grid([
        _metric_card_en(st, _fmt_count(scope.get("source_videos_found")), "SOURCE VIDEOS", "All records found in the declared window"),
        _metric_card_en(st, _fmt_count(scope.get("videos_audited")), "VIDEOS AUDITED", "Videos entering the declared audit scope"),
        _metric_card_en(st, _fmt_count(audit.get("total_claims")), "STRUCTURED CLAIMS", "Claims present in the current payload"),
    ]))
    story.extend([Spacer(1, 2 * mm), _callout_en(st, "Current run status", _status_en(status), accent=AMBER if status != "audit_complete" else GREEN_DARK, background=AMBER_SOFT if status != "audit_complete" else MINT)])
    categories = _list(scope.get("categories"))
    if categories:
        story.extend([Spacer(1, 5 * mm), Paragraph("Declared scope", st["h2"]), Paragraph(", ".join(_category_en(item) for item in categories), st["body"])])
    channel_id = _text(channel.get("id"), "Not recorded")
    metadata_rows = [
        [Paragraph("FIELD", st["table_head"]), Paragraph("VALUE", st["table_head"])],
        [Paragraph("Range start", st["table"]), Paragraph(_escape(date_range.get("start") or "Unknown"), st["table"])],
        [Paragraph("Range end", st["table"]), Paragraph(_escape(date_range.get("end") or "Unknown"), st["table"])],
        [Paragraph("Channel ID", st["table"]), Paragraph(_escape(channel_id), st["table"])],
        [Paragraph("Out-of-scope videos", st["table"]), Paragraph(_fmt_count(scope.get("out_of_scope_videos")), st["table"])],
    ]
    story.extend([Spacer(1, 3 * mm), _table(metadata_rows, [54 * mm, 112 * mm]), Spacer(1, 6 * mm)])
    counted = _int(audit.get("counted_claims"))
    if audit and counted > 0:
        story.append(_metric_grid([
            _metric_card_en(st, _fmt_int(counted), "ACTIVATED, VERIFIABLE", "Only these scenarios enter the result denominator"),
            _metric_card_en(st, _fmt_pct(audit.get("at_least_partial_percent")), "AT LEAST PARTLY ALIGNED", "Fully aligned plus partly aligned scenarios"),
            _metric_card_en(st, _fmt_pct(audit.get("score")), "WEIGHTED ALIGNMENT INDEX", "Full = 1, partial = 0.5, missed = 0"),
        ]))
        result_rows = [
            [Paragraph("LABEL", st["table_head"]), Paragraph("COUNT", st["table_head"])],
            [Paragraph("Fully aligned", st["table"]), Paragraph(_fmt_int(audit.get("correct_count")), st["table"])],
            [Paragraph("Partly aligned", st["table"]), Paragraph(_fmt_int(audit.get("partial_count")), st["table"])],
            [Paragraph("Missed", st["table"]), Paragraph(_fmt_int(audit.get("incorrect_count")), st["table"])],
        ]
        story.extend([Spacer(1, 3 * mm), _table(result_rows, [121 * mm, 45 * mm])])
    else:
        story.append(_callout_en(st, "No alignment index yet", "No percentage or alignment index is reported until activated scenarios have sufficient evidence and a recorded judgment.", accent=BLUE, background=colors.HexColor("#E7F0F8")))
    story.extend([Spacer(1, 5 * mm), _callout_en(st, "What the index is not", DISCLAIMER_EN, accent=CORAL, background=CORAL_SOFT), PageBreak()])

    story.extend(_heading_en(st, "02", "Evidence profile and methodology", "Scenario structure, data coverage, and judgment rules should remain separate from any aggregate result."))
    if profile:
        story.append(_metric_grid([
            _metric_card_en(st, _fmt_pct(profile.get("explicit_condition_percent")), "EXPLICIT CONDITIONS", "Claims containing a testable condition"),
            _metric_card_en(st, _fmt_pct(profile.get("level_claim_percent")), "PRICE LEVELS", "Claims containing at least one numeric level"),
            _metric_card_en(st, _fmt_pct(profile.get("invalidation_video_percent")), "VIDEO INVALIDATIONS", "Videos containing an invalidation concept"),
        ]))
        for label, key, accent in [
            ("Claims with explicit conditions", "explicit_condition_percent", GREEN_DARK),
            ("Claims with named price levels", "level_claim_percent", BLUE),
            ("Videos with both directional paths", "both_directions_video_percent", AMBER),
        ]:
            story.append(ProgressBar(label, profile.get(key), accent=accent))
    else:
        story.append(_callout_en(st, "Claim profile unavailable", "This stage has not run yet or the current payload does not include it.", accent=BLUE, background=colors.HexColor("#E7F0F8")))
    story.extend([Spacer(1, 5 * mm), Paragraph("Operational methodology", st["h2"])])
    method_rows = [[Paragraph("STAGE", st["table_head"]), Paragraph("OPERATIONAL RULE", st["table_head"])]]
    for label, body in METHODOLOGY_EN:
        method_rows.append([Paragraph(_escape(label), st["table"]), Paragraph(_escape(body), st["table"])])
    story.append(_table(method_rows, [35 * mm, 131 * mm]))
    story.extend([Spacer(1, 6 * mm), _callout_en(st, "AI assists; source evidence remains authoritative", "AI-assisted extraction and judgment require human review. Canonical source text and market data take precedence over model output.")])
    story.append(PageBreak())

    story.extend(_heading_en(st, "03", "Market data, limitations, and integrity", "Data resolution, non-counted outcomes, and file hashes define the limits of interpretation."))
    if outcome:
        providers = _list(outcome.get("providers"))
        story.append(_metric_grid([
            _metric_card_en(st, _fmt_int(outcome.get("available_series")), "MARKET SERIES", "Series available in the current payload"),
            _metric_card_en(st, _fmt_int(outcome.get("complete_claims")), "COMPLETE-WINDOW CLAIMS", "Claims with at least one complete outcome window"),
            _metric_card_en(st, _fmt_int(sum(_int(_mapping(item).get("row_count")) for item in providers)), "PRICE ROWS", "Rows across recorded providers"),
        ]))
        if providers:
            provider_rows = [[Paragraph("PROVIDER", st["table_head"]), Paragraph("RESOLUTION", st["table_head"]), Paragraph("SERIES", st["table_head"]), Paragraph("ROWS", st["table_head"])]]
            for raw in providers[:8]:
                item = _mapping(raw)
                provider_rows.append([Paragraph(_escape(item.get("name") or "Not recorded"), st["table"]), Paragraph(_escape(item.get("resolution") or "Unknown"), st["table"]), Paragraph(_fmt_int(item.get("series_count")), st["table"]), Paragraph(_fmt_int(item.get("row_count")), st["table"])])
            story.extend([Spacer(1, 4 * mm), _table(provider_rows, [80 * mm, 34 * mm, 24 * mm, 28 * mm])])
    else:
        story.append(_callout_en(st, "Market evidence unavailable", "Missing outcome data is not converted into a favorable or unfavorable result.", accent=BLUE, background=colors.HexColor("#E7F0F8")))
    limitations = [_text(item) for item in _list(data.get("limitations")) if _text(item)]
    if not limitations:
        limitations = [
            "AI-assisted extraction and scoring require human review and are not objective ground truth.",
            "Incomplete outcome windows remain insufficient evidence.",
            "Market-data providers or proxies may differ at exact boundary levels.",
        ]
    story.extend([Spacer(1, 6 * mm), Paragraph("Recorded limitations", st["h2"]), *_bullets_en(st, limitations)])
    story.extend([Spacer(1, 5 * mm), Paragraph("File integrity", st["h2"])])
    hash_items = [
        ("Source manifest", hashes.get("manifest_sha256")),
        ("Collection archive", hashes.get("archive_sha256")),
        ("Market evidence", hashes.get("market_evidence_sha256")),
        ("Outcome snapshot", hashes.get("outcome_sha256")),
    ]
    hash_rows = [[Paragraph("ARTIFACT", st["table_head"]), Paragraph("SHA-256", st["table_head"])]]
    for label, value in hash_items:
        if _text(value):
            hash_rows.append([Paragraph(label, st["table"]), Paragraph(_escape(value), st["hash"])])
    if len(hash_rows) > 1:
        story.append(_table(hash_rows, [49 * mm, 117 * mm]))
    else:
        story.append(Paragraph("Artifact hashes are not available in the current payload.", st["body"]))
    integrity_status = _text(verification.get("status"), _text(hashes.get("verification_status"), "not available"))
    story.extend([Spacer(1, 5 * mm), _callout_en(st, "File-integrity status", f"Recorded status: {integrity_status}. This checks recorded file consistency only; it does not certify analytical truth, personal skill, or investment quality.", accent=AMBER, background=AMBER_SOFT)])
    if synthetic:
        story.extend([Spacer(1, 5 * mm), _callout_en(st, "Synthetic demonstration", SYNTHETIC_EN, accent=CORAL, background=CORAL_SOFT)])
    story.extend([Spacer(1, 6 * mm), Paragraph("Responsible conclusion", st["h2"]), Paragraph("This document summarizes only the state and evidence recorded in the payload. Financial decisions require independent judgment, source review, and risk management.", st["body"])])
    return story


def generate_report(workspace: Path, output: Path | None = None) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve()
    input_path = workspace / "reports" / "dashboard_data.json"
    output_path = Path(output).expanduser().resolve() if output else workspace / "reports" / "audit-report.pdf"
    if not input_path.is_file():
        raise FileNotFoundError(f"dashboard payload not found: {input_path}")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("dashboard_data.json must contain a JSON object")
    synthetic = _detect_synthetic(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    st = _styles()

    temp_root = Path(tempfile.gettempdir()) / "market-analysis-audit-lab" / "pdfs"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audit-report-fonts-", dir=temp_root) as temp_name:
        _register_fonts(Path(temp_name))
        document = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=22 * mm if synthetic else 17 * mm,
            bottomMargin=15 * mm,
            title="Bilingual Market Analysis Audit Report - Persian First, English Second",
            author="Market Analysis Audit Report Generator",
            subject=DISCLAIMER_EN,
            creator="Generic audit PDF generator / ReportLab",
        )
        story = _build_farsi(data, st, synthetic)
        story.extend([PageBreak(), *_build_english(data, st, synthetic)])
        document.build(
            story,
            onFirstPage=lambda canvas, doc: _paint_cover(canvas, doc, synthetic),
            onLaterPages=lambda canvas, doc: _paint_page(canvas, doc, synthetic),
            canvasmaker=InvariantCanvas,
        )

    return {
        "input": str(input_path),
        "output": str(output_path),
        "status": _text(data.get("status"), "unknown"),
        "synthetic_demo": synthetic,
        "language_order": ["fa", "en"],
        "size_bytes": output_path.stat().st_size,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Persian-first bilingual audit report PDF")
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE, help="Workspace containing reports/dashboard_data.json")
    parser.add_argument("--output", type=Path, default=None, help="Override output path (default: <workspace>/reports/audit-report.pdf)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(generate_report(args.workspace, args.output), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
