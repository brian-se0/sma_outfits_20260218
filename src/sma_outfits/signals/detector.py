from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from sma_outfits.config.models import RouteRule
from sma_outfits.events import BarEvent, SMAState, SignalEvent, StrikeEvent
from sma_outfits.utils import stable_id

MACRO_PERIODS: dict[str, tuple[int, int]] = {
    "spx": (10, 50),
    "nas": (20, 100),
    "dji": (90, 300),
}


@dataclass(frozen=True, slots=True)
class OutfitDefinition:
    outfit_id: str
    periods: tuple[int, ...]
    description: str
    source_configuration: str
    source_ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class RouteBarContext:
    route: RouteRule
    key_sma: float
    micro_positive: bool
    macro_positive: bool


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
        routes: list[RouteRule],
        strict_routing: bool = True,
        tolerance: float = 0.01,
        trigger_mode: str = "close_touch_or_cross",
    ) -> None:
        self.tolerance = tolerance
        self.trigger_mode = trigger_mode
        self.strict_routing = strict_routing
        self._outfits_by_id: dict[str, OutfitDefinition] = {
            outfit.outfit_id: outfit for outfit in outfits
        }
        self._routes_by_key: dict[tuple[str, str], RouteRule] = {}
        for route in routes:
            route_key = (route.symbol, route.timeframe)
            if self.strict_routing and route_key in self._routes_by_key:
                raise RuntimeError(
                    "Duplicate route for strict routing key "
                    f"{route.symbol}/{route.timeframe}"
                )
            self._routes_by_key[route_key] = route
            if route.outfit_id not in self._outfits_by_id:
                raise RuntimeError(
                    f"Route '{route.id}' references unknown outfit '{route.outfit_id}'"
                )
        self._seen_keys: set[str] = set()

    def required_periods(self) -> set[int]:
        periods: set[int] = set()
        for route in self._routes_by_key.values():
            periods.add(route.key_period)
            periods.update(route.micro_periods)
            if route.macro_gate != "none":
                macro_periods = MACRO_PERIODS.get(route.macro_gate)
                if macro_periods is None:
                    raise RuntimeError(
                        f"Unsupported macro gate '{route.macro_gate}' for route '{route.id}'"
                    )
                periods.update(macro_periods)
        return periods

    def resolve_route(self, symbol: str, timeframe: str) -> RouteRule | None:
        route = self._routes_by_key.get((symbol.upper(), timeframe))
        if route is not None:
            return route
        if self.strict_routing:
            raise RuntimeError(
                "Strict routing violation: no route configured for "
                f"{symbol.upper()}/{timeframe}"
            )
        return None

    def build_route_context(
        self,
        bar: BarEvent,
        sma_states: dict[int, SMAState],
    ) -> RouteBarContext | None:
        route = self.resolve_route(bar.symbol, bar.timeframe)
        if route is None:
            return None

        key_state = sma_states.get(route.key_period)
        if key_state is None:
            return None

        micro_values: list[float] = []
        for period in route.micro_periods:
            state = sma_states.get(period)
            if state is None:
                return None
            micro_values.append(state.value)

        if route.side == "LONG":
            micro_positive = all(bar.close >= value for value in micro_values)
        else:
            micro_positive = all(bar.close <= value for value in micro_values)

        macro_positive = self._macro_positive(route, sma_states)
        if macro_positive is None:
            return None

        return RouteBarContext(
            route=route,
            key_sma=key_state.value,
            micro_positive=micro_positive,
            macro_positive=macro_positive,
        )

    def detect(
        self,
        bar: BarEvent,
        sma_states: dict[int, SMAState],
        history: pd.DataFrame,
        session_type: str = "regular",
    ) -> tuple[list[StrikeEvent], list[SignalEvent]]:
        context = self.build_route_context(bar=bar, sma_states=sma_states)
        if context is None:
            return [], []

        if not context.micro_positive or not context.macro_positive:
            return [], []
        if not self._triggered(bar=bar, context=context, history=history):
            return [], []

        route = context.route
        strike_id = stable_id(
            "strike",
            bar.symbol,
            bar.timeframe,
            _ts_iso(bar.ts),
            route.id,
            route.outfit_id,
            str(route.key_period),
        )
        if strike_id in self._seen_keys:
            return [], []
        self._seen_keys.add(strike_id)

        strike = StrikeEvent(
            id=strike_id,
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            outfit_id=route.outfit_id,
            period=route.key_period,
            sma_value=context.key_sma,
            bar_ts=bar.ts,
            tolerance=self.tolerance,
            trigger_mode=self.trigger_mode,
        )
        entry = round(context.key_sma, 2)
        stop = (
            round(entry - route.stop_offset, 2)
            if route.side == "LONG"
            else round(entry + route.stop_offset, 2)
        )
        confidence = (
            "HIGH"
            if route.signal_type in {"precision_buy", "automated_short", "magnetized_buy"}
            else "MEDIUM"
        )
        signal = SignalEvent(
            id=stable_id("signal", strike.id, route.id, route.side),
            strike_id=strike.id,
            route_id=route.id,
            side=route.side,
            signal_type=route.signal_type,  # type: ignore[arg-type]
            entry=entry,
            stop=stop,
            confidence=confidence,
            session_type=session_type,  # type: ignore[arg-type]
        )
        return [strike], [signal]

    def _triggered(
        self,
        bar: BarEvent,
        context: RouteBarContext,
        history: pd.DataFrame,
    ) -> bool:
        if self.trigger_mode != "close_touch_or_cross":
            raise RuntimeError(f"Unsupported strategy trigger_mode '{self.trigger_mode}'")

        key_sma = context.key_sma
        touch = abs(bar.close - key_sma) <= self.tolerance

        prev_close: float | None = None
        if len(history) >= 2 and "close" in history.columns:
            prev_close = float(history.iloc[-2]["close"])

        cross = False
        if prev_close is not None:
            if context.route.side == "LONG":
                cross = prev_close < key_sma and bar.close >= key_sma
            else:
                cross = prev_close > key_sma and bar.close <= key_sma
        return touch or cross

    @staticmethod
    def _macro_positive(
        route: RouteRule,
        sma_states: dict[int, SMAState],
    ) -> bool | None:
        gate = route.macro_gate
        if gate == "none":
            return True
        periods = MACRO_PERIODS.get(gate)
        if periods is None:
            raise RuntimeError(
                f"Unsupported macro gate '{gate}' for route '{route.id}'"
            )
        fast_period, slow_period = periods
        fast = sma_states.get(fast_period)
        slow = sma_states.get(slow_period)
        if fast is None or slow is None:
            return None
        return fast.value >= slow.value


def _ts_iso(ts: datetime) -> str:
    return pd.Timestamp(ts).isoformat()
