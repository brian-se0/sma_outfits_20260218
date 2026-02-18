from __future__ import annotations

import hashlib
from datetime import time
from typing import Iterable

import pandas as pd

SUPPORTED_TIMEFRAMES = (
    "1m",
    "2m",
    "3m",
    "5m",
    "10m",
    "15m",
    "20m",
    "30m",
    "1h",
    "2h",
    "4h",
    "1D",
    "1W",
    "1M",
    "1Q",
)

TIMEFRAME_TO_PANDAS_RULE = {
    "1m": "1min",
    "2m": "2min",
    "3m": "3min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "20m": "20min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1D": "1D",
    "1W": "W-FRI",
    "1M": "ME",
    "1Q": "QE",
}

ALPACA_NATIVE_TIMEFRAMES = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "1D": "1Day",
}


def stable_id(*parts: str) -> str:
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def ensure_utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def normalize_timeframe(value: str) -> str:
    candidate = value.strip()
    if candidate not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe '{candidate}'. Supported values: {SUPPORTED_TIMEFRAMES}"
        )
    return candidate


def timeframe_to_pandas_rule(value: str) -> str:
    timeframe = normalize_timeframe(value)
    return TIMEFRAME_TO_PANDAS_RULE[timeframe]


def parse_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def is_crypto_symbol(symbol: str) -> bool:
    return "/" in symbol


def is_regular_session(
    ts: pd.Timestamp,
    timezone: str = "America/New_York",
) -> bool:
    local = ensure_utc_timestamp(ts).tz_convert(timezone)
    if local.weekday() >= 5:
        return False
    local_time = local.time()
    return time(9, 30) <= local_time <= time(16, 0)


def apply_regular_session_filter(
    frame: pd.DataFrame,
    timezone: str = "America/New_York",
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    mask = out["ts"].map(lambda ts: is_regular_session(pd.Timestamp(ts), timezone))
    return out.loc[mask].reset_index(drop=True)
