from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from sma_outfits.indicators.sma_engine import SMAEngine, compute_sma_reference


def test_sma_engine_matches_pandas_reference() -> None:
    periods = [10, 50, 200, 548, 840]
    closes = pd.Series(np.linspace(100.0, 200.0, 1200))
    engine = SMAEngine(periods)
    observed: dict[int, list[float]] = {period: [] for period in periods}
    start = pd.Timestamp("2025-01-01T09:30:00Z")

    for index, close in enumerate(closes):
        ts = (start + pd.Timedelta(minutes=index)).to_pydatetime()
        states = engine.update(symbol="SPY", timeframe="1m", ts=ts, close=float(close))
        for period in periods:
            if period in states:
                observed[period].append(states[period].value)

    reference = compute_sma_reference(closes, periods)
    for period in periods:
        expected = reference[f"sma_{period}"].dropna().to_list()
        assert observed[period] == pytest.approx(expected)


def test_sma_engine_matches_ohlc4_reference() -> None:
    periods = [3, 8, 16]
    base = pd.Series(np.linspace(100.0, 140.0, 200))
    open_ = base + 0.1
    high = base + 0.5
    low = base - 0.4
    close = base - 0.2
    ohlc4 = (open_ + high + low + close) / 4.0
    engine = SMAEngine(periods)
    observed: dict[int, list[float]] = {period: [] for period in periods}
    start = pd.Timestamp("2025-01-01T09:30:00Z")

    for index, value in enumerate(ohlc4):
        ts = (start + pd.Timedelta(minutes=index)).to_pydatetime()
        states = engine.update(
            symbol="QQQ",
            timeframe="1m",
            ts=ts,
            source_value=float(value),
        )
        for period in periods:
            if period in states:
                observed[period].append(states[period].value)

    reference = compute_sma_reference(ohlc4, periods)
    for period in periods:
        expected = reference[f"sma_{period}"].dropna().to_list()
        assert observed[period] == pytest.approx(expected)
