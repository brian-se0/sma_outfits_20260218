from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from sma_outfits.archive.thread_writer import append_thread_markdown
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
from sma_outfits.signals.classifier import SignalClassifier
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
        self._init_pipeline_components()

    def _init_pipeline_components(self) -> None:
        periods = sorted({period for outfit in self.outfits for period in outfit.periods})
        classifier = SignalClassifier(
            volatility_threshold=self.settings.signal.volatility_percentile_threshold
        )
        required_history = max(
            classifier.drawdown_window + 1,
            classifier.atr_window + classifier.volatility_window - 1,
        )
        self._history_window = max(64, required_history + 8)
        self.sma_engine = SMAEngine(periods)
        self.detector = StrikeDetector(
            outfits=self.outfits,
            tolerance=self.settings.signal.tolerance,
            trigger_mode=self.settings.signal.trigger_mode,
            long_break=self.settings.risk.long_break,
            short_break=self.settings.risk.short_break,
            classifier=classifier,
        )
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
        timeframes = timeframes or self.settings.all_timeframes

        strikes: list[StrikeEvent] = []
        signals: list[SignalEvent] = []
        position_events: list[PositionEvent] = []
        archive_records: list[ArchiveRecord] = []
        proxy_prices: dict[str, float] = {}
        jobs: list[tuple[str, str, pd.DataFrame]] = []
        total_bars = 0

        for symbol in symbols:
            for timeframe in timeframes:
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
                sma_states = self.sma_engine.update(
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    ts=bar.ts,
                    close=bar.close,
                )
                new_strikes, new_signals = self.detector.detect(
                    bar=bar,
                    sma_states=sma_states,
                    history=history,
                    session_type="regular",
                )
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


def _to_utc_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")
