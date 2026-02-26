from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, AsyncIterator, Callable

import pandas as pd

from sma_outfits.archive.thread_writer import append_thread_markdown
from sma_outfits.config.models import RouteRule, Settings
from sma_outfits.data.alpaca_clients import (
    AlpacaRESTClient,
    AlpacaWebSocketBarStream,
    LiveBar,
    LiveStreamError,
    StreamDisconnectedError,
    StreamHeartbeatError,
    StreamStaleError,
)
from sma_outfits.data.storage import StorageManager
from sma_outfits.events import (
    ArchiveRecord,
    BarEvent,
    PositionEvent,
    SignalEvent,
    StrikeEvent,
    event_to_record,
)
from sma_outfits.execution import (
    IncrementalTimeframeAggregator,
    RollingBarBuffer,
    SourceBarWindow,
    preflight_cross_symbol_context_execution_pairs,
    resolve_execution_scope,
    resolve_outfits_path,
    strategy_source_value,
    to_utc_timestamp,
)
from sma_outfits.indicators.sma_engine import SMAEngine
from sma_outfits.live.state import LiveStateStore
from sma_outfits.reporting.summary import build_summary
from sma_outfits.risk.manager import ManagedPosition, ReferenceBreakRule, RiskManager
from sma_outfits.signals.detector import RouteBarContext, StrikeDetector, load_outfits
from sma_outfits.utils import (
    apply_regular_session_filter,
    ensure_utc_timestamp,
    is_regular_session,
    market_for_symbol,
)

LiveStreamFactory = Callable[[str, list[str]], AsyncIterator[LiveBar]]
LiveProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class LiveRunResult:
    summary: dict[str, Any]
    bars_received: int
    bars_processed: int
    duplicate_bars_skipped: int
    reconnects: int
    stale_feed_reconnects: int
    heartbeat_failures: int
    data_gaps_detected: int
    stale_symbol_warnings: int
    reconciliation_checks: int
    reconciliation_mismatches: int
    started_at: datetime
    ended_at: datetime


class LiveRunner:
    def __init__(
        self,
        settings: Settings,
        storage: StorageManager,
        rest_client: AlpacaRESTClient | None = None,
        stream_factory: LiveStreamFactory | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.rest_client = rest_client or AlpacaRESTClient(settings.alpaca)
        self._logger = logging.getLogger("sma_outfits.live")
        self._stream_factory = stream_factory or self._default_stream_factory
        self._state_store = LiveStateStore(self._resolve_state_path())
        self._state_fingerprint = _state_fingerprint(settings)

        outfits_path = resolve_outfits_path(settings.outfits_path)
        self._outfits = load_outfits(outfits_path)
        self._routes_by_id: dict[str, RouteRule] = {
            route.id: route for route in self.settings.strategy.routes
        }
        self._init_pipeline_components()

        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._reset_state()

    async def run(
        self,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
        runtime_minutes: int | None = None,
        runtime_seconds: float | None = None,
        warmup_minutes: int | None = None,
        progress_callback: LiveProgressCallback | None = None,
    ) -> LiveRunResult:
        self._reset_state()
        self._stop_event.clear()
        self._init_pipeline_components()
        self._progress_callback = progress_callback
        self._started_at = datetime.now(timezone.utc)
        self._emit_progress(force=True, status="starting")

        selected_symbols = symbols or self.settings.universe.symbols
        selected_timeframes = timeframes or self.settings.timeframes.live
        scope = resolve_execution_scope(
            settings=self.settings,
            symbols=selected_symbols,
            timeframes=selected_timeframes,
            command="run-live",
        )
        execution_pairs = scope.execution_pairs
        preflight_cross_symbol_context_execution_pairs(
            routes_by_id=self._routes_by_id,
            routes=self.settings.strategy.routes,
            execution_pairs=execution_pairs,
            command="run-live",
        )
        self._timeframes_by_symbol = scope.timeframes_by_symbol
        self._initialize_timeframe_aggregators(execution_pairs)
        selected_symbols = list(self._timeframes_by_symbol.keys())
        self._selected_symbols = selected_symbols
        self._load_persisted_event_ids()
        effective_runtime = (
            runtime_minutes if runtime_minutes is not None else self.settings.live.runtime_minutes
        )
        effective_warmup = (
            warmup_minutes if warmup_minutes is not None else self.settings.live.warmup_minutes
        )

        if effective_warmup > 0:
            await asyncio.to_thread(
                self._prime_warmup_state,
                selected_symbols,
                self._timeframes_by_symbol,
                effective_warmup,
            )
        self._load_persisted_live_state()

        market_groups = self._split_market_symbols(selected_symbols)
        if not market_groups:
            raise RuntimeError("run-live aborted: no symbols available for websocket subscription")

        tasks = [
            asyncio.create_task(
                self._consume_market_stream(
                    market=market,
                    symbols=group_symbols,
                ),
                name=f"live-{market}",
            )
            for market, group_symbols in market_groups
        ]

        if runtime_seconds is not None:
            if runtime_seconds <= 0:
                raise ValueError("runtime_seconds must be > 0")
            timeout_seconds = float(runtime_seconds)
        else:
            timeout_seconds = (
                float(effective_runtime * 60) if effective_runtime is not None else None
            )

        try:
            if timeout_seconds is None:
                await asyncio.gather(*tasks)
            else:
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=timeout_seconds,
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in done:
                    exc = task.exception()
                    if exc is not None:
                        for pending_task in pending:
                            pending_task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        raise exc
                if pending:
                    self._stop_event.set()
                    for pending_task in pending:
                        pending_task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
        finally:
            self._stop_event.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._persist_live_state(force=True)

        summary = build_summary(
            strikes=self._strikes,
            signals=self._signals,
            position_events=self._position_events,
        )
        ended_at = datetime.now(timezone.utc)
        self._emit_progress(force=True, status="completed")
        return LiveRunResult(
            summary=summary,
            bars_received=self._bars_received,
            bars_processed=self._bars_processed,
            duplicate_bars_skipped=self._duplicate_bars_skipped,
            reconnects=self._reconnects,
            stale_feed_reconnects=self._stale_feed_reconnects,
            heartbeat_failures=self._heartbeat_failures,
            data_gaps_detected=self._data_gaps_detected,
            stale_symbol_warnings=self._stale_symbol_warnings,
            reconciliation_checks=self._reconciliation_checks,
            reconciliation_mismatches=self._reconciliation_mismatches,
            started_at=self._started_at,
            ended_at=ended_at,
        )

    async def _consume_market_stream(
        self,
        market: str,
        symbols: list[str],
    ) -> None:
        attempts = 0
        while not self._stop_event.is_set():
            try:
                async for live_bar in self._stream_factory(market, symbols):
                    if self._stop_event.is_set():
                        return
                    attempts = 0
                    await self._handle_live_bar(live_bar)

                if self._stop_event.is_set():
                    return
                raise StreamDisconnectedError(
                    f"{market} stream ended without stop signal"
                )
            except asyncio.CancelledError:
                return
            except (StreamDisconnectedError, StreamStaleError, StreamHeartbeatError, LiveStreamError) as exc:
                if self._stop_event.is_set():
                    return
                attempts += 1
                self._reconnects += 1
                if isinstance(exc, StreamStaleError):
                    self._stale_feed_reconnects += 1
                if isinstance(exc, StreamHeartbeatError):
                    self._heartbeat_failures += 1

                if attempts > self.settings.live.reconnect_max_attempts:
                    raise RuntimeError(
                        f"{market} stream failed after {attempts} reconnect attempts"
                    ) from exc

                delay = min(
                    self.settings.live.reconnect_max_delay_seconds,
                    self.settings.live.reconnect_base_delay_seconds * (2 ** (attempts - 1)),
                )
                self._logger.warning(
                    "Live stream reconnecting for %s in %.2fs (attempt %d): %s",
                    market,
                    delay,
                    attempts,
                    exc,
                )
                self._emit_progress(
                    force=True,
                    status=f"{market}:reconnect_attempt={attempts}",
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                raise RuntimeError(f"Fatal error in {market} live stream: {exc}") from exc

    async def _handle_live_bar(self, live_bar: LiveBar) -> None:
        async with self._lock:
            self._bars_received += 1
            symbol = live_bar.symbol.upper()
            symbol_market = market_for_symbol(symbol, self.settings.universe.symbol_markets)
            if (
                self.settings.sessions.regular_only
                and not self.settings.sessions.extended_enabled
                and symbol_market == "stocks"
            ):
                self._ensure_calendar_sessions_for_timestamp(live_bar.ts)
                if not is_regular_session(
                    live_bar.ts,
                    session_windows=self._session_windows_by_date,
                    timezone=self.settings.sessions.timezone,
                ):
                    return

            source_window = self._source_windows_by_symbol.get(symbol)
            if source_window is None:
                source_window = SourceBarWindow(self._source_window)
                self._source_windows_by_symbol[symbol] = source_window
            accepted = source_window.append(
                ts=live_bar.ts,
                open_=live_bar.open,
                high=live_bar.high,
                low=live_bar.low,
                close=live_bar.close,
                volume=live_bar.volume,
                symbol=symbol,
            )
            if not accepted:
                self._duplicate_bars_skipped += 1
                return

            self._update_symbol_diagnostics(symbol=symbol, ts=live_bar.ts)
            self._write_bar(
                symbol=symbol,
                timeframe="1m",
                ts=live_bar.ts,
                open_=live_bar.open,
                high=live_bar.high,
                low=live_bar.low,
                close=live_bar.close,
                volume=live_bar.volume,
            )

            timeframes = self._timeframes_by_symbol.get(symbol, [])
            if self.settings.strategy.strict_routing and not timeframes:
                raise RuntimeError(
                    "Strict routing violation: no live execution timeframes for "
                    f"{symbol}"
                )
            for timeframe in timeframes:
                if timeframe == "1m":
                    self._bars_processed += 1
                    self._process_strategy_bar(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=live_bar.ts,
                        open_=live_bar.open,
                        high=live_bar.high,
                        low=live_bar.low,
                        close=live_bar.close,
                        volume=live_bar.volume,
                        source=live_bar.source,
                        persist_bar=False,
                    )
                    continue

                aggregator = self._aggregators_by_key.get((symbol, timeframe))
                if aggregator is None:
                    raise RuntimeError(
                        f"Missing live aggregator for execution pair {symbol}/{timeframe}"
                    )
                completed_bar = aggregator.update(
                    ts=live_bar.ts,
                    open_=live_bar.open,
                    high=live_bar.high,
                    low=live_bar.low,
                    close=live_bar.close,
                    volume=live_bar.volume,
                )
                if completed_bar is None:
                    continue
                self._bars_processed += 1
                self._process_strategy_bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=to_utc_timestamp(completed_bar["ts"]),
                    open_=float(completed_bar["open"]),
                    high=float(completed_bar["high"]),
                    low=float(completed_bar["low"]),
                    close=float(completed_bar["close"]),
                    volume=float(completed_bar["volume"]),
                    source=live_bar.source,
                    persist_bar=True,
                )
            self._reconcile_if_due()
            self._persist_live_state()
            self._emit_progress()

    def _process_strategy_bar(
        self,
        symbol: str,
        timeframe: str,
        ts: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        source: str,
        persist_bar: bool = True,
    ) -> None:
        if persist_bar:
            self._write_bar(
                symbol=symbol,
                timeframe=timeframe,
                ts=ts,
                open_=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )

        key = (symbol, timeframe)
        history_buffer = self._history_by_key.get(key)
        if history_buffer is None:
            history_buffer = RollingBarBuffer(self._history_window)
            self._history_by_key[key] = history_buffer
        history_buffer.append(
            ts=ts,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            label=f"{symbol}/{timeframe}",
        )
        history = history_buffer.to_frame()

        bar = BarEvent(
            symbol=symbol,
            timeframe=timeframe,
            ts=ts.to_pydatetime(),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
        )
        self._proxy_prices[symbol] = close

        sma_states = self._sma_engine.update(
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
        route_contexts = self._detector.build_route_contexts(
            bar=bar,
            sma_states=sma_states,
        )
        route_contexts_by_route_id = {
            context.route.id: context for context in route_contexts
        }
        for route_context in route_contexts:
            self._latest_context_by_route_id[route_context.route.id] = (
                to_utc_timestamp(bar.ts),
                route_context,
            )
        new_strikes, detected_signals = self._detector.detect(
            bar=bar,
            sma_states=sma_states,
            history=history,
            session_type="regular",
            cross_context_lookup=self._cross_context_lookup,
        )
        prepared_pairs: list[tuple[StrikeEvent, SignalEvent]] = []
        for strike, signal in zip(new_strikes, detected_signals, strict=True):
            prepared_signal = self._risk_manager.prepare_signal_for_entry(
                signal=signal,
                route_history=history,
            )
            if prepared_signal.id in self._known_signal_ids:
                continue
            prepared_pairs.append((strike, prepared_signal))
        new_strikes = [pair[0] for pair in prepared_pairs]
        new_signals = [pair[1] for pair in prepared_pairs]

        active_positions = self._active_positions_by_key.get(key, [])
        position_events: list[PositionEvent] = []
        for signal in new_signals:
            opened_position = self._risk_manager.open_position(
                signal,
                symbol=symbol,
                ts=bar.ts,
                route_context=route_contexts_by_route_id.get(signal.route_id),
                cross_context_lookup=self._cross_context_lookup,
            )
            active_positions.append(opened_position)
            position_events.append(self._risk_manager.open_event(opened_position, ts=bar.ts))

        archive_records: list[ArchiveRecord] = []
        for strike, signal in zip(new_strikes, new_signals, strict=True):
            if self.settings.archive.enabled:
                archive_records.append(self._archive_signal(strike=strike, signal=signal))

        next_positions: list[ManagedPosition] = []
        for position in active_positions:
            events = self._risk_manager.evaluate_bar(
                position,
                bar=bar,
                proxy_prices=self._proxy_prices,
                route_context=route_contexts_by_route_id.get(position.route_id),
                route_history=history,
                cross_context_lookup=self._cross_context_lookup,
            )
            position_events.extend(events)
            if not position.closed:
                next_positions.append(position)
        self._active_positions_by_key[key] = next_positions

        self._persist_events("strikes", new_strikes)
        self._persist_events("signals", new_signals)
        self._persist_events("positions", position_events)
        self._persist_events("archive", archive_records)

    def _persist_events(self, name: str, events: list[Any]) -> None:
        if not events:
            return

        unique_records: list[dict[str, Any]] = []
        seen = self._event_ids[name]
        for event in events:
            event_id = _event_identity(event)
            if event_id in seen:
                continue
            seen.add(event_id)
            unique_records.append(event_to_record(event))
            if name == "strikes":
                self._strikes.append(event)
            elif name == "signals":
                self._signals.append(event)
                self._known_signal_ids.add(event.id)
            elif name == "positions":
                self._position_events.append(event)
            elif name == "archive":
                self._archive_records.append(event)
        if unique_records:
            self.storage.append_events(name, unique_records)

    def _write_bar(
        self,
        symbol: str,
        timeframe: str,
        ts: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        frame = pd.DataFrame(
            [
                {
                    "ts": ts,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            ]
        )
        self.storage.write_bars(
            frame,
            symbol=symbol,
            timeframe=timeframe,
            timezone=self.settings.sessions.timezone,
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

    def _prime_warmup_state(
        self,
        symbols: list[str],
        timeframes_by_symbol: dict[str, list[str]],
        warmup_minutes: int,
    ) -> None:
        end = pd.Timestamp.now(tz="UTC").floor("min") - pd.Timedelta(minutes=1)
        start = end - pd.Timedelta(minutes=warmup_minutes)
        if start >= end:
            raise RuntimeError("Invalid live warmup range: start must be earlier than end")

        if self.settings.sessions.regular_only and not self.settings.sessions.extended_enabled:
            if any(
                market_for_symbol(symbol, self.settings.universe.symbol_markets) == "stocks"
                for symbol in symbols
            ):
                self._ensure_calendar_sessions_for_range(start=start, end=end)

        for symbol in symbols:
            symbol_market = market_for_symbol(symbol, self.settings.universe.symbol_markets)
            fetched = self.rest_client.fetch_bars(
                symbol=symbol,
                start=start,
                end=end,
                timeframe="1m",
                market=symbol_market,
            )
            if (
                self.settings.sessions.regular_only
                and not self.settings.sessions.extended_enabled
                and symbol_market == "stocks"
            ):
                fetched = apply_regular_session_filter(
                    fetched,
                    session_windows=self._session_windows_by_date,
                    timezone=self.settings.sessions.timezone,
                )

            if fetched.empty:
                raise RuntimeError(
                    f"No warmup bars available for {symbol} after session filtering"
                )

            normalized = fetched.loc[:, ["ts", "open", "high", "low", "close", "volume"]].copy()
            normalized["ts"] = pd.to_datetime(normalized["ts"], utc=True)
            normalized = normalized.sort_values("ts").drop_duplicates(subset=["ts"])
            normalized = normalized.reset_index(drop=True)
            source_window = SourceBarWindow(self._source_window)
            source_window.load_frame(normalized, symbol=symbol)
            self._source_windows_by_symbol[symbol] = source_window
            self._proxy_prices[symbol] = float(normalized.iloc[-1]["close"])

            for timeframe in timeframes_by_symbol.get(symbol, []):
                if timeframe == "1m":
                    frame = normalized
                    if frame.empty:
                        continue
                    for row in frame.itertuples(index=False):
                        ts = to_utc_timestamp(row.ts)
                        self._prime_strategy_bar(
                            symbol=symbol,
                            timeframe=timeframe,
                            ts=ts,
                            open_=float(row.open),
                            high=float(row.high),
                            low=float(row.low),
                            close=float(row.close),
                            volume=float(row.volume),
                        )
                    continue

                aggregator = self._aggregators_by_key.get((symbol, timeframe))
                if aggregator is None:
                    raise RuntimeError(
                        f"Missing warmup aggregator for execution pair {symbol}/{timeframe}"
                    )
                for row in normalized.itertuples(index=False):
                    completed_bar = aggregator.update(
                        ts=row.ts,
                        open_=float(row.open),
                        high=float(row.high),
                        low=float(row.low),
                        close=float(row.close),
                        volume=float(row.volume),
                    )
                    if completed_bar is None:
                        continue
                    ts = to_utc_timestamp(completed_bar["ts"])
                    self._prime_strategy_bar(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=ts,
                        open_=float(completed_bar["open"]),
                        high=float(completed_bar["high"]),
                        low=float(completed_bar["low"]),
                        close=float(completed_bar["close"]),
                        volume=float(completed_bar["volume"]),
                    )

    def _prime_strategy_bar(
        self,
        symbol: str,
        timeframe: str,
        ts: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        key = (symbol, timeframe)
        history_buffer = self._history_by_key.get(key)
        if history_buffer is None:
            history_buffer = RollingBarBuffer(self._history_window)
            self._history_by_key[key] = history_buffer
        history_buffer.append(
            ts=ts,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            label=f"{symbol}/{timeframe}",
        )
        self._sma_engine.update(
            symbol=symbol,
            timeframe=timeframe,
            ts=ts.to_pydatetime(),
            source_value=strategy_source_value(
                open_=open_,
                high=high,
                low=low,
                close=close,
                price_basis=self.settings.strategy.price_basis,
            ),
        )

    def _default_stream_factory(self, market: str, symbols: list[str]) -> AsyncIterator[LiveBar]:
        stream = AlpacaWebSocketBarStream(
            config=self.settings.alpaca,
            market=market,
            symbols=symbols,
            stale_feed_seconds=self.settings.live.stale_feed_seconds,
            heartbeat_interval_seconds=self.settings.live.heartbeat_interval_seconds,
            heartbeat_timeout_seconds=self.settings.live.heartbeat_timeout_seconds,
        )
        return stream.stream_bars()

    def _initialize_timeframe_aggregators(
        self,
        execution_pairs: list[tuple[str, str]],
    ) -> None:
        self._aggregators_by_key = {}
        for symbol, timeframe in execution_pairs:
            if timeframe == "1m":
                continue
            self._aggregators_by_key[(symbol, timeframe)] = IncrementalTimeframeAggregator(
                timeframe=timeframe,
                timezone=self.settings.sessions.timezone,
                anchors=self.settings.timeframes.anchors,
            )

    def _cross_context_lookup(
        self,
        reference_route_id: str,
        ts: datetime,
    ) -> RouteBarContext | None:
        cached = self._latest_context_by_route_id.get(reference_route_id)
        if cached is None:
            return None
        cached_ts, context = cached
        if cached_ts <= to_utc_timestamp(ts):
            return context
        return None

    def _split_market_symbols(self, symbols: list[str]) -> list[tuple[str, list[str]]]:
        groups_by_market: dict[str, list[str]] = {"stocks": [], "crypto": []}
        for symbol in symbols:
            market = market_for_symbol(symbol, self.settings.universe.symbol_markets)
            groups_by_market[market].append(symbol)
        groups: list[tuple[str, list[str]]] = []
        if groups_by_market["stocks"]:
            groups.append(("stocks", groups_by_market["stocks"]))
        if groups_by_market["crypto"]:
            groups.append(("crypto", groups_by_market["crypto"]))
        return groups

    def _resolve_state_path(self) -> Path:
        configured = self.settings.live.state_file
        if configured is not None:
            return Path(configured)
        return self.storage.root / "live_state.json"

    def _load_persisted_event_ids(self) -> None:
        for event_name in list(self._event_ids.keys()):
            rows = self.storage.load_events(event_name)
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError(
                        f"Persisted event row must be a dict for {event_name}: {type(row)}"
                    )
                event_id: str | None = None
                if "id" in row:
                    event_id = str(row["id"])
                elif "signal_id" in row:
                    event_id = str(row["signal_id"])
                if event_id is None or not event_id:
                    raise RuntimeError(
                        f"Persisted {event_name} row missing id/signal_id: {row}"
                    )
                self._event_ids[event_name].add(event_id)
                if event_name == "signals":
                    self._known_signal_ids.add(event_id)

    def _load_persisted_live_state(self) -> None:
        if not self.settings.live.state_persistence_enabled:
            return
        payload = self._state_store.load()
        if payload is None:
            return
        version = payload.get("version")
        if version != 1:
            raise RuntimeError(
                f"Unsupported live state version in {self._state_store.path}: {version!r}"
            )
        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise RuntimeError(
                f"Live state fingerprint missing or invalid in {self._state_store.path}"
            )
        if fingerprint != self._state_fingerprint:
            raise RuntimeError(
                "Live state fingerprint mismatch; remove stale state file before running: "
                f"{self._state_store.path}"
            )

        proxy_prices = payload.get("proxy_prices")
        if proxy_prices is not None:
            if not isinstance(proxy_prices, dict):
                raise RuntimeError(
                    f"Live state proxy_prices must be dict in {self._state_store.path}"
                )
            self._proxy_prices = {
                str(symbol).upper(): float(price)
                for symbol, price in proxy_prices.items()
            }

        raw_positions = payload.get("active_positions", [])
        if not isinstance(raw_positions, list):
            raise RuntimeError(
                f"Live state active_positions must be list in {self._state_store.path}"
            )
        restored_positions = 0
        for row in raw_positions:
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"Live state position row must be dict in {self._state_store.path}"
                )
            key = (str(row["symbol"]).upper(), str(row["timeframe"]))
            selected_timeframes = self._timeframes_by_symbol.get(key[0], [])
            if key[1] not in selected_timeframes:
                continue
            position = _position_from_state(row)
            self._active_positions_by_key.setdefault(key, []).append(position)
            self._known_signal_ids.add(position.signal_id)
            restored_positions += 1
        if restored_positions:
            self._logger.info("Restored %d active positions from live state", restored_positions)

    def _persist_live_state(self, force: bool = False) -> None:
        if not self.settings.live.state_persistence_enabled:
            return
        now = monotonic()
        if (
            not force
            and (now - self._last_state_flush) < self.settings.live.state_flush_interval_seconds
        ):
            return
        self._last_state_flush = now

        active_rows: list[dict[str, Any]] = []
        for (symbol, timeframe), positions in sorted(self._active_positions_by_key.items()):
            for position in positions:
                if position.closed:
                    continue
                active_rows.append(
                    _position_to_state_row(
                        position=position,
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                )

        payload: dict[str, Any] = {
            "version": 1,
            "fingerprint": self._state_fingerprint,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "active_positions": active_rows,
            "proxy_prices": dict(sorted(self._proxy_prices.items())),
        }
        self._state_store.save(payload)

    def _update_symbol_diagnostics(self, *, symbol: str, ts: pd.Timestamp) -> None:
        ts_utc = to_utc_timestamp(ts)
        previous_ts = self._last_bar_ts_by_symbol.get(symbol)
        if previous_ts is not None:
            gap_seconds = (ts_utc - previous_ts).total_seconds()
            if gap_seconds > float(self.settings.live.data_gap_threshold_seconds):
                self._data_gaps_detected += 1
                self._logger.warning(
                    "Detected live data gap for %s: %.1fs between bars (%s -> %s)",
                    symbol,
                    gap_seconds,
                    previous_ts.isoformat(),
                    ts_utc.isoformat(),
                )
        self._last_bar_ts_by_symbol[symbol] = ts_utc
        if self._latest_ts_seen is None or ts_utc > self._latest_ts_seen:
            self._latest_ts_seen = ts_utc
        self._recompute_stale_symbols()

    def _recompute_stale_symbols(self) -> None:
        if self._latest_ts_seen is None:
            self._stale_symbols = set()
            return
        stale: set[str] = set()
        threshold = float(self.settings.live.symbol_stale_threshold_seconds)
        for symbol in self._selected_symbols:
            last_ts = self._last_bar_ts_by_symbol.get(symbol)
            if last_ts is None:
                continue
            lag_seconds = (self._latest_ts_seen - last_ts).total_seconds()
            if lag_seconds > threshold:
                stale.add(symbol)
        newly_stale = stale.difference(self._stale_symbols)
        if newly_stale:
            self._stale_symbol_warnings += len(newly_stale)
        self._stale_symbols = stale

    def _reconcile_if_due(self) -> None:
        if not self.settings.live.reconciliation_enabled:
            return
        now = monotonic()
        if (now - self._last_reconciliation_at) < self.settings.live.reconciliation_interval_seconds:
            return
        self._last_reconciliation_at = now
        self._run_reconciliation()

    def _run_reconciliation(self) -> None:
        broker_positions = self.rest_client.fetch_open_positions()
        broker_orders = self.rest_client.fetch_open_orders()
        self._reconciliation_checks += 1

        local_symbols: set[str] = set()
        for positions in self._active_positions_by_key.values():
            for position in positions:
                if not position.closed:
                    local_symbols.add(position.symbol.upper())
        broker_symbols = {
            str(row["symbol"]).upper()
            for row in broker_positions
            if isinstance(row, dict) and "symbol" in row
        }
        order_symbols = {
            str(row["symbol"]).upper()
            for row in broker_orders
            if isinstance(row, dict) and "symbol" in row
        }

        missing_on_broker = sorted(local_symbols.difference(broker_symbols))
        unexpected_on_broker = sorted(broker_symbols.difference(local_symbols))
        mismatch = bool(missing_on_broker or unexpected_on_broker)
        if mismatch:
            self._reconciliation_mismatches += 1
            self._logger.warning(
                "Paper reconciliation mismatch: missing_on_broker=%s unexpected_on_broker=%s",
                missing_on_broker,
                unexpected_on_broker,
            )
        self._last_reconciliation = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "local_open_symbols": sorted(local_symbols),
            "broker_open_symbols": sorted(broker_symbols),
            "broker_open_order_symbols": sorted(order_symbols),
            "missing_on_broker": missing_on_broker,
            "unexpected_on_broker": unexpected_on_broker,
            "mismatch": mismatch,
        }

    def _reset_state(self) -> None:
        self._source_windows_by_symbol: dict[str, SourceBarWindow] = {}
        self._history_by_key: dict[tuple[str, str], RollingBarBuffer] = {}
        self._aggregators_by_key: dict[tuple[str, str], IncrementalTimeframeAggregator] = {}
        self._latest_context_by_route_id: dict[str, tuple[pd.Timestamp, RouteBarContext]] = {}
        self._active_positions_by_key: dict[tuple[str, str], list[ManagedPosition]] = {}
        self._timeframes_by_symbol: dict[str, list[str]] = {}
        self._selected_symbols: list[str] = []
        self._proxy_prices: dict[str, float] = {}
        self._session_windows_by_date: dict[str, tuple[pd.Timestamp, pd.Timestamp] | None] = {}
        self._known_signal_ids: set[str] = set()

        self._event_ids: dict[str, set[str]] = {
            "strikes": set(),
            "signals": set(),
            "positions": set(),
            "archive": set(),
        }
        self._strikes: list[StrikeEvent] = []
        self._signals: list[SignalEvent] = []
        self._position_events: list[PositionEvent] = []
        self._archive_records: list[ArchiveRecord] = []

        self._bars_received = 0
        self._bars_processed = 0
        self._duplicate_bars_skipped = 0
        self._reconnects = 0
        self._stale_feed_reconnects = 0
        self._heartbeat_failures = 0
        self._data_gaps_detected = 0
        self._stale_symbol_warnings = 0
        self._stale_symbols: set[str] = set()
        self._last_bar_ts_by_symbol: dict[str, pd.Timestamp] = {}
        self._latest_ts_seen: pd.Timestamp | None = None
        self._reconciliation_checks = 0
        self._reconciliation_mismatches = 0
        self._last_reconciliation: dict[str, Any] | None = None
        self._last_reconciliation_at = 0.0
        self._last_state_flush = 0.0
        self._started_at = datetime.now(timezone.utc)
        self._progress_callback: LiveProgressCallback | None = None
        self._last_progress_emit = 0.0

    def _emit_progress(self, force: bool = False, status: str | None = None) -> None:
        if self._progress_callback is None:
            return
        now = monotonic()
        if not force and (now - self._last_progress_emit) < 1.0:
            return
        self._last_progress_emit = now
        payload: dict[str, Any] = {
            "status": status if status is not None else "running",
            "bars_received": self._bars_received,
            "bars_processed": self._bars_processed,
            "duplicate_bars_skipped": self._duplicate_bars_skipped,
            "reconnects": self._reconnects,
            "stale_feed_reconnects": self._stale_feed_reconnects,
            "heartbeat_failures": self._heartbeat_failures,
            "data_gaps_detected": self._data_gaps_detected,
            "stale_symbol_warnings": self._stale_symbol_warnings,
            "stale_symbols": sorted(self._stale_symbols),
            "reconciliation_checks": self._reconciliation_checks,
            "reconciliation_mismatches": self._reconciliation_mismatches,
            "uptime_seconds": max(
                0.0,
                (datetime.now(timezone.utc) - self._started_at).total_seconds(),
            ),
        }
        if self._last_reconciliation is not None:
            payload["last_reconciliation"] = dict(self._last_reconciliation)
        self._progress_callback(payload)

    def _init_pipeline_components(self) -> None:
        self._detector = StrikeDetector(
            outfits=self._outfits,
            routes=self.settings.strategy.routes,
            strict_routing=self.settings.strategy.strict_routing,
            tolerance=self.settings.signal.tolerance,
            trigger_mode=self.settings.strategy.trigger_mode,
        )
        periods = sorted(self._detector.required_periods())
        if not periods:
            periods = sorted({period for outfit in self._outfits for period in outfit.periods})
        self._sma_engine = SMAEngine(periods)
        self._history_window = max(64, max(periods, default=2) + 8)
        self._source_window = max(10_000, self._history_window * 16)
        self._risk_manager = RiskManager(
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

    def _ensure_calendar_sessions_for_range(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> None:
        sessions = self.rest_client.fetch_calendar_sessions(
            start=start,
            end=end,
            timezone=self.settings.sessions.timezone,
        )
        self._session_windows_by_date.update(sessions)

    def _ensure_calendar_sessions_for_timestamp(self, ts: pd.Timestamp) -> None:
        date_key = ensure_utc_timestamp(ts).tz_convert(self.settings.sessions.timezone).strftime(
            "%Y-%m-%d"
        )
        if date_key in self._session_windows_by_date:
            return
        self._ensure_calendar_sessions_for_range(start=ts, end=ts)

def _event_identity(event: Any) -> str:
    if hasattr(event, "id"):
        return str(getattr(event, "id"))
    if hasattr(event, "signal_id"):
        return str(getattr(event, "signal_id"))
    raise ValueError(f"Unsupported event type for idempotent persistence: {type(event)}")


def _position_to_state_row(
    *,
    position: ManagedPosition,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    return {
        "signal_id": position.signal_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": position.side,
        "entry": float(position.entry),
        "stop": float(position.stop),
        "opened_ts": pd.Timestamp(position.opened_ts).isoformat(),
        "route_id": position.route_id,
        "remaining_qty": float(position.remaining_qty),
        "closed": bool(position.closed),
        "reference_break_rules": [
            {
                "symbol": rule.symbol,
                "level": float(rule.level),
                "threshold": float(rule.threshold),
                "mode": rule.mode,
                "source_route_id": rule.source_route_id,
            }
            for rule in position.reference_break_rules
        ],
        "current_reference_price": (
            float(position.current_reference_price)
            if position.current_reference_price is not None
            else None
        ),
        "buy_hold_optimized": bool(position.buy_hold_optimized),
        "last_reference_session": position.last_reference_session,
    }


def _position_from_state(row: dict[str, Any]) -> ManagedPosition:
    reference_rules_raw = row.get("reference_break_rules", [])
    if not isinstance(reference_rules_raw, list):
        raise RuntimeError("live state position.reference_break_rules must be a list")
    reference_break_rules: list[ReferenceBreakRule] = []
    for raw_rule in reference_rules_raw:
        if not isinstance(raw_rule, dict):
            raise RuntimeError("live state reference_break_rules entries must be dict rows")
        mode = str(raw_rule.get("mode"))
        if mode not in {"below", "above"}:
            raise RuntimeError(f"live state reference break mode invalid: {mode!r}")
        reference_break_rules.append(
            ReferenceBreakRule(
                symbol=str(raw_rule["symbol"]).upper(),
                level=float(raw_rule["level"]),
                threshold=float(raw_rule["threshold"]),
                mode=mode,  # type: ignore[arg-type]
                source_route_id=str(raw_rule["source_route_id"]),
            )
        )

    opened_ts = ensure_utc_timestamp(str(row["opened_ts"])).to_pydatetime()
    return ManagedPosition(
        signal_id=str(row["signal_id"]),
        symbol=str(row["symbol"]).upper(),
        side=str(row["side"]),
        entry=float(row["entry"]),
        stop=float(row["stop"]),
        opened_ts=opened_ts,
        route_id=str(row["route_id"]),
        remaining_qty=float(row.get("remaining_qty", 1.0)),
        closed=bool(row.get("closed", False)),
        reference_break_rules=tuple(reference_break_rules),
        current_reference_price=(
            float(row["current_reference_price"])
            if row.get("current_reference_price") is not None
            else None
        ),
        buy_hold_optimized=bool(row.get("buy_hold_optimized", False)),
        last_reference_session=(
            str(row["last_reference_session"])
            if row.get("last_reference_session") is not None
            else None
        ),
    )


def _state_fingerprint(settings: Settings) -> str:
    fingerprint_payload = {
        "strategy": settings.strategy.model_dump(mode="json"),
        "risk": settings.risk.model_dump(mode="json"),
        "sessions": settings.sessions.model_dump(mode="json"),
        "universe": {
            "symbols": list(settings.universe.symbols),
            "symbol_markets": dict(settings.universe.symbol_markets),
        },
        "timeframes": settings.timeframes.model_dump(mode="json"),
    }
    serialized = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
