from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import duckdb
import orjson
import pandas as pd

from sma_outfits.data.resample import ensure_ohlcv_schema


class StorageManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "bars").mkdir(parents=True, exist_ok=True)
        self._write_sequence = 0

    @staticmethod
    def _safe_symbol(symbol: str) -> str:
        return symbol.replace("/", "_")

    def _bars_base(self, symbol: str, timeframe: str) -> Path:
        safe_symbol = self._safe_symbol(symbol)
        return (
            self.root
            / "bars"
            / f"timeframe={timeframe}"
            / f"symbol={safe_symbol}"
        )

    def write_bars(
        self,
        frame: pd.DataFrame,
        symbol: str,
        timeframe: str,
        timezone: str = "America/New_York",
    ) -> int:
        bars = ensure_ohlcv_schema(frame)
        if bars.empty:
            return 0
        bars["session_date"] = bars["ts"].dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")
        written = 0
        for session_date, chunk in bars.groupby("session_date"):
            directory = self._bars_base(symbol, timeframe) / f"date={session_date}"
            directory.mkdir(parents=True, exist_ok=True)
            self._write_sequence += 1
            chunk_id = f"{time.time_ns()}_{self._write_sequence:06d}"
            path = directory / f"bars-{chunk_id}.parquet"
            next_chunk = chunk.drop(columns=["session_date"])
            try:
                next_chunk.to_parquet(path, index=False)
            except OSError as exc:
                probe_error = self._probe_partition_writability(directory)
                raise RuntimeError(
                    _build_partition_write_error(
                        path=path,
                        directory=directory,
                        write_error=exc,
                        probe_error=probe_error,
                    )
                ) from exc
            written += len(next_chunk)
        return written

    def _probe_partition_writability(self, directory: Path) -> OSError | None:
        probe_name = f".write_probe_{time.time_ns()}_{self._write_sequence:06d}.tmp"
        probe_path = directory / probe_name
        try:
            with probe_path.open("wb") as handle:
                handle.write(b"")
        except OSError as exc:
            return exc
        finally:
            try:
                probe_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # Probe cleanup must not hide the primary storage write error.
                pass
        return None

    def read_bars(
        self,
        symbol: str,
        timeframe: str,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        base = self._bars_base(symbol, timeframe)
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        if not base.exists():
            return empty

        parquet_files = sorted(base.glob("date=*/bars*.parquet"))
        if not parquet_files:
            return empty

        parquet_glob = str(base / "date=*" / "bars*.parquet")
        query = [
            "SELECT ts, open, high, low, close, volume",
            "FROM (",
            "  SELECT ts, open, high, low, close, volume,",
            "         row_number() OVER (PARTITION BY ts ORDER BY filename DESC) AS rn",
            "  FROM read_parquet(?, filename=true)",
            ")",
            "WHERE rn = 1",
        ]
        params: list[Any] = [parquet_glob]
        if start is not None:
            query.append("  AND ts >= ?")
            params.append(_as_utc_timestamp(start).to_pydatetime())
        if end is not None:
            query.append("  AND ts <= ?")
            params.append(_as_utc_timestamp(end).to_pydatetime())
        query.append("ORDER BY ts")

        connection = duckdb.connect()
        try:
            out = connection.execute("\n".join(query), params).df()
        finally:
            connection.close()
        if out.empty:
            return empty

        out["ts"] = pd.to_datetime(out["ts"], utc=True)
        out = out.sort_values("ts").reset_index(drop=True)
        return out.loc[:, ["ts", "open", "high", "low", "close", "volume"]]

    def append_events(self, name: str, records: list[dict[str, Any]]) -> Path:
        events_root = self.root / "events"
        events_root.mkdir(parents=True, exist_ok=True)
        path = events_root / f"{name}.jsonl"
        with path.open("ab") as handle:
            for record in records:
                handle.write(orjson.dumps(record, option=orjson.OPT_SORT_KEYS))
                handle.write(b"\n")
        return path

    def load_events(self, name: str) -> list[dict[str, Any]]:
        path = self.root / "events" / f"{name}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("rb") as handle:
            for raw in handle:
                line = raw.strip()
                if line:
                    rows.append(orjson.loads(line))
        return rows


def _as_utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _build_partition_write_error(
    path: Path,
    directory: Path,
    write_error: OSError,
    probe_error: OSError | None,
) -> str:
    base = (
        "Failed to write parquet partition '{}'. "
        "Underlying OS error: {}. "
    ).format(path, _format_os_error(write_error))
    recovery = "Remove the affected date partition directory and rerun backfill."
    if probe_error is None:
        return base + "This can indicate a corrupted partition directory. " + recovery

    if _is_filesystem_corruption_error(probe_error):
        return (
            base
            + "Partition writability probe for '{}' failed: {}. "
            + "Root cause: filesystem reports the partition directory is corrupted or unreadable. "
            + recovery
        ).format(directory, _format_os_error(probe_error))

    return (
        base
        + "Partition writability probe for '{}' failed: {}. "
        + "Root cause: partition directory is not writable. "
        + recovery
    ).format(directory, _format_os_error(probe_error))


def _format_os_error(error: OSError) -> str:
    details = [str(error)]
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        details.append(f"(winerror={winerror})")
    return " ".join(details)


def _is_filesystem_corruption_error(error: OSError) -> bool:
    winerror = getattr(error, "winerror", None)
    if winerror == 1392:
        return True
    lowered = str(error).lower()
    return "corrupted and unreadable" in lowered
