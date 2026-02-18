from __future__ import annotations

from pathlib import Path

import pandas as pd

from sma_outfits.data.storage import StorageManager
from sma_outfits.replay.engine import ReplayEngine


def test_end_to_end_replay_with_synthetic_data(settings, tmp_path: Path) -> None:
    storage = StorageManager(Path(settings.storage_root))
    ts = pd.date_range("2025-01-02T14:30:00Z", periods=1200, freq="1min")
    close = pd.Series(100.0 + (pd.Series(range(len(ts))) * 0.02), dtype=float)
    bars = pd.DataFrame(
        {
            "ts": ts,
            "open": close - 0.03,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1000.0,
        }
    )
    storage.write_bars(bars, symbol="SPY", timeframe="1m")

    engine = ReplayEngine(settings=settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-03T10:00:00Z"),
        symbols=["SPY"],
        timeframes=["1m"],
    )
    assert result.signals
    assert result.position_events
    persisted = storage.load_events("signals")
    assert persisted
