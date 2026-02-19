from __future__ import annotations

from pathlib import Path

import pandas as pd

from sma_outfits.data.alpaca_clients import InMemoryHistoricalClient
from sma_outfits.data.ingest import BackfillResult, backfill_historical
from sma_outfits.data.storage import StorageManager


def test_backfill_daily_source_not_filtered_by_regular_session(settings) -> None:
    frame = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T00:00:00Z"),
                pd.Timestamp("2025-01-03T00:00:00Z"),
            ],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000.0, 1200.0],
        }
    )
    client = InMemoryHistoricalClient({("SPY", "1D"): frame})
    storage = StorageManager(Path(settings.storage_root))
    progress_updates: list[tuple[int, int, BackfillResult]] = []

    results = backfill_historical(
        settings=settings,
        symbols=["SPY"],
        timeframes=["1D"],
        start=pd.Timestamp("2025-01-01T00:00:00Z"),
        end=pd.Timestamp("2025-01-04T00:00:00Z"),
        client=client,
        storage=storage,
        progress_callback=lambda done, total, row: progress_updates.append(
            (done, total, row)
        ),
    )

    assert results
    assert results[0].bars_written > 0
    assert progress_updates
    assert progress_updates[-1][0] == progress_updates[-1][1] == 1
    persisted = storage.read_bars("SPY", "1D")
    assert len(persisted) == 2
