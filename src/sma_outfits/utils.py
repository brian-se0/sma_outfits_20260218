from __future__ import annotations

import hashlib
from typing import Iterable, Mapping

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

BASE_TIMEFRAME_TO_PANDAS_RULE = {
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
}

DEFAULT_PERIOD_ANCHORS = {
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

ALLOWED_MARKETS = frozenset({"stocks", "crypto"})


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


def timeframe_to_pandas_rule(
    value: str,
    anchors: Mapping[str, str] | None = None,
) -> str:
    timeframe = normalize_timeframe(value)
    if timeframe in BASE_TIMEFRAME_TO_PANDAS_RULE:
        return BASE_TIMEFRAME_TO_PANDAS_RULE[timeframe]
    if timeframe not in DEFAULT_PERIOD_ANCHORS:
        raise ValueError(f"Unsupported timeframe for pandas rule mapping: {timeframe}")

    candidate_anchors = anchors if anchors is not None else DEFAULT_PERIOD_ANCHORS
    if timeframe not in candidate_anchors:
        raise ValueError(
            f"Missing anchor rule for timeframe '{timeframe}'. "
            f"Required keys: {tuple(DEFAULT_PERIOD_ANCHORS.keys())}"
        )
    rule = str(candidate_anchors[timeframe]).strip()
    if not rule:
        raise ValueError(f"Anchor rule for timeframe '{timeframe}' must be non-empty")
    return rule


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


def normalize_market(value: str) -> str:
    market = value.strip().lower()
    if market not in ALLOWED_MARKETS:
        raise ValueError(
            f"Unsupported market '{value}'. Allowed values: {sorted(ALLOWED_MARKETS)}"
        )
    return market


def market_for_symbol(
    symbol: str,
    symbol_markets: Mapping[str, str],
) -> str:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol cannot be empty")
    if normalized_symbol not in symbol_markets:
        raise ValueError(
            f"No configured market mapping for symbol '{normalized_symbol}'. "
            "Add universe.symbol_markets entry."
        )
    return normalize_market(str(symbol_markets[normalized_symbol]))


def is_regular_session(
    ts: pd.Timestamp,
    session_windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp] | None],
    timezone: str = "America/New_York",
) -> bool:
    ts_utc = ensure_utc_timestamp(ts)
    local_date_key = ts_utc.tz_convert(timezone).strftime("%Y-%m-%d")
    session_window = session_windows.get(local_date_key)
    if session_window is None:
        return False
    market_open_utc = ensure_utc_timestamp(session_window[0])
    market_close_utc = ensure_utc_timestamp(session_window[1])
    if market_close_utc < market_open_utc:
        raise ValueError(
            f"Invalid session window for {local_date_key}: "
            f"close={market_close_utc.isoformat()} before open={market_open_utc.isoformat()}"
        )
    return market_open_utc <= ts_utc <= market_close_utc


def apply_regular_session_filter(
    frame: pd.DataFrame,
    session_windows: Mapping[str, tuple[pd.Timestamp, pd.Timestamp] | None],
    timezone: str = "America/New_York",
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    local_dates = out["ts"].dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")
    unique_dates = sorted(set(local_dates.tolist()))
    missing_dates = [date for date in unique_dates if date not in session_windows]
    if missing_dates:
        raise RuntimeError(
            "Regular-session filter requires explicit session windows for all bar dates. "
            f"Missing dates: {missing_dates}"
        )
    closed_dates = [date for date in unique_dates if session_windows.get(date) is None]
    if closed_dates:
        raise RuntimeError(
            "Regular-session filter received bars for dates marked as closed sessions. "
            f"Closed dates: {closed_dates}"
        )
    mask = out["ts"].map(
        lambda ts: is_regular_session(
            pd.Timestamp(ts),
            session_windows=session_windows,
            timezone=timezone,
        )
    )
    return out.loc[mask].reset_index(drop=True)
