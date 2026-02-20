from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Mapping

import pandas as pd

from sma_outfits.config.models import RouteRule, Settings
from sma_outfits.utils import timeframe_to_pandas_rule

ExecutionPair = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    execution_pairs: list[ExecutionPair]
    timeframes_by_symbol: dict[str, list[str]]


def to_utc_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def resolve_outfits_path(outfits_path: str) -> Path:
    candidate = Path(outfits_path)
    if not candidate.exists():
        raise FileNotFoundError(
            "Configured outfits catalog path does not exist: "
            f"{candidate}"
        )
    if not candidate.is_file():
        raise FileNotFoundError(
            "Configured outfits catalog path is not a file: "
            f"{candidate}"
        )
    return candidate


def strategy_source_value(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    price_basis: str,
) -> float:
    if price_basis == "close":
        return close
    if price_basis == "ohlc4":
        return (open_ + high + low + close) / 4.0
    raise RuntimeError(f"Unsupported strategy.price_basis '{price_basis}'")


def execution_timeframes_by_symbol(
    pairs: list[ExecutionPair],
) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for symbol, timeframe in pairs:
        values = mapping.setdefault(symbol, [])
        if timeframe not in values:
            values.append(timeframe)
    return mapping


def resolve_execution_scope(
    *,
    settings: Settings,
    symbols: list[str],
    timeframes: list[str],
    command: str,
) -> ExecutionScope:
    pairs = resolve_execution_pairs(
        settings=settings,
        symbols=symbols,
        timeframes=timeframes,
        command=command,
    )
    return ExecutionScope(
        execution_pairs=pairs,
        timeframes_by_symbol=execution_timeframes_by_symbol(pairs),
    )


def resolve_execution_pairs(
    *,
    settings: Settings,
    symbols: list[str],
    timeframes: list[str],
    command: str,
) -> list[ExecutionPair]:
    normalized_symbols: list[str] = []
    seen_symbols: set[str] = set()
    for symbol in symbols:
        normalized = symbol.upper()
        if normalized not in seen_symbols:
            seen_symbols.add(normalized)
            normalized_symbols.append(normalized)

    if not settings.strategy.strict_routing:
        return [
            (symbol, timeframe)
            for symbol in normalized_symbols
            for timeframe in timeframes
        ]

    configured_routes = settings.strategy.routes
    configured_symbols = {route.symbol for route in configured_routes}
    configured_timeframes = {route.timeframe for route in configured_routes}
    selected = [
        (route.symbol, route.timeframe)
        for route in configured_routes
        if route.symbol in normalized_symbols and route.timeframe in timeframes
    ]
    if not selected:
        raise RuntimeError(
            f"Strict routing preflight failed for {command}: requested symbols/timeframes "
            "do not match any configured route."
        )

    missing_symbols = sorted(set(normalized_symbols).difference(configured_symbols))
    missing_timeframes = sorted(set(timeframes).difference(configured_timeframes))
    if missing_symbols or missing_timeframes:
        details: list[str] = []
        if missing_symbols:
            details.append("symbols=" + ",".join(missing_symbols))
        if missing_timeframes:
            details.append("timeframes=" + ",".join(missing_timeframes))
        configured = ", ".join(
            f"{route.symbol}/{route.timeframe}" for route in configured_routes
        )
        raise RuntimeError(
            f"Strict routing preflight failed for {command}: requested values outside configured "
            "strict routes (" + "; ".join(details) + "). "
            f"Configured routes: {configured}"
        )

    unique_pairs: list[ExecutionPair] = []
    seen: set[ExecutionPair] = set()
    for pair in selected:
        if pair not in seen:
            seen.add(pair)
            unique_pairs.append(pair)
    return unique_pairs


def preflight_cross_symbol_context_execution_pairs(
    *,
    routes_by_id: Mapping[str, RouteRule],
    routes: list[RouteRule],
    execution_pairs: list[ExecutionPair],
    command: str,
) -> None:
    selected_pairs = set(execution_pairs)
    violations: list[str] = []
    for route in routes:
        route_pair = (route.symbol, route.timeframe)
        if route_pair not in selected_pairs:
            continue
        cross_context = route.cross_symbol_context
        if not cross_context.enabled:
            continue
        for rule in cross_context.rules:
            reference_route = routes_by_id.get(rule.reference_route_id)
            if reference_route is None:
                raise RuntimeError(
                    "Cross-symbol context preflight failed for {}: route '{}' "
                    "references unknown route_id '{}'".format(
                        command,
                        route.id,
                        rule.reference_route_id,
                    )
                )
            reference_pair = (reference_route.symbol, reference_route.timeframe)
            if reference_pair not in selected_pairs:
                violations.append(
                    "{} requires {} ({}/{})".format(
                        route.id,
                        rule.reference_route_id,
                        reference_pair[0],
                        reference_pair[1],
                    )
                )
    if violations:
        raise RuntimeError(
            "Cross-symbol context preflight failed for {}: selected symbols/timeframes "
            "omit required reference route pairs ({}).".format(command, "; ".join(violations))
        )


class RollingBarBuffer:
    def __init__(self, maxlen: int) -> None:
        if maxlen <= 0:
            raise ValueError("RollingBarBuffer maxlen must be > 0")
        self._rows: Deque[tuple[pd.Timestamp, float, float, float, float, float]] = deque(
            maxlen=maxlen
        )
        self._frame_cache: pd.DataFrame | None = None
        self._dirty = True

    def append(
        self,
        *,
        ts: object,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        label: str,
    ) -> None:
        ts_utc = to_utc_timestamp(ts)
        if self._rows:
            last_ts = self._rows[-1][0]
            if ts_utc <= last_ts:
                if ts_utc == last_ts:
                    raise RuntimeError(
                        f"Duplicate bar timestamp for {label}: {ts_utc.isoformat()}"
                    )
                raise RuntimeError(
                    "Non-monotonic bar timestamp for {}: {} < {}".format(
                        label,
                        ts_utc.isoformat(),
                        last_ts.isoformat(),
                    )
                )

        self._rows.append(
            (
                ts_utc,
                float(open_),
                float(high),
                float(low),
                float(close),
                float(volume),
            )
        )
        self._dirty = True

    def to_frame(self) -> pd.DataFrame:
        if self._frame_cache is not None and not self._dirty:
            return self._frame_cache
        if not self._rows:
            frame = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        else:
            frame = pd.DataFrame(
                [
                    {
                        "ts": row[0],
                        "open": row[1],
                        "high": row[2],
                        "low": row[3],
                        "close": row[4],
                        "volume": row[5],
                    }
                    for row in self._rows
                ]
            )
        self._frame_cache = frame
        self._dirty = False
        return frame


class SourceBarWindow:
    def __init__(self, maxlen: int) -> None:
        if maxlen <= 0:
            raise ValueError("SourceBarWindow maxlen must be > 0")
        self._maxlen = maxlen
        self._rows: Deque[tuple[pd.Timestamp, float, float, float, float, float]] = deque()
        self._by_ts: dict[pd.Timestamp, tuple[float, float, float, float, float]] = {}

    @property
    def last_ts(self) -> pd.Timestamp | None:
        if not self._rows:
            return None
        return self._rows[-1][0]

    def append(
        self,
        *,
        ts: object,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        symbol: str,
    ) -> bool:
        ts_utc = to_utc_timestamp(ts)
        values = (
            float(open_),
            float(high),
            float(low),
            float(close),
            float(volume),
        )

        existing = self._by_ts.get(ts_utc)
        if existing is not None:
            if existing == values:
                return False
            raise RuntimeError(
                "Conflicting duplicate bar detected for "
                f"{symbol} at {ts_utc.isoformat()}"
            )

        if self._rows:
            last_ts = self._rows[-1][0]
            if ts_utc < last_ts:
                raise RuntimeError(
                    f"Non-monotonic live bar timestamp for {symbol}: "
                    f"{ts_utc.isoformat()} < {last_ts.isoformat()}"
                )

        if len(self._rows) >= self._maxlen:
            oldest = self._rows.popleft()
            self._by_ts.pop(oldest[0], None)

        self._rows.append((ts_utc, *values))
        self._by_ts[ts_utc] = values
        return True

    def load_frame(self, frame: pd.DataFrame, *, symbol: str) -> None:
        normalized = frame.loc[:, ["ts", "open", "high", "low", "close", "volume"]].copy()
        normalized["ts"] = pd.to_datetime(normalized["ts"], utc=True)
        normalized = normalized.sort_values("ts").drop_duplicates(subset=["ts"])
        for row in normalized.itertuples(index=False):
            self.append(
                ts=row.ts,
                open_=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                symbol=symbol,
            )


class IncrementalTimeframeAggregator:
    def __init__(
        self,
        *,
        timeframe: str,
        timezone: str,
        anchors: Mapping[str, str] | None,
    ) -> None:
        self.timeframe = timeframe
        self.timezone = timezone
        self.rule = timeframe_to_pandas_rule(timeframe, anchors=anchors)
        self._bucket_end: pd.Timestamp | None = None
        self._open = 0.0
        self._high = 0.0
        self._low = 0.0
        self._close = 0.0
        self._volume = 0.0

    def update(
        self,
        *,
        ts: object,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> dict[str, float | pd.Timestamp] | None:
        ts_utc = to_utc_timestamp(ts)
        next_bucket_end = self._resolve_bucket_end(ts_utc)
        if self._bucket_end is None:
            self._start_bucket(
                bucket_end=next_bucket_end,
                open_=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
            return None

        if next_bucket_end < self._bucket_end:
            raise RuntimeError(
                "Non-monotonic aggregated timestamp for {}: {} < {}".format(
                    self.timeframe,
                    next_bucket_end.isoformat(),
                    self._bucket_end.isoformat(),
                )
            )

        if next_bucket_end == self._bucket_end:
            self._high = max(self._high, float(high))
            self._low = min(self._low, float(low))
            self._close = float(close)
            self._volume += float(volume)
            return None

        completed = {
            "ts": self._bucket_end,
            "open": self._open,
            "high": self._high,
            "low": self._low,
            "close": self._close,
            "volume": self._volume,
        }
        self._start_bucket(
            bucket_end=next_bucket_end,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        return completed

    def _start_bucket(
        self,
        *,
        bucket_end: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        self._bucket_end = bucket_end
        self._open = float(open_)
        self._high = float(high)
        self._low = float(low)
        self._close = float(close)
        self._volume = float(volume)

    def _resolve_bucket_end(self, ts_utc: pd.Timestamp) -> pd.Timestamp:
        local_ts = ts_utc.tz_convert(self.timezone)
        bucket_end = local_ts.ceil(self.rule)
        return bucket_end.tz_convert("UTC")
