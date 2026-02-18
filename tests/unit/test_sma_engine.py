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
