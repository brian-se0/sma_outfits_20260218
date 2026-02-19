from __future__ import annotations

import pandas as pd

from sma_outfits.data.resample import resample_ohlcv


def _make_minute_bars() -> pd.DataFrame:
    ts = pd.date_range("2025-01-02T14:30:00Z", periods=240, freq="1min")
    values = pd.Series(range(1, len(ts) + 1), dtype=float)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": values,
            "high": values + 0.5,
            "low": values - 0.5,
            "close": values + 0.1,
            "volume": 100.0,
        }
    )


def _make_daily_bars() -> pd.DataFrame:
    ts = pd.date_range("2024-10-01T00:00:00Z", periods=180, freq="1D")
    values = pd.Series(range(1, len(ts) + 1), dtype=float)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": values,
            "high": values + 1.0,
            "low": values - 1.0,
            "close": values + 0.2,
            "volume": 1000.0,
        }
    )


def test_resampler_correctness_and_supported_timeframes() -> None:
    minute_bars = _make_minute_bars()
    expected_2m = (
        minute_bars.set_index("ts")
        .tz_convert("America/New_York")
        .resample("2min", label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
        .tz_convert("UTC")
        .reset_index()
    )
    actual_2m = resample_ohlcv(minute_bars, "2m")
    pd.testing.assert_frame_equal(
        actual_2m.reset_index(drop=True),
        expected_2m.reset_index(drop=True),
    )

    for timeframe in ["3m", "5m", "10m", "15m", "20m", "30m", "1h", "2h", "4h"]:
        assert not resample_ohlcv(minute_bars, timeframe).empty

    daily_bars = _make_daily_bars()
    for timeframe in ["1D", "1W", "1M", "1Q"]:
        assert not resample_ohlcv(daily_bars, timeframe).empty


def test_resampler_uses_configured_anchor_rules() -> None:
    daily_bars = _make_daily_bars()
    weekly_default = resample_ohlcv(daily_bars, "1W")
    weekly_custom = resample_ohlcv(
        daily_bars,
        "1W",
        anchors={"1W": "W-THU", "1M": "ME", "1Q": "QE"},
    )

    assert not weekly_default.empty
    assert not weekly_custom.empty
    assert not weekly_default["ts"].equals(weekly_custom["ts"])
