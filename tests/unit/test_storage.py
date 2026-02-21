from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sma_outfits.data.storage import (
    StorageManager,
    legacy_case_collision_groups,
    storage_timeframe_token,
)
from sma_outfits.utils import SUPPORTED_TIMEFRAMES


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


def test_storage_timeframe_tokens_are_unique() -> None:
    tokens = [storage_timeframe_token(timeframe) for timeframe in SUPPORTED_TIMEFRAMES]
    assert len(tokens) == len(set(tokens))


def test_storage_reads_canonical_and_legacy_dirs_and_prefers_canonical(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path / "storage")
    canonical = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T14:30:00Z")],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
        }
    )
    storage.write_bars(canonical, symbol="XLF", timeframe="1m")

    legacy_dir = (
        tmp_path
        / "storage"
        / "bars"
        / "timeframe=1m"
        / "symbol=XLF"
        / "date=2025-01-02"
    )
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-02T14:31:00Z"),
            ],
            "open": [200.0, 200.0],
            "high": [201.0, 201.0],
            "low": [199.0, 199.0],
            "close": [200.5, 200.6],
            "volume": [2000.0, 2001.0],
        }
    )
    legacy.to_parquet(legacy_dir / "bars-legacy.parquet", index=False)

    out = storage.read_bars(symbol="XLF", timeframe="1m")
    assert len(out) == 2
    # Canonical row must win for duplicate timestamp.
    first = out.loc[out["ts"] == pd.Timestamp("2025-01-02T14:30:00Z")].iloc[0]
    assert float(first["close"]) == 100.5
    second = out.loc[out["ts"] == pd.Timestamp("2025-01-02T14:31:00Z")].iloc[0]
    assert float(second["close"]) == 200.6


def test_storage_events_root_override_is_used(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    events_root = tmp_path / "custom-events"
    storage = StorageManager(root, events_root=events_root)

    storage.append_events("signals", [{"id": "x", "route_id": "r"}])
    assert (events_root / "signals.jsonl").exists()
    assert not (root / "events" / "signals.jsonl").exists()

    rows = storage.load_events("signals")
    assert rows == [{"id": "x", "route_id": "r"}]


def test_migrate_legacy_layout_detects_ambiguous_case_collision(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path / "storage")
    legacy_dir = (
        tmp_path
        / "storage"
        / "bars"
        / "timeframe=1m"
        / "symbol=SPY"
        / "date=2025-01-02"
    )
    legacy_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T14:30:00Z")],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        }
    ).to_parquet(legacy_dir / "bars-legacy.parquet", index=False)

    report = storage.migrate_legacy_timeframe_layout(dry_run=True)
    assert report["status"] == "error"
    assert report["ambiguous_dirs"]
    assert "1m" in legacy_case_collision_groups()


def test_migrate_legacy_layout_moves_non_ambiguous_dirs(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path / "storage")
    legacy_dir = (
        tmp_path
        / "storage"
        / "bars"
        / "timeframe=1D"
        / "symbol=SPY"
        / "date=2025-01-02"
    )
    legacy_dir.mkdir(parents=True, exist_ok=True)
    source_file = legacy_dir / "bars-legacy.parquet"
    pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T00:00:00Z")],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
        }
    ).to_parquet(source_file, index=False)

    report = storage.migrate_legacy_timeframe_layout(dry_run=False)
    assert report["status"] == "ok"
    assert not source_file.exists()
    target_file = (
        tmp_path
        / "storage"
        / "bars"
        / "timeframe=1day"
        / "symbol=SPY"
        / "date=2025-01-02"
        / "bars-legacy.parquet"
    )
    assert target_file.exists()
