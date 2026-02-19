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


def test_backfill_daily_source_expands_intraday_window_for_equities(settings) -> None:
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T05:00:00Z")],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1000.0],
        }
    )
    client = InMemoryHistoricalClient({("SPY", "1D"): frame})
    storage = StorageManager(Path(settings.storage_root))

    results = backfill_historical(
        settings=settings,
        symbols=["SPY"],
        timeframes=["1D"],
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-02T21:00:00Z"),
        client=client,
        storage=storage,
    )

    assert results
    assert results[0].bars_written == 1
    persisted = storage.read_bars("SPY", "1D")
    assert len(persisted) == 1


def test_backfill_clips_daily_output_to_requested_local_date_window(settings) -> None:
    frame = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T05:00:00Z"),
                pd.Timestamp("2025-01-03T05:00:00Z"),
            ],
            "open": [100.0, 110.0],
            "high": [102.0, 112.0],
            "low": [99.0, 109.0],
            "close": [101.0, 111.0],
            "volume": [1000.0, 900.0],
        }
    )
    client = InMemoryHistoricalClient({("SPY", "1D"): frame})
    storage = StorageManager(Path(settings.storage_root))

    results = backfill_historical(
        settings=settings,
        symbols=["SPY"],
        timeframes=["1D"],
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-02T21:00:00Z"),
        client=client,
        storage=storage,
    )

    assert results
    persisted = storage.read_bars("SPY", "1D")
    assert len(persisted) == 1
    assert persisted.iloc[0]["ts"] == pd.Timestamp("2025-01-02T05:00:00Z")


def test_backfill_daily_source_uses_utc_boundaries_for_crypto(settings) -> None:
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T00:00:00Z")],
            "open": [40000.0],
            "high": [40500.0],
            "low": [39500.0],
            "close": [40200.0],
            "volume": [12.0],
        }
    )
    client = InMemoryHistoricalClient({("BTC/USD", "1D"): frame})
    storage = StorageManager(Path(settings.storage_root))

    results = backfill_historical(
        settings=settings,
        symbols=["BTC/USD"],
        timeframes=["1D"],
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-02T21:00:00Z"),
        client=client,
        storage=storage,
    )

    assert results
    assert results[0].bars_written == 1
    persisted = storage.read_bars("BTC/USD", "1D")
    assert len(persisted) == 1
