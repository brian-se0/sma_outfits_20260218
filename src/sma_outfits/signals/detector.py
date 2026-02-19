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

    required_keys = {
        "id",
        "periods",
        "description",
        "source_configuration",
        "source_ambiguous",
    }
    outfits: list[OutfitDefinition] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Each outfit row must be a map")
        missing = required_keys.difference(row.keys())
        if missing:
            raise ValueError(
                f"Outfit row[{index}] missing required keys: {sorted(missing)}"
            )
        unexpected = set(row.keys()).difference(required_keys)
        if unexpected:
            raise ValueError(
                f"Outfit row[{index}] has unexpected keys: {sorted(unexpected)}"
            )

        outfit_id = row["id"]
        if not isinstance(outfit_id, str) or not outfit_id.strip():
            raise ValueError(f"Outfit row[{index}] id must be non-empty string")

        periods_raw = row["periods"]
        if not isinstance(periods_raw, list) or not periods_raw:
            raise ValueError(
                f"Outfit row[{index}] periods must be a non-empty list of integers"
            )
        if any(not isinstance(period, int) or isinstance(period, bool) for period in periods_raw):
            raise ValueError(f"Outfit row[{index}] periods must contain integers only")
        periods = tuple(periods_raw)
        if any(period < 1 or period > 999 for period in periods):
            raise ValueError(f"Invalid period in outfit {outfit_id}")

        description = row["description"]
        if not isinstance(description, str):
            raise ValueError(f"Outfit row[{index}] description must be string")

        source_configuration = row["source_configuration"]
        if not isinstance(source_configuration, str):
            raise ValueError(
                f"Outfit row[{index}] source_configuration must be string"
            )

        source_ambiguous = row["source_ambiguous"]
        if not isinstance(source_ambiguous, bool):
            raise ValueError(
                f"Outfit row[{index}] source_ambiguous must be boolean"
            )

        outfits.append(
            OutfitDefinition(
                outfit_id=outfit_id.strip(),
                periods=periods,
                description=description,
                source_configuration=source_configuration,
                source_ambiguous=source_ambiguous,
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
