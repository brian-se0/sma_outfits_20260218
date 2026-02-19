from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

Side = Literal["LONG", "SHORT"]
SignalType = Literal[
    "precision_buy",
    "optimized_buy",
    "magnetized_buy",
    "automated_short",
    "singular_point_hard_stop",
]
SessionType = Literal["regular", "extended"]


@dataclass(frozen=True, slots=True)
class BarEvent:
    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


@dataclass(frozen=True, slots=True)
class SMAState:
    symbol: str
    timeframe: str
    period: int
    value: float
    ts: datetime


@dataclass(frozen=True, slots=True)
class StrikeEvent:
    id: str
    symbol: str
    timeframe: str
    outfit_id: str
    period: int
    sma_value: float
    bar_ts: datetime
    tolerance: float
    trigger_mode: str


@dataclass(frozen=True, slots=True)
class SignalEvent:
    id: str
    strike_id: str
    route_id: str
    side: Side
    signal_type: SignalType
    entry: float
    stop: float
    confidence: str
    session_type: SessionType


@dataclass(frozen=True, slots=True)
class PositionEvent:
    id: str
    signal_id: str
    action: str
    qty: float
    price: float
    reason: str
    ts: datetime


@dataclass(frozen=True, slots=True)
class ArchiveRecord:
    signal_id: str
    markdown_path: str
    artifact_type: str
    caption: str
    ts: datetime


def event_to_record(event: Any) -> dict[str, Any]:
    data = asdict(event)
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data
