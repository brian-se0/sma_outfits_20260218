from __future__ import annotations

from typing import Mapping

import pandas as pd

from sma_outfits.utils import timeframe_to_pandas_rule

REQUIRED_BAR_COLUMNS = ("ts", "open", "high", "low", "close", "volume")


def ensure_ohlcv_schema(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_BAR_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required bar columns: {missing}")
    out = frame.loc[:, REQUIRED_BAR_COLUMNS].copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    out = out.sort_values("ts").drop_duplicates(subset=["ts"])
    return out.reset_index(drop=True)


def resample_ohlcv(
    frame: pd.DataFrame,
    timeframe: str,
    timezone: str = "America/New_York",
    anchors: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    normalized = ensure_ohlcv_schema(frame)
    if timeframe == "1m":
        return normalized

    rule = timeframe_to_pandas_rule(timeframe, anchors=anchors)
    localized = normalized.set_index("ts").tz_convert(timezone)
    grouped = localized.resample(rule, label="right", closed="right")
    out = grouped.agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out.tz_convert("UTC").reset_index()
    return out.loc[:, REQUIRED_BAR_COLUMNS].reset_index(drop=True)
