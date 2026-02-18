from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from sma_outfits.archive.charts import write_signal_chart
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


class ReplayEngine:
    def __init__(self, settings: Settings, storage: StorageManager) -> None:
        self.settings = settings
        self.storage = storage
        outfits_path = self._resolve_outfits_path(settings.outfits_path)
        self.outfits = load_outfits(outfits_path)
        self.outfit_periods = {outfit.outfit_id: list(outfit.periods) for outfit in self.outfits}
        periods = sorted({period for outfit in self.outfits for period in outfit.periods})
        self.sma_engine = SMAEngine(periods)
        classifier = SignalClassifier(
            volatility_threshold=settings.signal.volatility_percentile_threshold
        )
        self.detector = StrikeDetector(
            outfits=self.outfits,
            tolerance=settings.signal.tolerance,
            trigger_mode=settings.signal.trigger_mode,
            long_break=settings.risk.long_break,
            short_break=settings.risk.short_break,
            classifier=classifier,
        )
        self.risk_manager = RiskManager(
            long_break=settings.risk.long_break,
            short_break=settings.risk.short_break,
            partial_take_r=settings.risk.partial_take_r,
            final_take_r=settings.risk.final_take_r,
            timeout_bars=settings.risk.timeout_bars,
            migrations={
                symbol: migration.model_dump()
                for symbol, migration in settings.risk.migrations.items()
            },
        )

    def run(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> ReplayResult:
        symbols = symbols or self.settings.universe.symbols
        timeframes = timeframes or self.settings.all_timeframes

        strikes: list[StrikeEvent] = []
        signals: list[SignalEvent] = []
        position_events: list[PositionEvent] = []
        archive_records: list[ArchiveRecord] = []
        has_data = False
        proxy_prices: dict[str, float] = {}

        for symbol in symbols:
            for timeframe in timeframes:
                bars = self.storage.read_bars(symbol, timeframe, start=start, end=end)
                if bars.empty:
                    continue
                has_data = True
                bars = bars.sort_values("ts").reset_index(drop=True)
                history = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
                active_positions: list[ManagedPosition] = []

                for index, row in bars.iterrows():
                    bar_ts = pd.Timestamp(row["ts"]).to_pydatetime()
                    bar = BarEvent(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts=bar_ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                        source="replay",
                    )
                    proxy_prices[symbol] = bar.close

                    history_ts = pd.Timestamp(bar.ts)
                    if history_ts.tzinfo is None:
                        history_ts = history_ts.tz_localize("UTC")
                    else:
                        history_ts = history_ts.tz_convert("UTC")
                    history.loc[len(history)] = {
                        "ts": history_ts,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
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
                            archive_records.append(
                                self._archive_signal(
                                    bars=bars.iloc[max(0, index - 250) : index + 1].copy(),
                                    strike=strike,
                                    signal=signal,
                                )
                            )

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

        if not has_data:
            raise RuntimeError("Replay aborted: no stored bars found for requested symbols/timeframes")

        summary = build_summary(strikes=strikes, signals=signals, position_events=position_events)
        self.storage.append_events("strikes", [event_to_record(event) for event in strikes])
        self.storage.append_events("signals", [event_to_record(event) for event in signals])
        self.storage.append_events("positions", [event_to_record(event) for event in position_events])
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
        bars: pd.DataFrame,
        strike: StrikeEvent,
        signal: SignalEvent,
    ) -> ArchiveRecord:
        archive_root = Path(self.settings.archive.root)
        chart_path = archive_root / "charts" / f"{signal.id}.png"
        outfit_periods = self.outfit_periods.get(strike.outfit_id, [strike.period])
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
