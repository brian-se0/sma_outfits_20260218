from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import pandas as pd

from sma_outfits.archive.charts import write_signal_chart
from sma_outfits.archive.thread_writer import append_thread_markdown
from sma_outfits.config.models import Settings
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
from sma_outfits.signals.classifier import SignalClassifier
from sma_outfits.signals.detector import StrikeDetector, load_outfits
from sma_outfits.utils import is_crypto_symbol, is_regular_session

LiveStreamFactory = Callable[[str, list[str]], AsyncIterator[LiveBar]]


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
        self._outfit_periods = {
            outfit.outfit_id: list(outfit.periods) for outfit in self._outfits
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
    ) -> LiveRunResult:
        self._reset_state()
        self._stop_event.clear()
        self._init_pipeline_components()
        self._started_at = datetime.now(timezone.utc)

        selected_symbols = symbols or self.settings.universe.symbols
        selected_timeframes = timeframes or self.settings.timeframes.live
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
                selected_timeframes,
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
                    timeframes=selected_timeframes,
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
        timeframes: list[str],
    ) -> None:
        attempts = 0
        while not self._stop_event.is_set():
            try:
                async for live_bar in self._stream_factory(market, symbols):
                    if self._stop_event.is_set():
                        return
                    attempts = 0
                    await self._handle_live_bar(live_bar, timeframes)

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
                await asyncio.sleep(delay)
            except Exception as exc:
                raise RuntimeError(f"Fatal error in {market} live stream: {exc}") from exc

    async def _handle_live_bar(self, live_bar: LiveBar, timeframes: list[str]) -> None:
        async with self._lock:
            self._bars_received += 1
            symbol = live_bar.symbol.upper()
            if (
                self.settings.sessions.regular_only
                and not self.settings.sessions.extended_enabled
                and not is_crypto_symbol(symbol)
                and not is_regular_session(
                    live_bar.ts,
                    timezone=self.settings.sessions.timezone,
                )
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

        appended = pd.concat(
            [
                frame,
                pd.DataFrame(
                    [
                        {
                            "ts": live_bar.ts,
                            "open": live_bar.open,
                            "high": live_bar.high,
                            "low": live_bar.low,
                            "close": live_bar.close,
                            "volume": live_bar.volume,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        appended["ts"] = pd.to_datetime(appended["ts"], utc=True)
        appended = appended.sort_values("ts").reset_index(drop=True)
        self._source_1m_by_symbol[symbol] = appended
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
        history = self._history_by_key.get(key)
        if history is None:
            history = _empty_bar_frame()
        history = pd.concat(
            [
                history,
                pd.DataFrame(
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
                ),
            ],
            ignore_index=True,
        )
        history["ts"] = pd.to_datetime(history["ts"], utc=True)
        history = history.sort_values("ts").drop_duplicates(subset=["ts"])
        if len(history) > 5000:
            history = history.iloc[-5000:].reset_index(drop=True)
        else:
            history = history.reset_index(drop=True)
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
            close=bar.close,
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
                archive_records.append(
                    self._archive_signal(
                        bars=history.tail(250).copy(),
                        strike=strike,
                        signal=signal,
                    )
                )

        position_events: list[PositionEvent] = []
        next_positions: list[ManagedPosition] = []
        for position in active_positions:
            events = self._risk_manager.evaluate_bar(
                position,
                bar=bar,
                proxy_prices=self._proxy_prices,
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
        bars: pd.DataFrame,
        strike: StrikeEvent,
        signal: SignalEvent,
    ) -> ArchiveRecord:
        archive_root = Path(self.settings.archive.root)
        chart_path = archive_root / "charts" / f"{signal.id}.png"
        outfit_periods = self._outfit_periods.get(strike.outfit_id, [strike.period])
        write_signal_chart(
            bars=bars,
            strike=strike,
            signal=signal,
            outfit_periods=outfit_periods,
            output_path=chart_path,
        )
        markdown_path = append_thread_markdown(
            root=archive_root / "threads",
            strike=strike,
            signal=signal,
            chart_path=chart_path,
        )
        caption = (
            f"{strike.symbol} {strike.timeframe} {signal.signal_type} at {strike.sma_value:.2f} "
            f"(MA{strike.period}, outfit {strike.outfit_id})"
        )
        return ArchiveRecord(
            signal_id=signal.id,
            chart_path=str(chart_path),
            markdown_path=str(markdown_path),
            caption=caption,
            ts=strike.bar_ts,
        )

    def _prime_warmup_state(
        self,
        symbols: list[str],
        timeframes: list[str],
        warmup_minutes: int,
    ) -> None:
        end = pd.Timestamp.now(tz="UTC").floor("min") - pd.Timedelta(minutes=1)
        start = end - pd.Timedelta(minutes=warmup_minutes)
        if start >= end:
            raise RuntimeError("Invalid live warmup range: start must be earlier than end")

        for symbol in symbols:
            fetched = self.rest_client.fetch_bars(
                symbol=symbol,
                start=start,
                end=end,
                timeframe="1m",
            )
            if (
                self.settings.sessions.regular_only
                and not self.settings.sessions.extended_enabled
                and not is_crypto_symbol(symbol)
            ):
                local = fetched.copy()
                local["ts"] = pd.to_datetime(local["ts"], utc=True)
                mask = local["ts"].map(
                    lambda ts: is_regular_session(ts, timezone=self.settings.sessions.timezone)
                )
                fetched = local.loc[mask].reset_index(drop=True)

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
            for timeframe in timeframes:
                if timeframe == "1m":
                    frame = normalized
                else:
                    frame = resample_ohlcv(
                        normalized,
                        timeframe=timeframe,
                        timezone=self.settings.sessions.timezone,
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
        history = self._history_by_key.get(key)
        if history is None:
            history = _empty_bar_frame()
        history = pd.concat(
            [
                history,
                pd.DataFrame(
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
                ),
            ],
            ignore_index=True,
        )
        history["ts"] = pd.to_datetime(history["ts"], utc=True)
        history = history.sort_values("ts").drop_duplicates(subset=["ts"])
        if len(history) > 5000:
            history = history.iloc[-5000:].reset_index(drop=True)
        else:
            history = history.reset_index(drop=True)
        self._history_by_key[key] = history
        self._sma_engine.update(
            symbol=symbol,
            timeframe=timeframe,
            ts=ts.to_pydatetime(),
            close=close,
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

    @staticmethod
    def _split_market_symbols(symbols: list[str]) -> list[tuple[str, list[str]]]:
        stocks = [symbol for symbol in symbols if not is_crypto_symbol(symbol)]
        crypto = [symbol for symbol in symbols if is_crypto_symbol(symbol)]
        groups: list[tuple[str, list[str]]] = []
        if stocks:
            groups.append(("stocks", stocks))
        if crypto:
            groups.append(("crypto", crypto))
        return groups

    @staticmethod
    def _resolve_outfits_path(outfits_path: str) -> Path:
        candidate = Path(outfits_path)
        if candidate.exists():
            return candidate
        package_default = Path(__file__).resolve().parents[1] / "config" / "outfits.yaml"
        if package_default.exists():
            return package_default
        raise FileNotFoundError(
            "Unable to resolve outfits catalog. Checked: "
            f"{candidate} and {package_default}"
        )

    def _reset_state(self) -> None:
        self._source_1m_by_symbol: dict[str, pd.DataFrame] = {}
        self._history_by_key: dict[tuple[str, str], pd.DataFrame] = {}
        self._active_positions_by_key: dict[tuple[str, str], list[ManagedPosition]] = {}
        self._proxy_prices: dict[str, float] = {}
        self._last_processed_ts: dict[tuple[str, str], pd.Timestamp] = {}

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

    def _init_pipeline_components(self) -> None:
        periods = sorted({period for outfit in self._outfits for period in outfit.periods})
        self._sma_engine = SMAEngine(periods)
        classifier = SignalClassifier(
            volatility_threshold=self.settings.signal.volatility_percentile_threshold
        )
        self._detector = StrikeDetector(
            outfits=self._outfits,
            tolerance=self.settings.signal.tolerance,
            trigger_mode=self.settings.signal.trigger_mode,
            long_break=self.settings.risk.long_break,
            short_break=self.settings.risk.short_break,
            classifier=classifier,
        )
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
        )


def _empty_bar_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])


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
