from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from sma_outfits.config.models import Settings
from sma_outfits.data.alpaca_clients import HistoricalBarsClient
from sma_outfits.data.resample import resample_ohlcv
from sma_outfits.data.storage import StorageManager
from sma_outfits.utils import (
    apply_regular_session_filter,
    ensure_utc_timestamp,
    market_for_symbol,
)


@dataclass(slots=True, frozen=True)
class BackfillResult:
    symbol: str
    timeframe: str
    bars_written: int


BackfillProgressCallback = Callable[[int, int, BackfillResult], None]


def source_timeframe_for(target: str) -> str:
    intraday = {"1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m"}
    hourly = {"1h", "2h", "4h"}
    daily = {"1D", "1W", "1M", "1Q"}
    if target in intraday:
        return "1m"
    if target in hourly:
        return "1h"
    if target in daily:
        return "1D"
    raise ValueError(f"Unsupported target timeframe '{target}'")


def backfill_historical(
    settings: Settings,
    symbols: list[str],
    timeframes: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    client: HistoricalBarsClient,
    storage: StorageManager,
    progress_callback: BackfillProgressCallback | None = None,
) -> list[BackfillResult]:
    if start >= end:
        raise ValueError("start must be earlier than end")
    results: list[BackfillResult] = []
    completed = 0
    total = len(symbols) * len(timeframes)

    grouped_targets: dict[str, list[str]] = defaultdict(list)
    for target in timeframes:
        grouped_targets[source_timeframe_for(target)].append(target)

    for symbol in symbols:
        source_frames: dict[str, pd.DataFrame] = {}
        symbol_market = market_for_symbol(symbol, settings.universe.symbol_markets)
        boundary_timezone = "UTC" if symbol_market == "crypto" else settings.sessions.timezone
        for source_tf in grouped_targets:
            fetch_start, fetch_end = _source_fetch_window(
                source_timeframe=source_tf,
                start=start,
                end=end,
                timezone=boundary_timezone,
            )
            fetched = client.fetch_bars(
                symbol=symbol,
                start=fetch_start,
                end=fetch_end,
                timeframe=source_tf,
                market=symbol_market,
            )
            if (
                settings.sessions.regular_only
                and not settings.sessions.extended_enabled
                and symbol_market == "stocks"
                and _should_apply_session_filter(source_tf)
            ):
                session_windows = client.fetch_calendar_sessions(
                    start=fetch_start,
                    end=fetch_end,
                    timezone=settings.sessions.timezone,
                )
                fetched = apply_regular_session_filter(
                    fetched,
                    session_windows=session_windows,
                    timezone=settings.sessions.timezone,
                )
            if fetched.empty:
                raise RuntimeError(
                    "No bars available after source fetch/session filter for "
                    f"{symbol} {source_tf}. "
                    f"Configured policy ingest.empty_source_policy={settings.ingest.empty_source_policy!r}"
                )
            source_frames[source_tf] = fetched

        for source_tf, target_tfs in grouped_targets.items():
            base_frame = source_frames[source_tf]
            for target_tf in target_tfs:
                if target_tf == source_tf:
                    output = base_frame
                else:
                    output = resample_ohlcv(
                        base_frame,
                        timeframe=target_tf,
                        timezone=settings.sessions.timezone,
                        anchors=settings.timeframes.anchors,
                    )
                output = _clip_to_requested_window(
                    output,
                    timeframe=target_tf,
                    start=start,
                    end=end,
                    timezone=boundary_timezone,
                )
                if output.empty:
                    raise RuntimeError(
                        "No bars remain after clipping to requested backfill window "
                        f"for {symbol} {target_tf}: "
                        f"start={ensure_utc_timestamp(start).isoformat()} "
                        f"end={ensure_utc_timestamp(end).isoformat()}"
                    )
                written = storage.write_bars(
                    output,
                    symbol=symbol,
                    timeframe=target_tf,
                    timezone=settings.sessions.timezone,
                )
                result = BackfillResult(
                    symbol=symbol,
                    timeframe=target_tf,
                    bars_written=written,
                )
                results.append(result)
                completed += 1
                if progress_callback is not None:
                    progress_callback(completed, total, result)
    return results


def _should_apply_session_filter(source_timeframe: str) -> bool:
    return source_timeframe in {"1m", "1h"}


def _source_fetch_window(
    source_timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timezone: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_utc = ensure_utc_timestamp(start)
    end_utc = ensure_utc_timestamp(end)
    if source_timeframe != "1D":
        return start_utc, end_utc

    local_start = start_utc.tz_convert(timezone).floor("D")
    local_end = end_utc.tz_convert(timezone).ceil("D")
    return local_start.tz_convert("UTC"), local_end.tz_convert("UTC")


def _clip_to_requested_window(
    frame: pd.DataFrame,
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timezone: str,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    start_utc = ensure_utc_timestamp(start)
    end_utc = ensure_utc_timestamp(end)

    intraday = {"1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m", "1h", "2h", "4h"}
    if timeframe in intraday:
        clipped = out.loc[(out["ts"] >= start_utc) & (out["ts"] <= end_utc)]
        return clipped.reset_index(drop=True)

    start_date = start_utc.tz_convert(timezone).strftime("%Y-%m-%d")
    end_date = end_utc.tz_convert(timezone).strftime("%Y-%m-%d")
    local_dates = out["ts"].dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")
    clipped = out.loc[(local_dates >= start_date) & (local_dates <= end_date)]
    return clipped.reset_index(drop=True)
