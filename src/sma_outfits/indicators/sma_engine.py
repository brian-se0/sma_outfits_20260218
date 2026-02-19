from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from sma_outfits.events import SMAState


@dataclass(slots=True)
class _RollingState:
    values: deque[float] = field(default_factory=deque)
    rolling_sum: float = 0.0


class SMAEngine:
    def __init__(self, periods: list[int]) -> None:
        if not periods:
            raise ValueError("SMAEngine requires at least one period")
        unique = sorted(set(periods))
        if unique[0] < 1 or unique[-1] > 999:
            raise ValueError("SMA periods must be within [1, 999]")
        self.periods = unique
        self._state: dict[tuple[str, str], dict[int, _RollingState]] = {}

    def update(
        self,
        symbol: str,
        timeframe: str,
        ts: datetime,
        close: float | None = None,
        source_value: float | None = None,
    ) -> dict[int, SMAState]:
        if source_value is not None and close is not None:
            raise ValueError("Pass either close or source_value to SMAEngine.update, not both")
        if source_value is None and close is None:
            raise ValueError("SMAEngine.update requires close or source_value")

        key = (symbol, timeframe)
        period_state = self._state.setdefault(
            key,
            {period: _RollingState() for period in self.periods},
        )
        out: dict[int, SMAState] = {}
        close_value = float(source_value if source_value is not None else close)
        for period, rolling_state in period_state.items():
            rolling_state.values.append(close_value)
            rolling_state.rolling_sum += close_value
            if len(rolling_state.values) > period:
                rolling_state.rolling_sum -= rolling_state.values.popleft()
            if len(rolling_state.values) == period:
                out[period] = SMAState(
                    symbol=symbol,
                    timeframe=timeframe,
                    period=period,
                    value=rolling_state.rolling_sum / period,
                    ts=ts,
                )
        return out


def compute_sma_reference(
    closes: pd.Series,
    periods: list[int],
) -> pd.DataFrame:
    frame = pd.DataFrame(index=closes.index)
    for period in periods:
        frame[f"sma_{period}"] = closes.rolling(period, min_periods=period).mean()
    return frame
