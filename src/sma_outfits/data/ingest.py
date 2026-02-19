from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from sma_outfits.config.models import Settings
from sma_outfits.data.alpaca_clients import HistoricalBarsClient
from sma_outfits.data.resample import resample_ohlcv
from sma_outfits.data.storage import StorageManager
from sma_outfits.utils import apply_regular_session_filter, is_crypto_symbol


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
        for source_tf in grouped_targets:
            fetched = client.fetch_bars(symbol, start, end, source_tf)
            if (
                settings.sessions.regular_only
                and not settings.sessions.extended_enabled
                and not is_crypto_symbol(symbol)
                and _should_apply_session_filter(source_tf)
            ):
                fetched = apply_regular_session_filter(
                    fetched, timezone=settings.sessions.timezone
                )
            if fetched.empty:
                raise RuntimeError(f"No bars available after session filter: {symbol} {source_tf}")
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
