from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sma_outfits.data.storage import StorageManager


def test_write_bars_raises_actionable_error_on_os_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = StorageManager(tmp_path / "storage")
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T14:30:00Z")],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
        }
    )

    def _raise_os_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_os_error)

    with pytest.raises(RuntimeError, match="Remove the affected date partition directory"):
        storage.write_bars(
            frame,
            symbol="XLF",
            timeframe="15m",
        )


def test_write_bars_surfaces_partition_corruption_root_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = StorageManager(tmp_path / "storage")
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T14:30:00Z")],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
        }
    )

    def _raise_os_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError(22, "Invalid argument")

    def _probe_failure(_directory: Path) -> OSError:
        return OSError(22, "The file or directory is corrupted and unreadable.")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _raise_os_error)
    monkeypatch.setattr(storage, "_probe_partition_writability", _probe_failure)

    with pytest.raises(RuntimeError) as exc:
        storage.write_bars(
            frame,
            symbol="XLF",
            timeframe="15m",
        )
    message = str(exc.value)
    assert "Root cause: filesystem reports the partition directory is corrupted or unreadable." in message
    assert "Remove the affected date partition directory and rerun backfill." in message
