from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from sma_outfits.archive.thread_writer import append_thread_markdown
from sma_outfits.config.models import RouteRule
from sma_outfits.config.models import Settings
from sma_outfits.data.storage import StorageManager
from sma_outfits.events import (
    ArchiveRecord,
    BarEvent,
    PositionEvent,
    SignalEvent,
    StrikeEvent,
    event_to_record,
)
from sma_outfits.indicators.sma_engine import SMAEngine
from sma_outfits.reporting.summary import build_summary
from sma_outfits.risk.manager import ManagedPosition, RiskManager
from sma_outfits.signals.detector import StrikeDetector, load_outfits


@dataclass(slots=True, frozen=True)
class ReplayResult:
    strikes: list[StrikeEvent]
    signals: list[SignalEvent]
    position_events: list[PositionEvent]
    archive_records: list[ArchiveRecord]
    summary: dict


ReplayProgressCallback = Callable[[int, int, str, str, pd.Timestamp], None]


class ReplayEngine:
    def __init__(self, settings: Settings, storage: StorageManager) -> None:
        self.settings = settings
        self.storage = storage
        outfits_path = self._resolve_outfits_path(settings.outfits_path)
        self.outfits = load_outfits(outfits_path)
        self._routes_by_id: dict[str, RouteRule] = {
            route.id: route for route in self.settings.strategy.routes
        }
        self._init_pipeline_components()

    def _init_pipeline_components(self) -> None:
        self.detector = StrikeDetector(
            outfits=self.outfits,
            routes=self.settings.strategy.routes,
            strict_routing=self.settings.strategy.strict_routing,
            tolerance=self.settings.signal.tolerance,
            trigger_mode=self.settings.strategy.trigger_mode,
        )
        periods = sorted(self.detector.required_periods())
        if not periods:
            periods = sorted({period for outfit in self.outfits for period in outfit.periods})
        self._history_window = max(64, max(periods, default=2) + 8)
        self.sma_engine = SMAEngine(periods)
        self.risk_manager = RiskManager(
            long_break=self.settings.risk.long_break,
            short_break=self.settings.risk.short_break,
            partial_take_r=self.settings.risk.partial_take_r,
            final_take_r=self.settings.risk.final_take_r,
            timeout_bars=self.settings.risk.timeout_bars,
            migrations={
                symbol: migration.model_dump()
                for symbol, migration in self.settings.risk.migrations.items()
            },
            routes=self._routes_by_id,
            allow_same_bar_exit=self.settings.strategy.allow_same_bar_exit,
        )

    def run(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        progress_callback: ReplayProgressCallback | None = None,
    ) -> ReplayResult:
        self._init_pipeline_components()
        symbols = symbols or self.settings.universe.symbols
        timeframes = timeframes or self.settings.timeframes.live
        execution_pairs = self._resolve_execution_pairs(symbols=symbols, timeframes=timeframes)

        strikes: list[StrikeEvent] = []
        signals: list[SignalEvent] = []
        position_events: list[PositionEvent] = []
        archive_records: list[ArchiveRecord] = []
        proxy_prices: dict[str, float] = {}
        jobs: list[tuple[str, str, pd.DataFrame]] = []
        total_bars = 0

        for symbol, timeframe in execution_pairs:
            bars = self.storage.read_bars(symbol, timeframe, start=start, end=end)
            if bars.empty:
                continue
            bars = bars.sort_values("ts").reset_index(drop=True)
            jobs.append((symbol, timeframe, bars))
            total_bars += len(bars)

        if total_bars == 0:
            raise RuntimeError("Replay aborted: no stored bars found for requested symbols/timeframes")

        processed_bars = 0
        for symbol, timeframe, bars in jobs:
            history = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
            active_positions: list[ManagedPosition] = []

            for row in bars.itertuples(index=False):
                bar_ts = _to_utc_timestamp(row.ts)
                bar = BarEvent(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=bar_ts.to_pydatetime(),
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                    source="replay",
                )
                proxy_prices[symbol] = bar.close
                processed_bars += 1
                if progress_callback is not None:
                    progress_callback(processed_bars, total_bars, symbol, timeframe, bar_ts)

                history = self._append_history(history, bar)
                source_value = _strategy_source_value(
                    bar=bar,
                    price_basis=self.settings.strategy.price_basis,
                )
                sma_states = self.sma_engine.update(
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    ts=bar.ts,
                    source_value=source_value,
                )
                route_context = self.detector.build_route_context(
                    bar=bar,
                    sma_states=sma_states,
                )
                new_strikes, detected_signals = self.detector.detect(
                    bar=bar,
                    sma_states=sma_states,
                    history=history,
                    session_type="regular",
                )
                new_signals = [
                    self.risk_manager.prepare_signal_for_entry(
                        signal=signal,
                        route_history=history,
                    )
                    for signal in detected_signals
                ]
                strikes.extend(new_strikes)
                signals.extend(new_signals)
                for signal in new_signals:
                    active_positions.append(
                        self.risk_manager.open_position(signal, symbol=symbol, ts=bar.ts)
                    )

                for strike, signal in zip(new_strikes, new_signals, strict=True):
                    if self.settings.archive.enabled:
                        archive_records.append(self._archive_signal(strike=strike, signal=signal))

                next_positions: list[ManagedPosition] = []
                for position in active_positions:
                    events = self.risk_manager.evaluate_bar(
                        position,
                        bar=bar,
                        proxy_prices=proxy_prices,
                        route_context=route_context,
                        route_history=history,
                    )
                    position_events.extend(events)
                    if not position.closed:
                        next_positions.append(position)
                active_positions = next_positions

        summary = build_summary(strikes=strikes, signals=signals, position_events=position_events)
        if strikes:
            self.storage.append_events("strikes", [event_to_record(event) for event in strikes])
        if signals:
            self.storage.append_events("signals", [event_to_record(event) for event in signals])
        if position_events:
            self.storage.append_events("positions", [event_to_record(event) for event in position_events])
        if archive_records:
            self.storage.append_events("archive", [event_to_record(event) for event in archive_records])

        return ReplayResult(
            strikes=strikes,
            signals=signals,
            position_events=position_events,
            archive_records=archive_records,
            summary=summary,
        )

    def _append_history(self, history: pd.DataFrame, bar: BarEvent) -> pd.DataFrame:
        ts = _to_utc_timestamp(bar.ts)
        if not history.empty:
            last_ts = _to_utc_timestamp(history.iloc[-1]["ts"])
            if ts <= last_ts:
                if ts == last_ts:
                    raise RuntimeError(
                        f"Duplicate replay bar timestamp for {bar.symbol}/{bar.timeframe}: {ts.isoformat()}"
                    )
                raise RuntimeError(
                    f"Non-monotonic replay bar timestamp for {bar.symbol}/{bar.timeframe}: "
                    f"{ts.isoformat()} < {last_ts.isoformat()}"
                )

        history.loc[len(history)] = {
            "ts": ts,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        if len(history) > self._history_window:
            history = history.iloc[-self._history_window :].reset_index(drop=True)
        return history

    def _archive_signal(
        self,
        strike: StrikeEvent,
        signal: SignalEvent,
    ) -> ArchiveRecord:
        archive_root = Path(self.settings.archive.root)
        markdown_path = append_thread_markdown(
            root=archive_root / "threads",
            strike=strike,
            signal=signal,
        )
        caption = (
            f"{strike.symbol} {strike.timeframe} {signal.signal_type} at {strike.sma_value:.2f} "
            f"(MA{strike.period}, outfit {strike.outfit_id})"
        )
        return ArchiveRecord(
            signal_id=signal.id,
            markdown_path=str(markdown_path),
            artifact_type="thread_markdown",
            caption=caption,
            ts=strike.bar_ts,
        )

    @staticmethod
    def _resolve_outfits_path(outfits_path: str) -> Path:
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

    def _resolve_execution_pairs(
        self,
        symbols: list[str],
        timeframes: list[str],
    ) -> list[tuple[str, str]]:
        normalized_symbols = [symbol.upper() for symbol in symbols]
        if not self.settings.strategy.strict_routing:
            return [
                (symbol, timeframe)
                for symbol in normalized_symbols
                for timeframe in timeframes
            ]

        configured_routes = self.settings.strategy.routes
        configured_symbols = {route.symbol for route in configured_routes}
        configured_timeframes = {route.timeframe for route in configured_routes}
        selected = [
            (route.symbol, route.timeframe)
            for route in configured_routes
            if route.symbol in normalized_symbols and route.timeframe in timeframes
        ]
        if not selected:
            raise RuntimeError(
                "Strict routing preflight failed for replay: requested symbols/timeframes "
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
            raise RuntimeError(
                "Strict routing preflight failed for replay: requested values outside configured "
                "routes (" + "; ".join(details) + ")."
            )

        unique_pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pair in selected:
            if pair not in seen:
                seen.add(pair)
                unique_pairs.append(pair)
        return unique_pairs


def _to_utc_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _strategy_source_value(bar: BarEvent, price_basis: str) -> float:
    if price_basis == "close":
        return bar.close
    if price_basis == "ohlc4":
        return (bar.open + bar.high + bar.low + bar.close) / 4.0
    raise RuntimeError(f"Unsupported strategy.price_basis '{price_basis}'")
