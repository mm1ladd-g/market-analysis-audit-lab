from __future__ import annotations

import csv
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import yfinance as yf

from audit_lab import __version__
from audit_lab.settings import Settings
from audit_lab.utils.hash import sha256_file, sha256_json
from audit_lab.utils.jsonio import write_json_atomic

OUTCOME_SCHEMA_VERSION = "2.0.0"

# Crypto is fetched from Binance's official public archive at one-minute
# resolution. Global instruments still use explicit Yahoo symbols/proxies until
# an exchange or broker credential is configured; the distinction is retained
# in every output artifact and in the public report.
ASSET_SOURCES = {
    "BTC": ("BTC-USD", "Binance BTC/USDT spot used as the BTC/USD outcome benchmark"),
    "BTCUSD": ("BTC-USD", "Binance BTC/USDT spot used as the BTC/USD outcome benchmark"),
    "BTC-USD": ("BTC-USD", "Binance BTC/USDT spot used as the BTC/USD outcome benchmark"),
    "ETH": ("ETH-USD", "Binance ETH/USDT spot used as the ETH/USD outcome benchmark"),
    "ETHUSD": ("ETH-USD", "Binance ETH/USDT spot used as the ETH/USD outcome benchmark"),
    "ETH-USD": ("ETH-USD", "Binance ETH/USDT spot used as the ETH/USD outcome benchmark"),
    "ETHBTC": ("ETH-BTC", "Binance ETH/BTC spot"),
    "ETH-BTC": ("ETH-BTC", "Binance ETH/BTC spot"),
    "SOL": ("SOL-USD", "Binance SOL/USDT spot used as the SOL/USD outcome benchmark"),
    "SOLUSD": ("SOL-USD", "Binance SOL/USDT spot used as the SOL/USD outcome benchmark"),
    "SOL-USD": ("SOL-USD", "Binance SOL/USDT spot used as the SOL/USD outcome benchmark"),
    "XAUUSD": ("GC=F", "COMEX gold futures proxy for XAUUSD"),
    "GOLD": ("GC=F", "COMEX gold futures"),
    "SILVER": ("SI=F", "COMEX silver futures"),
    "XAGUSD": ("SI=F", "COMEX silver futures proxy for XAGUSD"),
    "WTI": ("CL=F", "NYMEX WTI crude futures"),
    "OIL": ("CL=F", "NYMEX WTI crude futures proxy"),
    "BRENT": ("BZ=F", "ICE Brent crude futures"),
    "DXY": ("DX-Y.NYB", "ICE US Dollar Index"),
    "NASDAQ": ("^IXIC", "Nasdaq Composite index"),
    "NASDAQ100": ("^NDX", "Nasdaq-100 index"),
    "NDX": ("^NDX", "Nasdaq-100 index"),
    "DOW": ("^DJI", "Dow Jones Industrial Average index"),
    "DJI": ("^DJI", "Dow Jones Industrial Average index"),
    "DJIA": ("^DJI", "Dow Jones Industrial Average index"),
    "DOWJONES": ("^DJI", "Dow Jones Industrial Average index"),
    "SPX": ("^GSPC", "S&P 500 index"),
    "S&P500": ("^GSPC", "S&P 500 index"),
    "VIX": ("^VIX", "CBOE Volatility Index"),
    "US10Y": ("^TNX", "CBOE 10-year Treasury yield index"),
    "UST10Y": ("^TNX", "CBOE 10-year Treasury yield index"),
    "EURUSD": ("EURUSD=X", "EUR/USD Yahoo FX feed"),
    "GBPUSD": ("GBPUSD=X", "GBP/USD Yahoo FX feed"),
    "USDJPY": ("JPY=X", "USD/JPY Yahoo FX feed"),
    "IBIT": ("IBIT", "iShares Bitcoin Trust ETF"),
}

BINANCE_SERIES = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "SOL-USD": "SOLUSDT",
    "ETH-BTC": "ETHBTC",
}

NON_PRICE_CONTEXT = {
    "BTC-ETF",
    "BTCSPOTETFS",
    "MACRO",
}

UNSUPPORTED_EXACT = {
    "BTC.D": "TradingView's BTC dominance index is not an exchange-traded price series.",
    "USDT.D": "TradingView's USDT dominance index is not an exchange-traded price series.",
    "TOTAL": "TradingView's TOTAL crypto-cap index requires a separately licensed or reconstructed series.",
    "TOTAL2": "TradingView's TOTAL2 crypto-cap index requires a separately licensed or reconstructed series.",
    "TOTAL3": "TradingView's TOTAL3 crypto-cap index requires a separately licensed or reconstructed series.",
    "CRYPTO_TOTAL": "The requested aggregate crypto-cap series is not configured as exact evidence.",
    "ALTCOINS": "No single exchange-traded price series represents all altcoins.",
    "CRYPTO": "No single exchange-traded price series represents the whole crypto market.",
    "CRYPTOMARKET": "No single exchange-traded price series represents the whole crypto market.",
    "BTCSPOTETFS": "ETF-flow claims are contextual inputs and outside this price-outcome audit.",
    "BTC-ETF": "ETF-flow claims are contextual inputs and outside this price-outcome audit.",
    "MACRO": "Macro-release facts are contextual inputs and outside this price-outcome audit.",
}

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

SERIES_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9^=._-]{0,63}")
BINANCE_SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{5,20}")
CSV_METADATA_SCHEMA_VERSION = "1.0"
YFINANCE_COVERAGE_POLICY = {
    "session_type": "non_continuous",
    "cadence_seconds": 3600,
    "maximum_gap_seconds": 72 * 3600,
    "boundary_tolerance_seconds": 72 * 3600,
    "minimum_bars_per_24h": 4,
    "declaration_source": "application yfinance hourly convenience-proxy policy",
}


def _validate_series_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("series_key must be a string")
    series_key = value
    if not SERIES_KEY_PATTERN.fullmatch(series_key) or series_key in {".", ".."}:
        raise ValueError(
            "series_key must be 1-64 ASCII characters and may contain only "
            "letters, digits, ^, =, dot, underscore, or hyphen"
        )
    return series_key


def _validate_binance_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Binance symbol must be a string")
    symbol = value
    if not BINANCE_SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Binance symbols must be 5-20 uppercase ASCII letters or digits")
    return symbol


def _series_file_stem(series_key: str) -> str:
    """Return a deterministic filename stem after validating the logical key."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", _validate_series_key(series_key))


def _ensure_path_within(root: Path, candidate: Path, *, label: str) -> Path:
    """Resolve a path and reject traversal or a symlink escape from ``root``."""
    root_resolved = root.expanduser().resolve()
    candidate_resolved = candidate.expanduser().resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its configured root") from exc
    return candidate_resolved


def _workspace_write_path(workspace_dir: Path, candidate: Path, *, label: str) -> Path:
    return _ensure_path_within(workspace_dir, candidate, label=label)


def _workspace_relative_path(workspace_dir: Path, candidate: Path) -> str:
    return str(_workspace_write_path(workspace_dir, candidate, label="artifact path").relative_to(
        workspace_dir.expanduser().resolve()
    ))


def _parse_aware_timestamp(value: object, *, field: str = "timestamp_utc") -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} is empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _validate_ohlc_rows(rows: list[dict], *, source: str) -> tuple[list[dict], dict]:
    """Validate and canonicalize a time-ordered OHLC series.

    Invalid rows are rejected rather than silently dropped or repaired. This is
    important because sorting, de-duplicating, or coercing bad OHLC data can
    change whether a claimed level appears to have been touched.
    """
    validated: list[dict] = []
    previous_timestamp: datetime | None = None
    seen: set[datetime] = set()
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{source} row {index} is not an object")
        timestamp = _parse_aware_timestamp(raw.get("timestamp_utc"))
        if timestamp in seen:
            raise ValueError(f"{source} contains a duplicate timestamp at row {index}")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError(f"{source} timestamps must be strictly increasing")
        seen.add(timestamp)
        previous_timestamp = timestamp

        values = {name: _clean_number(raw.get(name)) for name in ("open", "high", "low", "close")}
        if any(value is None for value in values.values()):
            raise ValueError(f"{source} row {index} has missing or non-finite OHLC values")
        open_price = values["open"]
        high = values["high"]
        low = values["low"]
        close = values["close"]
        assert open_price is not None and high is not None and low is not None and close is not None
        if high < low or high < max(open_price, close) or low > min(open_price, close):
            raise ValueError(f"{source} row {index} violates OHLC ordering")

        normalized = {
            "timestamp_utc": timestamp.isoformat(),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
        }
        volume = _clean_number(raw.get("volume"))
        if raw.get("volume") is not None and volume is None:
            raise ValueError(f"{source} row {index} has invalid volume")
        if volume is not None and volume < 0:
            raise ValueError(f"{source} row {index} has negative volume")
        normalized["volume"] = volume
        if raw.get("trade_count") is not None:
            try:
                trade_count = int(raw["trade_count"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{source} row {index} has invalid trade_count") from exc
            if trade_count < 0:
                raise ValueError(f"{source} row {index} has negative trade_count")
            normalized["trade_count"] = trade_count
        validated.append(normalized)

    validation = {
        "ohlc_ordering": "passed",
        "timestamps": "strictly_increasing_unique_utc",
        "row_count": len(validated),
        "first_timestamp_utc": validated[0]["timestamp_utc"] if validated else None,
        "last_timestamp_utc": validated[-1]["timestamp_utc"] if validated else None,
    }
    return validated, validation


def normalize_asset(asset: str) -> str:
    return (
        asset.upper()
        .replace(" ", "")
        .replace("/", "")
        .replace("–", "-")
        .replace("—", "-")
    )


def load_asset_registry(settings: Settings) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    sources = dict(ASSET_SOURCES)
    binance = dict(BINANCE_SERIES)
    if settings.asset_map_file is None:
        return sources, binance
    if settings.asset_map_file.stat().st_size > 1_000_000:
        raise ValueError("ASSET_MAP_FILE exceeds 1 MB")
    payload = json.loads(
        settings.asset_map_file.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if not isinstance(payload, dict):
        raise ValueError("ASSET_MAP_FILE must contain a JSON object")
    configured_sources = payload.get("asset_sources", {})
    configured_binance = payload.get("binance_series", {})
    if not isinstance(configured_sources, dict) or not isinstance(configured_binance, dict):
        raise ValueError("asset_sources and binance_series must be JSON objects")
    for alias, item in configured_sources.items():
        if not isinstance(item, dict) or not item.get("series_key"):
            raise ValueError(f"Invalid asset_sources entry for {alias}")
        alias_text = str(alias)
        if not alias_text.strip() or len(alias_text) > 128 or any(ord(char) < 32 for char in alias_text):
            raise ValueError("Asset aliases must be non-empty printable strings of at most 128 characters")
        series_key = _validate_series_key(item["series_key"])
        sources[normalize_asset(alias_text)] = (
            series_key,
            str(item.get("note") or "Operator-configured market series"),
        )
    for key, symbol in configured_binance.items():
        binance[_validate_series_key(key)] = _validate_binance_symbol(symbol)
    for series_key, symbol in binance.items():
        _validate_series_key(series_key)
        _validate_binance_symbol(symbol)
    return sources, binance


def resolve_asset(asset: str, sources: dict[str, tuple[str, str]] | None = None) -> tuple[str, str] | None:
    return (sources or ASSET_SOURCES).get(normalize_asset(asset))


def _clean_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 8) if math.isfinite(number) else None


def _normalize_history(frame: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    if frame.empty:
        return rows
    working = frame.copy()
    if isinstance(working.columns, pd.MultiIndex):
        working.columns = working.columns.get_level_values(0)
    index = pd.to_datetime(working.index, utc=True)
    for timestamp, (_, row) in zip(index, working.iterrows(), strict=True):
        values = {
            name.lower(): _clean_number(row.get(name))
            for name in ["Open", "High", "Low", "Close", "Volume"]
        }
        if all(values[name] is None for name in ["open", "high", "low", "close"]):
            continue
        rows.append({"timestamp_utc": timestamp.isoformat(), **values})
    return rows


def default_history_fetcher(ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
    return yf.Ticker(ticker).history(
        start=start,
        end=end,
        interval="1h",
        auto_adjust=False,
        actions=False,
        raise_errors=True,
    )


def _request_bytes(
    url: str, *, attempts: int = 4, timeout: int = 45, maximum_bytes: int = 128 * 1024 * 1024
) -> bytes:
    parsed_url = urllib.parse.urlsplit(url)
    allowed_hosts = {"api.binance.com", "data.binance.vision"}
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname not in allowed_hosts
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError("Market-data download URL is not an approved HTTPS endpoint")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(  # noqa: S310 - scheme and host are allowlisted above
                url,
                headers={
                    "User-Agent": (
                        f"MarketAnalysisAuditLab/{__version__} (+reproducible-research)"
                    )
                },
            )
            with urllib.request.urlopen(  # noqa: S310 - scheme and host are allowlisted above
                request, timeout=timeout
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > maximum_bytes:
                    raise ValueError("Market-data response exceeds the configured safety limit")
                payload = response.read(maximum_bytes + 1)
                if len(payload) > maximum_bytes:
                    raise ValueError("Market-data response exceeds the configured safety limit")
                return payload
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 8))
    assert last_error is not None
    raise last_error


def _timestamp_seconds(raw: str | int) -> float:
    value = int(raw)
    if value >= 10**14:
        return value / 1_000_000
    if value >= 10**11:
        return value / 1_000
    return float(value)


def _parse_binance_csv(payload: bytes) -> list[dict]:
    rows: list[dict] = []
    for line_number, row in enumerate(
        csv.reader(io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")), start=1
    ):
        if not row:
            continue
        if not row[0].lstrip("-").isdigit():
            if line_number == 1 and row[0].strip().casefold() in {"open_time", "opentime"}:
                continue
            raise ValueError(f"Binance archive contains a non-numeric timestamp at row {line_number}")
        if len(row) < 9:
            raise ValueError("Binance archive contains a truncated kline row")
        rows.append({
            "timestamp_utc": datetime.fromtimestamp(_timestamp_seconds(row[0]), UTC).isoformat(),
            "open": _clean_number(row[1]),
            "high": _clean_number(row[2]),
            "low": _clean_number(row[3]),
            "close": _clean_number(row[4]),
            "volume": _clean_number(row[5]),
            "trade_count": int(row[8]),
        })
    validated, _ = _validate_ohlc_rows(rows, source="Binance archive")
    return validated


def _parse_binance_api_rows(payload: list) -> tuple[list[dict], dict]:
    raw_rows = []
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, list) or len(row) < 9:
            raise ValueError(f"Binance REST API contains a truncated kline at row {index}")
        raw_rows.append({
            "timestamp_utc": datetime.fromtimestamp(_timestamp_seconds(row[0]), UTC).isoformat(),
            "open": _clean_number(row[1]),
            "high": _clean_number(row[2]),
            "low": _clean_number(row[3]),
            "close": _clean_number(row[4]),
            "volume": _clean_number(row[5]),
            "trade_count": row[8],
        })
    return _validate_ohlc_rows(raw_rows, source="Binance REST API")


def _binance_archive_day(symbol: str, day: date, raw_dir: Path) -> tuple[list[dict], dict]:
    symbol = _validate_binance_symbol(symbol)
    filename = f"{symbol}-1m-{day.isoformat()}.zip"
    base = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m"
    checksum_url = f"{base}/{filename}.CHECKSUM"
    archive_url = f"{base}/{filename}"
    symbol_dir = _ensure_path_within(raw_dir, raw_dir / symbol, label="Binance raw directory")
    symbol_dir.mkdir(parents=True, exist_ok=True)
    checksum_path = _ensure_path_within(
        raw_dir, symbol_dir / f"{filename}.CHECKSUM", label="Binance checksum path"
    )
    archive_path = _ensure_path_within(
        raw_dir, symbol_dir / filename, label="Binance archive path"
    )

    checksum_text = _request_bytes(checksum_url, maximum_bytes=4096).decode("utf-8").strip()
    expected_sha256 = checksum_text.split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError(f"Invalid Binance checksum response for {filename}")
    checksum_path.write_text(checksum_text + "\n", encoding="utf-8")
    if not archive_path.exists() or sha256_file(archive_path) != expected_sha256:
        archive_path.write_bytes(_request_bytes(archive_url))
    actual_sha256 = sha256_file(archive_path)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"Binance checksum mismatch for {filename}")
    with zipfile.ZipFile(archive_path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"Corrupt Binance archive member: {bad_member}")
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"Unexpected Binance archive layout for {filename}")
        member = archive.getinfo(members[0])
        if member.file_size > 64 * 1024 * 1024:
            raise ValueError(f"Binance archive member is unexpectedly large for {filename}")
        rows = _parse_binance_csv(archive.read(member))
    return rows, {
        "date": day.isoformat(),
        "source": "Binance public daily archive",
        "url": archive_url,
        "relative_path": str(archive_path),
        "sha256": actual_sha256,
        "upstream_sha256": expected_sha256,
        "checksum_verified": True,
        "rows": len(rows),
    }


def _binance_api_day(symbol: str, day: date, raw_dir: Path, now: datetime) -> tuple[list[dict], dict]:
    symbol = _validate_binance_symbol(symbol)
    day_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    day_end = min(day_start + timedelta(days=1), now)
    cursor_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000) - 1
    all_rows: list[list] = []
    while cursor_ms <= end_ms:
        params = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": "1m",
            "startTime": cursor_ms,
            "endTime": end_ms,
            "limit": 1000,
        })
        payload = json.loads(
            _request_bytes(
                f"https://api.binance.com/api/v3/klines?{params}", maximum_bytes=4 * 1024 * 1024
            ).decode("utf-8")
        )
        if not isinstance(payload, list):
            raise ValueError("Binance REST API returned an unexpected response shape")
        if not payload:
            break
        all_rows.extend(payload)
        cursor_ms = int(payload[-1][0]) + 60_000
        if len(payload) < 1000:
            break
        time.sleep(0.05)
    rows, validation = _parse_binance_api_rows(all_rows)
    symbol_dir = _ensure_path_within(raw_dir, raw_dir / symbol, label="Binance raw directory")
    symbol_dir.mkdir(parents=True, exist_ok=True)
    path = _ensure_path_within(
        raw_dir,
        symbol_dir / f"{symbol}-1m-{day.isoformat()}.live.json",
        label="Binance live-data path",
    )
    write_json_atomic(path, all_rows)
    return rows, {
        "date": day.isoformat(),
        "source": "Binance public REST API",
        "url": "https://api.binance.com/api/v3/klines",
        "relative_path": str(path),
        "sha256": sha256_file(path),
        "upstream_sha256": None,
        "checksum_verified": False,
        "rows": len(rows),
        "validation": validation,
    }


def fetch_binance_series(
    series_key: str,
    symbol: str,
    start: datetime,
    end: datetime,
    now: datetime,
    market_dir: Path,
    workspace_dir: Path,
) -> dict:
    series_key = _validate_series_key(series_key)
    symbol = _validate_binance_symbol(symbol)
    market_dir = _workspace_write_path(workspace_dir, market_dir, label="market data directory")
    rows: list[dict] = []
    source_files: list[dict] = []
    raw_dir = _workspace_write_path(
        workspace_dir, market_dir / "raw" / "binance" / "spot", label="Binance raw directory"
    )
    last_day = min((end - timedelta(microseconds=1)).date(), now.date())
    day = start.date()
    while day <= last_day:
        try:
            if day < now.date():
                day_rows, source = _binance_archive_day(symbol, day, raw_dir)
            else:
                day_rows, source = _binance_api_day(symbol, day, raw_dir, now)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                day_rows, source = _binance_api_day(symbol, day, raw_dir, now)
            else:
                raise
        rows.extend(day_rows)
        source["relative_path"] = _workspace_relative_path(workspace_dir, Path(source["relative_path"]))
        source_files.append(source)
        day += timedelta(days=1)
    rows = [
        row for row in rows
        if start <= datetime.fromisoformat(row["timestamp_utc"]) < end
    ]
    rows.sort(key=lambda row: row["timestamp_utc"])
    rows, validation = _validate_ohlc_rows(rows, source=f"Binance {symbol} normalized series")
    if not rows:
        raise ValueError(f"Binance returned no {symbol} rows inside the requested audit range")
    normalized_path = _workspace_write_path(
        workspace_dir,
        market_dir / f"{_series_file_stem(series_key)}.1m.json",
        label="normalized Binance series",
    )
    coverage_policy = {
        "session_type": "continuous",
        "cadence_seconds": 60,
        "maximum_gap_seconds": 60,
        "boundary_tolerance_seconds": 60,
        "minimum_bars_per_24h": 1440,
        "declaration_source": "Binance 1m endpoint/archive contract",
    }
    payload = {
        "provider": "Binance public market data",
        "venue": "Binance spot",
        "symbol": symbol,
        "series_key": series_key,
        "interval": "1m",
        "timezone": "UTC",
        "timestamp_semantics": "bar_open",
        "retrieved_at_utc": now.isoformat(),
        "requested_start_utc": start.isoformat(),
        "requested_end_utc": end.isoformat(),
        "coverage_policy": coverage_policy,
        "validation": validation,
        "raw_files": source_files,
        "rows": rows,
    }
    write_json_atomic(normalized_path, payload)
    return {
        "status": "available",
        "provider": payload["provider"],
        "venue": payload["venue"],
        "symbol": symbol,
        "interval": "1m",
        "timezone": "UTC",
        "timestamp_semantics": "bar_open",
        "source_file": _workspace_relative_path(workspace_dir, normalized_path),
        "source_sha256": sha256_file(normalized_path),
        "raw_file_count": len(source_files),
        "upstream_checksums_verified": sum(item["checksum_verified"] for item in source_files),
        "row_count": len(rows),
        "coverage_policy": coverage_policy,
        "validation": validation,
        "rows": rows,
    }


def _level_numbers(levels: list[str] | None) -> list[float]:
    parsed: list[float] = []
    for raw in levels or []:
        text = str(raw).translate(PERSIAN_DIGITS).replace(",", "").replace("٬", "")
        lowered = text.casefold()
        non_price_markers = [
            "%", "٪", "percent", "percentage", "درصد", "hour", "day", "week", "month", "year",
            "ساعت", "روز", "هفته", "ماه", "سال",
        ]
        if any(marker in lowered for marker in non_price_markers):
            continue
        for match in re.findall(r"-?\d+(?:\.\d+)?", text):
            value = float(match)
            if math.isfinite(value) and value not in parsed:
                parsed.append(value)
    return parsed


def _first_timestamp(selected: list[tuple[datetime, dict]], predicate: Callable[[dict], bool]) -> str | None:
    for timestamp, row in selected:
        if predicate(row):
            return timestamp.isoformat()
    return None


def _validate_coverage_policy(policy: object) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("a declared coverage policy is required")
    session_type = policy.get("session_type")
    if session_type not in {"continuous", "non_continuous"}:
        raise ValueError("session_type must be continuous or non_continuous")

    normalized = {"session_type": session_type}
    for name in ("cadence_seconds", "maximum_gap_seconds", "boundary_tolerance_seconds"):
        value = policy.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{name} must be a positive finite number")
        normalized[name] = float(value)
    cadence = normalized["cadence_seconds"]
    if normalized["maximum_gap_seconds"] < cadence:
        raise ValueError("maximum_gap_seconds cannot be shorter than cadence_seconds")
    if normalized["boundary_tolerance_seconds"] < cadence:
        raise ValueError("boundary_tolerance_seconds cannot be shorter than cadence_seconds")

    minimum = policy.get("minimum_bars_per_24h")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 2:
        raise ValueError("minimum_bars_per_24h must be an integer of at least 2")
    maximum_possible = math.ceil(86400 / cadence)
    if minimum > maximum_possible:
        raise ValueError("minimum_bars_per_24h exceeds the declared cadence")
    minimum_defensible = max(2, math.ceil(maximum_possible * 0.10))
    if session_type == "non_continuous" and minimum < minimum_defensible:
        raise ValueError(
            "non-continuous minimum_bars_per_24h must cover at least 10% of the declared cadence"
        )
    if session_type == "continuous" and minimum != maximum_possible:
        raise ValueError(
            "continuous minimum_bars_per_24h must equal the full count implied by cadence_seconds"
        )
    normalized["minimum_bars_per_24h"] = minimum

    # A continuous series cannot declare its way around missing bars. Its
    # maximum gap and boundary tolerance are tied to the declared cadence, and
    # the expected bar count is derived from that cadence below.
    tolerance = max(0.001, cadence * 0.01)
    if session_type == "continuous":
        if normalized["maximum_gap_seconds"] > cadence + tolerance:
            raise ValueError("continuous maximum_gap_seconds must equal the declared cadence")
        if normalized["boundary_tolerance_seconds"] > cadence + tolerance:
            raise ValueError("continuous boundary_tolerance_seconds must equal the declared cadence")

    declaration_source = policy.get("declaration_source")
    if declaration_source:
        normalized["declaration_source"] = str(declaration_source)[:240]
    return normalized


def _assess_window_coverage(
    selected: list[tuple[datetime, dict]],
    horizon: datetime,
    hours: int,
    policy: dict,
) -> dict:
    cadence = policy["cadence_seconds"]
    maximum_gap = policy["maximum_gap_seconds"]
    boundary_tolerance = policy["boundary_tolerance_seconds"]
    tolerance = max(0.001, cadence * 0.01)
    gaps = [
        (selected[index][0] - selected[index - 1][0]).total_seconds()
        for index in range(1, len(selected))
    ]
    maximum_observed_gap = max(gaps) if gaps else None
    irregular_gaps = [
        gap
        for gap in gaps
        if gap < cadence - tolerance
        or abs((gap / cadence) - round(gap / cadence)) > (tolerance / cadence)
    ]
    excessive_gaps = [gap for gap in gaps if gap > maximum_gap + tolerance]
    boundary_lag = max((horizon - selected[-1][0]).total_seconds(), 0.0)

    if policy["session_type"] == "continuous":
        minimum_bars = math.ceil(hours * 3600 / cadence)
    else:
        minimum_bars = math.ceil(policy["minimum_bars_per_24h"] * hours / 24)

    reasons: list[str] = []
    if len(selected) < minimum_bars:
        reasons.append("bar_count_below_declared_minimum")
    if irregular_gaps:
        reasons.append("timestamps_do_not_follow_declared_cadence")
    if excessive_gaps:
        reasons.append("gap_exceeds_declared_session_maximum")
    if boundary_lag > boundary_tolerance + tolerance:
        reasons.append("series_does_not_reach_window_boundary")
    complete = not reasons
    return {
        "complete": complete,
        "session_type": policy["session_type"],
        "cadence_seconds": cadence,
        "minimum_required_bars": minimum_bars,
        "maximum_allowed_gap_seconds": maximum_gap,
        "maximum_observed_gap_seconds": maximum_observed_gap,
        "boundary_tolerance_seconds": boundary_tolerance,
        "boundary_lag_seconds": boundary_lag,
        "reasons": reasons,
        "note": (
            "Coverage passed the declared cadence, session-gap, bar-count, and boundary checks."
            if complete
            else "Coverage failed: " + ", ".join(reasons) + "."
        ),
    }


def _window(
    rows: list[dict],
    anchor: datetime,
    hours: int,
    as_of: datetime,
    levels: list[str] | None = None,
    *,
    continuous: bool = False,
    coverage_policy: dict | None = None,
) -> dict:
    # ``continuous`` remains as a compatibility hint for callers, but no
    # cadence is inferred from observed rows. A declared policy is mandatory.
    try:
        policy = _validate_coverage_policy(coverage_policy)
    except ValueError as exc:
        return {
            "hours": hours,
            "status": "coverage_policy_missing" if coverage_policy is None else "coverage_policy_invalid",
            "complete": False,
            "coverage_complete": False,
            "coverage_note": str(exc),
            "continuous_hint": continuous,
        }
    if continuous and policy["session_type"] != "continuous":
        return {
            "hours": hours,
            "status": "coverage_policy_invalid",
            "complete": False,
            "coverage_complete": False,
            "coverage_note": "continuous source hint conflicts with the declared session_type",
        }
    try:
        validated_rows, validation = _validate_ohlc_rows(rows, source="market series")
    except ValueError as exc:
        return {
            "hours": hours,
            "status": "invalid_market_series",
            "complete": False,
            "coverage_complete": False,
            "coverage_note": str(exc),
        }
    parsed = [(_parse_aware_timestamp(row["timestamp_utc"]), row) for row in validated_rows]
    future = [(ts, row) for ts, row in parsed if ts >= anchor]
    if not future:
        return {"hours": hours, "status": "no_bar_after_publication", "complete": False}
    entry_ts, entry_row = future[0]
    if (entry_ts - anchor).total_seconds() > policy["maximum_gap_seconds"]:
        return {"hours": hours, "status": "next_tradable_bar_too_late", "complete": False}
    horizon = entry_ts + timedelta(hours=hours)
    selected = [(ts, row) for ts, row in future if entry_ts <= ts < horizon]
    elapsed = as_of >= horizon
    if not selected:
        return {"hours": hours, "status": "no_bars_in_window", "complete": False}
    opens = [row["open"] for _, row in selected if row.get("open") is not None]
    highs = [(ts, row["high"]) for ts, row in selected if row.get("high") is not None]
    lows = [(ts, row["low"]) for ts, row in selected if row.get("low") is not None]
    closes = [row["close"] for _, row in selected if row.get("close") is not None]
    if not opens or not highs or not lows or not closes:
        return {"hours": hours, "status": "incomplete_ohlc", "complete": False}
    entry = opens[0]
    highest_ts, highest = max(highs, key=lambda item: item[1])
    lowest_ts, lowest = min(lows, key=lambda item: item[1])
    close = closes[-1]
    level_events = []
    for level in _level_numbers(levels):
        level_events.append({
            "level": level,
            "first_touch_utc": _first_timestamp(
                selected,
                lambda row, value=level: row.get("low") is not None
                and row.get("high") is not None
                and row["low"] <= value <= row["high"],
            ),
            "first_close_above_utc": _first_timestamp(
                selected, lambda row, value=level: row.get("close") is not None and row["close"] > value
            ),
            "first_close_below_utc": _first_timestamp(
                selected, lambda row, value=level: row.get("close") is not None and row["close"] < value
            ),
        })
    coverage = _assess_window_coverage(selected, horizon, hours, policy)
    coverage_complete = coverage["complete"]
    coverage_note = coverage["note"]
    complete = elapsed and coverage_complete
    return {
        "hours": hours,
        "status": "complete" if complete else "source_coverage_gap" if elapsed else "window_not_elapsed",
        "complete": complete,
        "wall_clock_elapsed": elapsed,
        "coverage_complete": coverage_complete,
        "coverage_note": coverage_note,
        "coverage": coverage,
        "series_validation": validation,
        "publication_timestamp_utc": anchor.isoformat(),
        "entry_timestamp_utc": entry_ts.isoformat(),
        "window_end_utc": horizon.isoformat(),
        "last_bar_timestamp_utc": selected[-1][0].isoformat(),
        "bar_count": len(selected),
        "open": entry,
        "high": highest,
        "high_timestamp_utc": highest_ts.isoformat(),
        "low": lowest,
        "low_timestamp_utc": lowest_ts.isoformat(),
        "close": close,
        "return_pct": round((close / entry - 1) * 100, 6) if entry else None,
        "max_up_pct": round((highest / entry - 1) * 100, 6) if entry else None,
        "max_down_pct": round((lowest / entry - 1) * 100, 6) if entry else None,
        "level_events": level_events,
    }


def build_claim_outcome(
    claim: dict,
    video: dict,
    series: dict[str, dict],
    as_of: datetime,
    asset_sources: dict[str, tuple[str, str]] | None = None,
) -> dict:
    if video.get("published_at_source") == "date_noon_fallback":
        return {
            "claim_id": claim["claim_id"],
            "video_id": claim["video_id"],
            "category": claim.get("category"),
            "published_at_utc": video.get("published_at_utc"),
            "published_at_source": video.get("published_at_source"),
            "assets": [{
                "asset": asset,
                "status": "insufficient_timestamp_precision",
                "reason": (
                    "The source supplied only an upload date; intraday outcome alignment requires "
                    "a precise publication timestamp."
                ),
            } for asset in claim.get("assets", [])],
            "status": "insufficient_timestamp_precision",
        }
    anchor = datetime.fromisoformat(video["published_at_utc"])
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    assets = []
    for asset in claim.get("assets", []):
        resolved = resolve_asset(asset, asset_sources)
        normalized = normalize_asset(asset)
        if resolved is None:
            status = "out_of_scope_non_price" if normalized in NON_PRICE_CONTEXT else "unsupported_asset"
            assets.append({
                "asset": asset,
                "status": status,
                "reason": UNSUPPORTED_EXACT.get(
                    normalized, "No exact market-data mapping is configured for this asset."
                ),
            })
            continue
        series_key, proxy_note = resolved
        source = series.get(series_key)
        if not source or source.get("status") != "available":
            assets.append({
                "asset": asset,
                "series_key": series_key,
                "proxy_note": proxy_note,
                "status": "data_unavailable",
                "reason": (source or {}).get("error", "Market series was not available."),
            })
            continue
        assets.append({
            "asset": asset,
            "series_key": series_key,
            "provider": source.get("provider"),
            "venue": source.get("venue"),
            "symbol": source.get("symbol", series_key),
            "interval": source.get("interval"),
            "timezone": source.get("timezone", "UTC"),
            "timestamp_semantics": source.get("timestamp_semantics", "bar_open"),
            "coverage_policy": source.get("coverage_policy"),
            "license": source.get("license"),
            "proxy_note": proxy_note,
            "status": "available",
            "source_file": source["source_file"],
            "source_sha256": source["source_sha256"],
            "window_24h": _window(
                source["rows"], anchor, 24, as_of, claim.get("levels"),
                continuous=source.get("provider") == "Binance public market data",
                coverage_policy=source.get("coverage_policy"),
            ),
            "window_48h": _window(
                source["rows"], anchor, 48, as_of, claim.get("levels"),
                continuous=source.get("provider") == "Binance public market data",
                coverage_policy=source.get("coverage_policy"),
            ),
        })
    return {
        "claim_id": claim["claim_id"],
        "video_id": claim["video_id"],
        "category": claim.get("category"),
        "published_at_utc": video["published_at_utc"],
        "published_at_source": video.get("published_at_source"),
        "assets": assets,
        "status": "no_asset" if not claim.get("assets") else "evaluated_for_price_outcome",
    }


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_csv_sidecar(path: Path, series_key: str) -> dict:
    if not path.is_file():
        raise ValueError(f"CSV metadata sidecar not found: {path.name}")
    if path.stat().st_size > 1_000_000:
        raise ValueError("CSV metadata sidecar exceeds 1 MB")
    try:
        metadata = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except json.JSONDecodeError as exc:
        raise ValueError("CSV metadata sidecar is not valid JSON") from exc
    if not isinstance(metadata, dict):
        raise ValueError("CSV metadata sidecar must contain a JSON object")
    if metadata.get("schema_version") != CSV_METADATA_SCHEMA_VERSION:
        raise ValueError(f"CSV metadata schema_version must be {CSV_METADATA_SCHEMA_VERSION}")
    if _validate_series_key(metadata.get("series_key")) != series_key:
        raise ValueError("CSV metadata series_key does not match the configured series")

    normalized: dict = {
        "schema_version": CSV_METADATA_SCHEMA_VERSION,
        "series_key": series_key,
    }
    for name in ("symbol", "venue", "timezone", "interval"):
        value = metadata.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError(f"CSV metadata {name} must be a non-empty string of at most 128 characters")
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"CSV metadata {name} contains control characters")
        normalized[name] = value.strip()
    try:
        ZoneInfo(normalized["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ValueError("CSV metadata timezone must be a valid IANA timezone") from exc

    timestamp_semantics = metadata.get("timestamp_semantics")
    if timestamp_semantics not in {"bar_open", "bar_close"}:
        raise ValueError("CSV metadata timestamp_semantics must be bar_open or bar_close")
    normalized["timestamp_semantics"] = timestamp_semantics

    session = metadata.get("session")
    if not isinstance(session, dict):
        raise ValueError("CSV metadata session must be an object")
    policy = _validate_coverage_policy({
        "session_type": session.get("type"),
        "cadence_seconds": metadata.get("cadence_seconds"),
        "maximum_gap_seconds": session.get("maximum_gap_seconds"),
        "boundary_tolerance_seconds": session.get("boundary_tolerance_seconds"),
        "minimum_bars_per_24h": session.get("minimum_bars_per_24h"),
        "declaration_source": "operator CSV metadata sidecar",
    })
    normalized["cadence_seconds"] = policy["cadence_seconds"]
    normalized["session"] = {
        "type": policy["session_type"],
        "maximum_gap_seconds": policy["maximum_gap_seconds"],
        "boundary_tolerance_seconds": policy["boundary_tolerance_seconds"],
        "minimum_bars_per_24h": policy["minimum_bars_per_24h"],
    }
    normalized["coverage_policy"] = policy

    license_metadata = metadata.get("license")
    if not isinstance(license_metadata, dict):
        raise ValueError("CSV metadata license must be an object")
    license_name = license_metadata.get("name")
    redistribution = license_metadata.get("redistribution")
    if not isinstance(license_name, str) or not license_name.strip() or len(license_name) > 240:
        raise ValueError("CSV metadata license.name is required")
    if any(ord(char) < 32 for char in license_name):
        raise ValueError("CSV metadata license.name contains control characters")
    if redistribution not in {"none", "derived_only", "raw_allowed"}:
        raise ValueError("CSV metadata license.redistribution must be none, derived_only, or raw_allowed")
    normalized["license"] = {
        "name": license_name.strip(),
        "redistribution": redistribution,
    }
    if license_metadata.get("source_url"):
        source_url = str(license_metadata["source_url"])
        if len(source_url) > 2048 or any(ord(char) < 32 for char in source_url):
            raise ValueError("CSV metadata license.source_url is invalid")
        parsed_url = urllib.parse.urlparse(source_url)
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError("CSV metadata license.source_url must be an HTTP(S) URL")
        normalized["license"]["source_url"] = source_url
    return normalized


def fetch_csv_series(
    series_key: str,
    start: datetime,
    end: datetime,
    now: datetime,
    market_dir: Path,
    workspace_dir: Path,
    csv_dir: Path,
) -> dict:
    """Load operator-licensed OHLC data from a deterministic CSV adapter."""
    try:
        series_key = _validate_series_key(series_key)
        safe_name = _series_file_stem(series_key)
        csv_root = csv_dir.expanduser().resolve()
        source_path = _ensure_path_within(csv_root, csv_root / f"{safe_name}.csv", label="CSV source")
        metadata_path = _ensure_path_within(
            csv_root, csv_root / f"{safe_name}.metadata.json", label="CSV metadata sidecar"
        )
    except ValueError as exc:
        return {"status": "unavailable", "error": str(exc)}
    if not source_path.is_file():
        return {"status": "unavailable", "error": f"CSV source not found: {source_path.name}"}
    try:
        metadata = _load_csv_sidecar(metadata_path, series_key)
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            if len(fieldnames) != len(set(fieldnames)):
                raise ValueError("CSV contains duplicate column names")
            required = {"timestamp_utc", "open", "high", "low", "close"}
            missing = sorted(required - set(fieldnames))
            if missing:
                raise ValueError("CSV is missing columns: " + ", ".join(missing))
            raw_rows = []
            for record in reader:
                if None in record:
                    raise ValueError("CSV row has more fields than the declared header")
                raw_rows.append({
                    "timestamp_utc": record.get("timestamp_utc"),
                    "open": record.get("open"),
                    "high": record.get("high"),
                    "low": record.get("low"),
                    "close": record.get("close"),
                    "volume": (record.get("volume") or None),
                })
        validated_rows, validation = _validate_ohlc_rows(raw_rows, source=source_path.name)
        input_timestamp_semantics = metadata["timestamp_semantics"]
        if input_timestamp_semantics == "bar_close":
            cadence = timedelta(seconds=metadata["coverage_policy"]["cadence_seconds"])
            shifted_rows = [
                {
                    **row,
                    "timestamp_utc": (_parse_aware_timestamp(row["timestamp_utc"]) - cadence).isoformat(),
                }
                for row in validated_rows
            ]
            validated_rows, validation = _validate_ohlc_rows(
                shifted_rows, source=f"{source_path.name} normalized to bar-open timestamps"
            )
            validation["timestamp_normalization"] = "bar_close_to_bar_open"
        else:
            validation["timestamp_normalization"] = "not_required"
        rows = [
            row for row in validated_rows
            if start <= _parse_aware_timestamp(row["timestamp_utc"]) < end
        ]
        normalized_path = _workspace_write_path(
            workspace_dir,
            market_dir / f"{safe_name}.csv-normalized.json",
            label="normalized CSV series",
        )
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "error": str(exc)}
    payload = {
        "provider": "Operator-provided CSV",
        "venue": metadata["venue"],
        "symbol": metadata["symbol"],
        "series_key": series_key,
        "interval": metadata["interval"],
        "timezone": metadata["timezone"],
        "timestamp_semantics": "bar_open",
        "input_timestamp_semantics": input_timestamp_semantics,
        "session": metadata["session"],
        "coverage_policy": metadata["coverage_policy"],
        "license": metadata["license"],
        "retrieved_at_utc": now.isoformat(),
        "input_file": source_path.name,
        "input_sha256": sha256_file(source_path),
        "metadata_file": metadata_path.name,
        "metadata_sha256": sha256_file(metadata_path),
        "validation": validation,
        "rows": rows,
    }
    write_json_atomic(normalized_path, payload)
    return {
        "status": "available" if rows else "unavailable",
        "provider": payload["provider"],
        "venue": payload["venue"],
        "symbol": payload["symbol"],
        "interval": payload["interval"],
        "timezone": payload["timezone"],
        "timestamp_semantics": payload["timestamp_semantics"],
        "input_timestamp_semantics": payload["input_timestamp_semantics"],
        "session": payload["session"],
        "coverage_policy": payload["coverage_policy"],
        "license": payload["license"],
        "source_file": _workspace_relative_path(workspace_dir, normalized_path),
        "source_sha256": sha256_file(normalized_path),
        "raw_file_count": 1,
        "upstream_checksums_verified": 0,
        "row_count": len(rows),
        "validation": validation,
        "rows": rows,
        **({"error": "CSV contains no rows inside the audit window"} if not rows else {}),
    }


def fetch_market_outcomes(
    settings: Settings,
    *,
    history_fetcher: Callable[[str, datetime, datetime], pd.DataFrame] = default_history_fetcher,
    as_of: datetime | None = None,
) -> Path:
    manifest_path = settings.pack_dir / "manifest.json"
    claims_path = settings.claims_dir / "claims.jsonl"
    extraction_path = settings.claims_dir / "extraction_run.json"
    if not manifest_path.exists() or not claims_path.exists() or not extraction_path.exists():
        raise SystemExit("Manifest and complete claim extraction are required before outcomes.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    all_claims = [
        json.loads(line)
        for line in claims_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    scope = set(settings.audit_scope_categories)
    claims = [claim for claim in all_claims if claim.get("category") in scope]
    collection_id = manifest["collection_id"]
    if extraction.get("collection_id") != collection_id or extraction.get("status") != "complete":
        raise SystemExit("Claim artifacts do not belong to the current collection.")

    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    start = datetime.combine(settings.start_date, datetime.min.time(), tzinfo=UTC) - timedelta(days=1)
    end_limit = min(settings.end_date + timedelta(days=3), now.date()) + timedelta(days=1)
    end = datetime.combine(end_limit, datetime.min.time(), tzinfo=UTC)
    outcomes_dir = _workspace_write_path(
        settings.workspace_dir, settings.outcomes_dir, label="outcomes directory"
    )
    outcomes_dir.mkdir(parents=True, exist_ok=True)
    market_dir = _workspace_write_path(
        settings.workspace_dir, outcomes_dir / "market_data", label="market data directory"
    )
    market_dir.mkdir(parents=True, exist_ok=True)

    asset_sources, binance_series = load_asset_registry(settings)
    resolved = {
        resolve_asset(asset, asset_sources)[0]
        for claim in claims
        for asset in claim.get("assets", [])
        if resolve_asset(asset, asset_sources) is not None
    }
    series: dict[str, dict] = {}
    crypto_jobs = {key: binance_series[key] for key in resolved if key in binance_series}
    if crypto_jobs:
        with ThreadPoolExecutor(
            max_workers=min(4, len(crypto_jobs)), thread_name_prefix="binance-archive"
        ) as executor:
            futures = {
                executor.submit(
                    fetch_binance_series,
                    key,
                    symbol,
                    start,
                    end,
                    now,
                    market_dir,
                    settings.workspace_dir,
                ): key
                for key, symbol in crypto_jobs.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    series[key] = future.result()
                except Exception as exc:
                    series[key] = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}

    for ticker in sorted(resolved - set(crypto_jobs)):
        ticker = _validate_series_key(ticker)
        if settings.international_market_provider == "csv":
            if settings.market_csv_dir is None:
                series[ticker] = {"status": "unavailable", "error": "MARKET_CSV_DIR is not configured"}
            else:
                series[ticker] = fetch_csv_series(
                    ticker, start, end, now, market_dir, settings.workspace_dir, settings.market_csv_dir
                )
            continue
        last_error = None
        for attempt in range(1, 4):
            try:
                frame = history_fetcher(ticker, start, end)
                rows = _normalize_history(frame)
                if not rows:
                    raise ValueError("Provider returned no hourly OHLC rows")
                rows, validation = _validate_ohlc_rows(rows, source=f"yfinance {ticker}")
                safe_ticker = _series_file_stem(ticker)
                source_path = _workspace_write_path(
                    settings.workspace_dir,
                    market_dir / f"{safe_ticker}.hourly.json",
                    label="normalized yfinance series",
                )
                coverage_policy = _validate_coverage_policy(YFINANCE_COVERAGE_POLICY)
                payload = {
                    "provider": "Yahoo Finance via yfinance",
                    "provider_library_version": yf.__version__,
                    "venue": "Yahoo aggregated feed",
                    "ticker": ticker,
                    "interval": "1h",
                    "timezone": "UTC",
                    "timestamp_semantics": "bar_open",
                    "retrieved_at_utc": now.isoformat(),
                    "requested_start_utc": start.isoformat(),
                    "requested_end_utc": end.isoformat(),
                    "provider_attempt": attempt,
                    "coverage_policy": coverage_policy,
                    "validation": validation,
                    "rows": rows,
                }
                write_json_atomic(source_path, payload)
                series[ticker] = {
                    "status": "available",
                    "provider": payload["provider"],
                    "venue": payload["venue"],
                    "symbol": ticker,
                    "interval": "1h",
                    "timezone": "UTC",
                    "timestamp_semantics": "bar_open",
                    "provider_attempts": attempt,
                    "source_file": _workspace_relative_path(settings.workspace_dir, source_path),
                    "source_sha256": sha256_file(source_path),
                    "row_count": len(rows),
                    "coverage_policy": coverage_policy,
                    "validation": validation,
                    "rows": rows,
                }
                break
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
        else:
            assert last_error is not None
            series[ticker] = {
                "status": "unavailable",
                "provider_attempts": 3,
                "error": f"{type(last_error).__name__}: {last_error}",
            }

    videos = {
        video["video_id"]: video
        for video in manifest.get("videos", [])
        if video.get("category") in scope
    }
    outcomes = [
        build_claim_outcome(claim, videos[claim["video_id"]], series, now, asset_sources)
        for claim in claims
    ]
    public_series = {
        key: {name: value for name, value in item.items() if name != "rows"}
        for key, item in series.items()
    }
    output = {
        "schema_version": OUTCOME_SCHEMA_VERSION,
        "collection_id": collection_id,
        "created_at_utc": now.isoformat(),
        "audit_scope_categories": list(settings.audit_scope_categories),
        "price_outcome_only": settings.price_outcome_only,
        "provider": (
            "Binance public 1-minute archives for crypto; operator-provided CSV for other markets"
            if settings.international_market_provider == "csv"
            else (
                "Binance public 1-minute archives for crypto; explicit Yahoo hourly proxies "
                "for global markets"
            )
        ),
        "providers": [
            {
                "name": "Binance public market data",
                "scope": "BTC, ETH, SOL and ETH/BTC spot outcomes",
                "resolution": "1 minute",
                "integrity": "Official SHA-256 checksum verified for completed daily archives",
            },
            ({
                "name": "Operator-provided CSV",
                "scope": "Configured international-market series",
                "resolution": "Declared in source documentation",
                "integrity": "Input and normalized output are locally SHA-256 hashed",
            } if settings.international_market_provider == "csv" else {
                "name": "Yahoo Finance via yfinance",
                "scope": "Convenience proxies for international instruments",
                "resolution": "1 hour",
                "integrity": "Locally hashed after retrieval; explicit proxy labels retained",
            }),
        ],
        "methodology": {
            "entry_rule": "first tradable provider bar at or after the YouTube publication timestamp",
            "windows": [24, 48],
            "incomplete_windows_are_scored": False,
            "ordered_level_evidence": "first touch and first close above/below each extracted numeric level",
            "price_scope_policy": (
                "context inputs such as liquidation, ETF-flow and macro facts are not "
                "independently scored"
            ),
            "category_scope_policy": (
                "Only categories listed in AUDIT_SCOPE_CATEGORIES enter outcome evaluation"
            ),
        },
        "series": public_series,
        "claims": outcomes,
    }
    output["market_evidence_snapshot_sha256"] = sha256_json({
        "collection_id": collection_id,
        "scope": output["audit_scope_categories"],
        "series": public_series,
        "claims": outcomes,
    })
    output["outcome_snapshot_sha256"] = sha256_json(output)
    out_path = _workspace_write_path(
        settings.workspace_dir, outcomes_dir / "claim_outcomes.json", label="outcome snapshot"
    )
    write_json_atomic(out_path, output)
    return out_path
