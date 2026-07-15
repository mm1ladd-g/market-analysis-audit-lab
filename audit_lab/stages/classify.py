from __future__ import annotations

import json
import re
from pathlib import Path

from audit_lab.utils.validation import category_id, video_id


DEFAULT_RULES: dict[str, list[str]] = {
    "crypto": [
        "btc", "bitcoin", "crypto", "ethereum", "eth", "solana", "بیتکوین",
        "بیت کوین", "بیت‌کوین", "کریپتو", "رمزارز", "اتریوم", "سولانا",
    ],
    "global_markets": [
        "xau", "xauusd", "gold", "silver", "oil", "forex", "nasdaq", "s&p",
        "sp500", "dxy", "us10y", "vix", "international market", "global market",
        "بازار جهانی", "بازارهای جهانی", "اونس", "انس", "طلا", "نقره", "نفت",
        "فارکس", "نزدک", "داوجونز",
    ],
    "local_markets": [
        "domestic market", "local market", "بازار داخلی", "بورس", "شاخص کل",
        "تومان", "بازار تهران", "دلار آزاد",
    ],
}


def _search_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u200c", " ").casefold()).strip()


def _contains(text: str, keyword: str) -> bool:
    normalized_text = _search_text(text)
    normalized_keyword = _search_text(keyword)
    if not normalized_keyword:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)",
        normalized_text,
        flags=re.UNICODE,
    ) is not None


def load_category_config(path: Path | None) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Load optional per-video overrides and keyword rules.

    File format: ``{"video_overrides": {"id": "category"},
    "keyword_rules": {"category": ["term"]}}``. User rules are evaluated before
    the built-in broad market defaults.
    """
    if path is None:
        return {}, {key: list(values) for key, values in DEFAULT_RULES.items()}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Category configuration must be a JSON object")
    raw_overrides = payload.get("video_overrides", {})
    raw_rules = payload.get("keyword_rules", {})
    if not isinstance(raw_overrides, dict) or not isinstance(raw_rules, dict):
        raise ValueError("video_overrides and keyword_rules must be JSON objects")

    overrides: dict[str, str] = {}
    for key, value in raw_overrides.items():
        overrides[video_id(key)] = category_id(value)

    custom: dict[str, list[str]] = {}
    for raw_category, raw_terms in raw_rules.items():
        category = category_id(raw_category)
        if not isinstance(raw_terms, list) or not raw_terms:
            raise ValueError(f"Keyword rules for {category!r} must be a non-empty array")
        terms = [str(term).strip() for term in raw_terms]
        if any(not term or len(term) > 128 for term in terms):
            raise ValueError(f"Keyword rules for {category!r} contain an empty or overlong term")
        custom[category] = terms
    return overrides, {**custom, **{key: value for key, value in DEFAULT_RULES.items() if key not in custom}}


def guess_category(
    video_id: str,
    title: str,
    description: str = "",
    *,
    video_overrides: dict[str, str] | None = None,
    keyword_rules: dict[str, list[str]] | None = None,
) -> str:
    overrides = video_overrides or {}
    if video_id in overrides:
        return overrides[video_id]
    rules = keyword_rules or DEFAULT_RULES
    for category, keywords in rules.items():
        if any(_contains(title, keyword) for keyword in keywords):
            return category
    for category, keywords in rules.items():
        if any(_contains(description, keyword) for keyword in keywords):
            return category
    return "unknown"
