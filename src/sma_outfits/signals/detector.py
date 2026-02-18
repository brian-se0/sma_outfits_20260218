from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from sma_outfits.events import BarEvent, SMAState, SignalEvent, StrikeEvent
from sma_outfits.signals.classifier import SignalClassifier
from sma_outfits.utils import stable_id


@dataclass(frozen=True, slots=True)
class OutfitDefinition:
    outfit_id: str
    periods: tuple[int, ...]
    description: str
    source_configuration: str
    source_ambiguous: bool = False


def load_outfits(path: Path) -> list[OutfitDefinition]:
    if not path.exists():
        raise FileNotFoundError(f"Outfit catalog not found: {path}")
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or "outfits" not in parsed:
        raise ValueError("Outfit catalog must be a map with key 'outfits'")
    rows = parsed["outfits"]
    if not isinstance(rows, list):
        raise ValueError("Outfit catalog 'outfits' must be a list")

    outfits: list[OutfitDefinition] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each outfit row must be a map")
        periods = tuple(int(period) for period in row["periods"])
        if any(period < 1 or period > 999 for period in periods):
            raise ValueError(f"Invalid period in outfit {row.get('id')}")
        outfits.append(
            OutfitDefinition(
                outfit_id=str(row["id"]),
                periods=periods,
                description=str(row.get("description", "")),
                source_configuration=str(row.get("source_configuration", "")),
                source_ambiguous=bool(row.get("source_ambiguous", False)),
            )
        )
    return outfits


class StrikeDetector:
    def __init__(
        self,
        outfits: list[OutfitDefinition],
        tolerance: float = 0.01,
        trigger_mode: str = "bar_touch",
        long_break: float = 0.01,
        short_break: float = 0.01,
        classifier: SignalClassifier | None = None,
    ) -> None:
        self.outfits = outfits
        self.tolerance = tolerance
        self.trigger_mode = trigger_mode
        self.long_break = long_break
        self.short_break = short_break
        self.classifier = classifier or SignalClassifier()
        self._seen_keys: set[str] = set()

    def detect(
        self,
        bar: BarEvent,
        sma_states: dict[int, SMAState],
        history: pd.DataFrame,
        session_type: str = "regular",
    ) -> tuple[list[StrikeEvent], list[SignalEvent]]:
        strikes: list[StrikeEvent] = []
        signals: list[SignalEvent] = []
        for outfit in self.outfits:
            for period in outfit.periods:
                state = sma_states.get(period)
                if state is None:
                    continue
                if not self._touches(bar, state.value):
                    continue
                strike_id = stable_id(
                    "strike",
                    bar.symbol,
                    bar.timeframe,
                    _ts_iso(bar.ts),
                    outfit.outfit_id,
                    str(period),
                )
                if strike_id in self._seen_keys:
                    continue
                self._seen_keys.add(strike_id)
                strike = StrikeEvent(
                    id=strike_id,
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    outfit_id=outfit.outfit_id,
                    period=period,
                    sma_value=state.value,
                    bar_ts=bar.ts,
                    tolerance=self.tolerance,
                    trigger_mode=self.trigger_mode,
                )

                side = "LONG" if bar.close >= state.value else "SHORT"
                signal_type = self.classifier.classify(side=side, history=history)
                confidence = "HIGH" if signal_type in {"precision_buy", "automated_short"} else "MEDIUM"
                entry = round(state.value, 2)
                stop = (
                    round(entry - self.long_break, 2)
                    if side == "LONG"
                    else round(entry + self.short_break, 2)
                )
                signal = SignalEvent(
                    id=stable_id("signal", strike.id, side),
                    strike_id=strike.id,
                    side=side,
                    signal_type=signal_type,  # type: ignore[arg-type]
                    entry=entry,
                    stop=stop,
                    confidence=confidence,
                    session_type=session_type,  # type: ignore[arg-type]
                )
                strikes.append(strike)
                signals.append(signal)
        return strikes, signals

    def _touches(self, bar: BarEvent, sma_value: float) -> bool:
        lower = bar.low - self.tolerance
        upper = bar.high + self.tolerance
        return lower <= sma_value <= upper


def _ts_iso(ts: datetime) -> str:
    return pd.Timestamp(ts).isoformat()
