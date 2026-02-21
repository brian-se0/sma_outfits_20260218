from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    SMAState,
    SignalEvent,
    StrikeEvent,
    event_to_record,
)
from sma_outfits.execution import (
    RollingBarBuffer,
    preflight_cross_symbol_context_execution_pairs,
    resolve_execution_scope,
    resolve_outfits_path,
    strategy_source_value,
    to_utc_timestamp,
)
from sma_outfits.indicators.sma_engine import SMAEngine
from sma_outfits.reporting.summary import build_summary
from sma_outfits.risk.manager import ManagedPosition, RiskManager
from sma_outfits.signals.detector import RouteBarContext, StrikeDetector, load_outfits


@dataclass(slots=True, frozen=True)
class ReplayResult:
    strikes: list[StrikeEvent]
    signals: list[SignalEvent]
    position_events: list[PositionEvent]
    archive_records: list[ArchiveRecord]
    summary: dict


ReplayProgressCallback = Callable[[int, int, str, str, pd.Timestamp], None]


@dataclass(slots=True)
class _ReplayBarWork:
    key: tuple[str, str]
    bar: BarEvent
    history: pd.DataFrame
    sma_states: dict[int, SMAState]
    route_context: RouteBarContext | None


class ReplayEngine:
    def __init__(self, settings: Settings, storage: StorageManager) -> None:
        self.settings = settings
        self.storage = storage
        outfits_path = resolve_outfits_path(settings.outfits_path)
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
            risk_dollar_per_trade=self.settings.risk.risk_dollar_per_trade,
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
        execution_pairs = resolve_execution_scope(
            settings=self.settings,
            symbols=symbols,
            timeframes=timeframes,
            command="replay",
        ).execution_pairs
        preflight_cross_symbol_context_execution_pairs(
            routes_by_id=self._routes_by_id,
            routes=self.settings.strategy.routes,
            execution_pairs=execution_pairs,
            command="replay",
        )

        strikes: list[StrikeEvent] = []
        signals: list[SignalEvent] = []
        position_events: list[PositionEvent] = []
        archive_records: list[ArchiveRecord] = []
        proxy_prices: dict[str, float] = {}
        bars_by_pair: dict[tuple[str, str], pd.DataFrame] = {}
        total_bars = 0

        for symbol, timeframe in execution_pairs:
            bars = self.storage.read_bars(symbol, timeframe, start=start, end=end)
            if bars.empty:
                continue
            bars = bars.sort_values("ts").reset_index(drop=True)
            bars_by_pair[(symbol, timeframe)] = bars
            total_bars += len(bars)

        if total_bars == 0:
            raise RuntimeError("Replay aborted: no stored bars found for requested symbols/timeframes")

        pointers: dict[tuple[str, str], int] = {key: 0 for key in bars_by_pair}
        history_by_key: dict[tuple[str, str], RollingBarBuffer] = {}
        active_positions_by_key: dict[tuple[str, str], list[ManagedPosition]] = {}
        latest_context_by_route_id: dict[str, tuple[pd.Timestamp, RouteBarContext]] = {}

        def _cross_context_lookup(reference_route_id: str, ts: datetime) -> RouteBarContext | None:
            return self._lookup_cross_context(
                latest_context_by_route_id=latest_context_by_route_id,
                reference_route_id=reference_route_id,
                bar_ts=ts,
            )

        processed_bars = 0
        while True:
            next_ts = self._next_batch_timestamp(bars_by_pair=bars_by_pair, pointers=pointers)
            if next_ts is None:
                break

            batch_rows = self._consume_timestamp_batch(
                ts=next_ts,
                bars_by_pair=bars_by_pair,
                pointers=pointers,
            )
            pass_work: list[_ReplayBarWork] = []

            # Pass A: update history/SMA/context for all bars in this timestamp batch first.
            for key, row in batch_rows:
                symbol, timeframe = key
                bar_ts = to_utc_timestamp(row.ts)
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

                history_buffer = history_by_key.get(key)
                if history_buffer is None:
                    history_buffer = RollingBarBuffer(self._history_window)
                    history_by_key[key] = history_buffer
                history_buffer.append(
                    ts=bar.ts,
                    open_=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    label=f"{bar.symbol}/{bar.timeframe}",
                )
                history = history_buffer.to_frame()

                sma_states = self.sma_engine.update(
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    ts=bar.ts,
                    source_value=strategy_source_value(
                        open_=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        price_basis=self.settings.strategy.price_basis,
                    ),
                )
                route_context = self.detector.build_route_context(bar=bar, sma_states=sma_states)
                if route_context is not None:
                    latest_context_by_route_id[route_context.route.id] = (bar_ts, route_context)

                pass_work.append(
                    _ReplayBarWork(
                        key=key,
                        bar=bar,
                        history=history,
                        sma_states=sma_states,
                        route_context=route_context,
                    )
                )

            # Pass B: detect signals and run risk after same-timestamp contexts are available.
            for work in pass_work:
                new_strikes, detected_signals = self.detector.detect(
                    bar=work.bar,
                    sma_states=work.sma_states,
                    history=work.history,
                    session_type="regular",
                    cross_context_lookup=_cross_context_lookup,
                )
                new_signals = [
                    self.risk_manager.prepare_signal_for_entry(
                        signal=signal,
                        route_history=work.history,
                    )
                    for signal in detected_signals
                ]
                strikes.extend(new_strikes)
                signals.extend(new_signals)

                active_positions = active_positions_by_key.get(work.key, [])
                for signal in new_signals:
                    active_positions.append(
                        self.risk_manager.open_position(
                            signal=signal,
                            symbol=work.bar.symbol,
                            ts=work.bar.ts,
                            route_context=work.route_context,
                            cross_context_lookup=_cross_context_lookup,
                        )
                    )

                for strike, signal in zip(new_strikes, new_signals, strict=True):
                    if self.settings.archive.enabled:
                        archive_records.append(self._archive_signal(strike=strike, signal=signal))

                next_positions: list[ManagedPosition] = []
                for position in active_positions:
                    events = self.risk_manager.evaluate_bar(
                        position=position,
                        bar=work.bar,
                        proxy_prices=proxy_prices,
                        route_context=work.route_context,
                        route_history=work.history,
                    )
                    position_events.extend(events)
                    if not position.closed:
                        next_positions.append(position)
                active_positions_by_key[work.key] = next_positions

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
    def _next_batch_timestamp(
        *,
        bars_by_pair: dict[tuple[str, str], pd.DataFrame],
        pointers: dict[tuple[str, str], int],
    ) -> pd.Timestamp | None:
        next_ts: pd.Timestamp | None = None
        for key, bars in bars_by_pair.items():
            pointer = pointers[key]
            if pointer >= len(bars):
                continue
            candidate = to_utc_timestamp(bars.iloc[pointer]["ts"])
            if next_ts is None or candidate < next_ts:
                next_ts = candidate
        return next_ts

    @staticmethod
    def _consume_timestamp_batch(
        *,
        ts: pd.Timestamp,
        bars_by_pair: dict[tuple[str, str], pd.DataFrame],
        pointers: dict[tuple[str, str], int],
    ) -> list[tuple[tuple[str, str], pd.Series]]:
        batch_rows: list[tuple[tuple[str, str], pd.Series]] = []
        for key in sorted(bars_by_pair.keys()):
            bars = bars_by_pair[key]
            pointer = pointers[key]
            if pointer >= len(bars):
                continue
            candidate_ts = to_utc_timestamp(bars.iloc[pointer]["ts"])
            if candidate_ts != ts:
                continue
            batch_rows.append((key, bars.iloc[pointer]))
            pointers[key] = pointer + 1
        return batch_rows

    @staticmethod
    def _lookup_cross_context(
        *,
        latest_context_by_route_id: dict[str, tuple[pd.Timestamp, RouteBarContext]],
        reference_route_id: str,
        bar_ts: datetime,
    ) -> RouteBarContext | None:
        cached = latest_context_by_route_id.get(reference_route_id)
        if cached is None:
            return None
        cached_ts, context = cached
        if cached_ts <= to_utc_timestamp(bar_ts):
            return context
        return None
