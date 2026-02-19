from __future__ import annotations

import asyncio
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
from sma_outfits.data.resample import resample_ohlcv
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

        outfits_path = self._resolve_outfits_path(settings.outfits_path)
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
        execution_pairs = self._resolve_execution_pairs(
            symbols=selected_symbols,
            timeframes=selected_timeframes,
        )
        self._timeframes_by_symbol = _timeframes_by_symbol(execution_pairs)
        selected_symbols = list(self._timeframes_by_symbol.keys())
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

            accepted = self._append_source_bar(symbol, live_bar)
            if not accepted:
                self._duplicate_bars_skipped += 1
                return

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
                next_bar = self._next_completed_timeframe_bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    source_ts=live_bar.ts,
                )
                if next_bar is None:
                    continue
                self._bars_processed += 1
                self._process_strategy_bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=next_bar["ts"],
                    open_=next_bar["open"],
                    high=next_bar["high"],
                    low=next_bar["low"],
                    close=next_bar["close"],
                    volume=next_bar["volume"],
                    source=live_bar.source,
                    persist_bar=timeframe != "1m",
                )
            self._emit_progress()

    def _append_source_bar(self, symbol: str, live_bar: LiveBar) -> bool:
        frame = self._source_1m_by_symbol.get(symbol)
        if frame is None:
            frame = _empty_bar_frame()

        existing = frame.loc[frame["ts"] == live_bar.ts]
        if not existing.empty:
            row = existing.iloc[-1]
            if _bar_matches(
                row,
                live_bar.open,
                live_bar.high,
                live_bar.low,
                live_bar.close,
                live_bar.volume,
            ):
                return False
            raise RuntimeError(
                "Conflicting duplicate bar detected for "
                f"{symbol} at {live_bar.ts.isoformat()}"
            )

        if not frame.empty:
            last_ts = pd.Timestamp(frame["ts"].iloc[-1]).tz_convert("UTC")
            if live_bar.ts < last_ts:
                raise RuntimeError(
                    f"Non-monotonic live bar timestamp for {symbol}: "
                    f"{live_bar.ts.isoformat()} < {last_ts.isoformat()}"
                )

        frame.loc[len(frame)] = {
            "ts": live_bar.ts,
            "open": live_bar.open,
            "high": live_bar.high,
            "low": live_bar.low,
            "close": live_bar.close,
            "volume": live_bar.volume,
        }
        if len(frame) > self._source_window:
            frame = frame.iloc[-self._source_window :].reset_index(drop=True)
        self._source_1m_by_symbol[symbol] = frame
        self._proxy_prices[symbol] = live_bar.close
        return True

    def _next_completed_timeframe_bar(
        self,
        symbol: str,
        timeframe: str,
        source_ts: pd.Timestamp,
    ) -> dict[str, float | pd.Timestamp] | None:
        frame = self._source_1m_by_symbol.get(symbol)
        if frame is None or frame.empty:
            return None

        if timeframe == "1m":
            candidate = frame.iloc[-1]
        else:
            resampled = resample_ohlcv(
                frame,
                timeframe=timeframe,
                timezone=self.settings.sessions.timezone,
                anchors=self.settings.timeframes.anchors,
            )
            if resampled.empty:
                return None
            candidate = resampled.iloc[-1]

        candidate_ts = pd.Timestamp(candidate["ts"]).tz_convert("UTC")
        if candidate_ts > source_ts:
            return None

        key = (symbol, timeframe)
        last_seen = self._last_processed_ts.get(key)
        if last_seen is not None:
            if candidate_ts < last_seen:
                raise RuntimeError(
                    "Non-monotonic resampled timestamp for "
                    f"{symbol}/{timeframe}: {candidate_ts.isoformat()} < {last_seen.isoformat()}"
                )
            if candidate_ts == last_seen:
                return None

        self._last_processed_ts[key] = candidate_ts
        return {
            "ts": candidate_ts,
            "open": float(candidate["open"]),
            "high": float(candidate["high"]),
            "low": float(candidate["low"]),
            "close": float(candidate["close"]),
            "volume": float(candidate["volume"]),
        }

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
        history = self._append_history(
            key=key,
            ts=ts,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        self._history_by_key[key] = history

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
            source_value=_strategy_source_value(
                open_=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                price_basis=self.settings.strategy.price_basis,
            ),
        )
        route_context = self._detector.build_route_context(
            bar=bar,
            sma_states=sma_states,
        )
        new_strikes, new_signals = self._detector.detect(
            bar=bar,
            sma_states=sma_states,
            history=history,
            session_type="regular",
        )

        active_positions = self._active_positions_by_key.get(key, [])
        for signal in new_signals:
            active_positions.append(
                self._risk_manager.open_position(signal, symbol=symbol, ts=bar.ts)
            )

        archive_records: list[ArchiveRecord] = []
        for strike, signal in zip(new_strikes, new_signals, strict=True):
            if self.settings.archive.enabled:
                archive_records.append(self._archive_signal(strike=strike, signal=signal))

        position_events: list[PositionEvent] = []
        next_positions: list[ManagedPosition] = []
        for position in active_positions:
            events = self._risk_manager.evaluate_bar(
                position,
                bar=bar,
                proxy_prices=self._proxy_prices,
                route_context=route_context,
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
            elif name == "positions":
                self._position_events.append(event)
            elif name == "archive":
                self._archive_records.append(event)
        if unique_records:
            self.storage.append_events(name, unique_records)

    def _append_history(
        self,
        key: tuple[str, str],
        ts: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> pd.DataFrame:
        history = self._history_by_key.get(key)
        if history is None:
            history = _empty_bar_frame()

        ts_utc = _to_utc_timestamp(ts)
        if not history.empty:
            last_ts = _to_utc_timestamp(history.iloc[-1]["ts"])
            if ts_utc <= last_ts:
                if ts_utc == last_ts:
                    raise RuntimeError(
                        f"Duplicate strategy bar for {key[0]}/{key[1]} at {ts_utc.isoformat()}"
                    )
                raise RuntimeError(
                    f"Non-monotonic strategy bar for {key[0]}/{key[1]}: "
                    f"{ts_utc.isoformat()} < {last_ts.isoformat()}"
                )

        history.loc[len(history)] = {
            "ts": ts_utc,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
        if len(history) > self._history_window:
            history = history.iloc[-self._history_window :].reset_index(drop=True)
        return history

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
            self._source_1m_by_symbol[symbol] = normalized
            self._proxy_prices[symbol] = float(normalized.iloc[-1]["close"])

            last_source_ts = pd.Timestamp(normalized.iloc[-1]["ts"]).tz_convert("UTC")
            for timeframe in timeframes_by_symbol.get(symbol, []):
                if timeframe == "1m":
                    frame = normalized
                else:
                    frame = resample_ohlcv(
                        normalized,
                        timeframe=timeframe,
                        timezone=self.settings.sessions.timezone,
                        anchors=self.settings.timeframes.anchors,
                    )
                if frame.empty:
                    continue
                for row in frame.itertuples(index=False):
                    ts = pd.Timestamp(row.ts).tz_convert("UTC")
                    if ts > last_source_ts:
                        continue
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
                    self._last_processed_ts[(symbol, timeframe)] = ts

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
        history = self._append_history(
            key=key,
            ts=ts,
            open_=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        self._history_by_key[key] = history
        self._sma_engine.update(
            symbol=symbol,
            timeframe=timeframe,
            ts=ts.to_pydatetime(),
            source_value=_strategy_source_value(
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

    def _reset_state(self) -> None:
        self._source_1m_by_symbol: dict[str, pd.DataFrame] = {}
        self._history_by_key: dict[tuple[str, str], pd.DataFrame] = {}
        self._active_positions_by_key: dict[tuple[str, str], list[ManagedPosition]] = {}
        self._timeframes_by_symbol: dict[str, list[str]] = {}
        self._proxy_prices: dict[str, float] = {}
        self._last_processed_ts: dict[tuple[str, str], pd.Timestamp] = {}
        self._session_windows_by_date: dict[str, tuple[pd.Timestamp, pd.Timestamp] | None] = {}

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
            "uptime_seconds": max(
                0.0,
                (datetime.now(timezone.utc) - self._started_at).total_seconds(),
            ),
        }
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
            migrations={
                symbol: migration.model_dump()
                for symbol, migration in self.settings.risk.migrations.items()
            },
            routes=self._routes_by_id,
            allow_same_bar_exit=self.settings.strategy.allow_same_bar_exit,
        )

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
                "Strict routing preflight failed for run-live: requested symbols/timeframes "
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
                "Strict routing preflight failed for run-live: requested values outside configured "
                "routes (" + "; ".join(details) + ")."
            )

        unique_pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pair in selected:
            if pair not in seen:
                seen.add(pair)
                unique_pairs.append(pair)
        return unique_pairs

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


def _empty_bar_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])


def _to_utc_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _bar_matches(
    row: pd.Series,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> bool:
    return (
        float(row["open"]) == float(open_)
        and float(row["high"]) == float(high)
        and float(row["low"]) == float(low)
        and float(row["close"]) == float(close)
        and float(row["volume"]) == float(volume)
    )


def _event_identity(event: Any) -> str:
    if hasattr(event, "id"):
        return str(getattr(event, "id"))
    if hasattr(event, "signal_id"):
        return str(getattr(event, "signal_id"))
    raise ValueError(f"Unsupported event type for idempotent persistence: {type(event)}")


def _timeframes_by_symbol(
    pairs: list[tuple[str, str]],
) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for symbol, timeframe in pairs:
        values = mapping.setdefault(symbol, [])
        if timeframe not in values:
            values.append(timeframe)
    return mapping


def _strategy_source_value(
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
