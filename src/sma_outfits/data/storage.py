from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import orjson
import pandas as pd

from sma_outfits.data.resample import ensure_ohlcv_schema
from sma_outfits.utils import SUPPORTED_TIMEFRAMES, normalize_timeframe

_TIMEFRAME_STORAGE_TOKEN = {
    "1m": "1min",
    "2m": "2min",
    "3m": "3min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "20m": "20min",
    "30m": "30min",
    "1h": "1hour",
    "2h": "2hour",
    "4h": "4hour",
    "1D": "1day",
    "1W": "1week",
    "1M": "1month",
    "1Q": "1quarter",
}


def storage_timeframe_token(timeframe: str) -> str:
    normalized = normalize_timeframe(timeframe)
    token = _TIMEFRAME_STORAGE_TOKEN.get(normalized)
    if token is None:
        raise ValueError(f"Unsupported timeframe for storage token mapping: {normalized}")
    return token


def storage_timeframe_read_candidates(timeframe: str) -> list[str]:
    normalized = normalize_timeframe(timeframe)
    candidates = [storage_timeframe_token(normalized), normalized]
    return list(dict.fromkeys(candidates))


def legacy_case_collision_groups() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for timeframe in SUPPORTED_TIMEFRAMES:
        grouped[timeframe.lower()].append(timeframe)
    return {
        key: sorted(values)
        for key, values in grouped.items()
        if len(values) > 1
    }


class StorageManager:
    def __init__(self, root: Path, events_root: Path | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "bars").mkdir(parents=True, exist_ok=True)
        self.events_root = events_root if events_root is not None else self.root / "events"
        self.events_root.mkdir(parents=True, exist_ok=True)
        self._write_sequence = 0

    @staticmethod
    def _safe_symbol(symbol: str) -> str:
        return symbol.replace("/", "_")

    def _bars_base(self, symbol: str, timeframe: str, *, legacy: bool = False) -> Path:
        safe_symbol = self._safe_symbol(symbol)
        timeframe_dir = normalize_timeframe(timeframe) if legacy else storage_timeframe_token(timeframe)
        return (
            self.root
            / "bars"
            / f"timeframe={timeframe_dir}"
            / f"symbol={safe_symbol}"
        )

    def _bars_bases_for_read(self, symbol: str, timeframe: str) -> list[tuple[Path, int]]:
        normalized = normalize_timeframe(timeframe)
        candidates = storage_timeframe_read_candidates(normalized)
        output: list[tuple[Path, int]] = []
        for candidate in candidates:
            legacy = candidate == normalized
            base = self._bars_base(symbol, normalized, legacy=legacy)
            if base.exists():
                rank = 1 if not legacy else 0
                output.append((base, rank))
        return output

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
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        bases = self._bars_bases_for_read(symbol, timeframe)
        if not bases:
            return empty

        connection = duckdb.connect()
        frames: list[pd.DataFrame] = []
        try:
            for base, source_rank in bases:
                parquet_files = sorted(base.glob("date=*/bars*.parquet"))
                if not parquet_files:
                    continue
                parquet_glob = str(base / "date=*" / "bars*.parquet")
                out = connection.execute(
                    "\n".join(
                        [
                            "SELECT ts, open, high, low, close, volume",
                            "FROM (",
                            "  SELECT ts, open, high, low, close, volume,",
                            "         row_number() OVER (PARTITION BY ts ORDER BY filename DESC) AS rn",
                            "  FROM read_parquet(?, filename=true)",
                            ")",
                            "WHERE rn = 1",
                            "ORDER BY ts",
                        ]
                    ),
                    [parquet_glob],
                ).df()
                if out.empty:
                    continue
                out["__source_rank"] = source_rank
                frames.append(out)
        finally:
            connection.close()

        if not frames:
            return empty

        out = pd.concat(frames, ignore_index=True)
        if out.empty:
            return empty

        out["ts"] = pd.to_datetime(out["ts"], utc=True)
        out = (
            out.sort_values(["ts", "__source_rank"])
            .drop_duplicates(subset=["ts"], keep="last")
            .drop(columns=["__source_rank"])
            .reset_index(drop=True)
        )
        if start is not None:
            out = out.loc[out["ts"] >= _as_utc_timestamp(start)].reset_index(drop=True)
        if end is not None:
            out = out.loc[out["ts"] <= _as_utc_timestamp(end)].reset_index(drop=True)
        return out.loc[:, ["ts", "open", "high", "low", "close", "volume"]]

    def append_events(self, name: str, records: list[dict[str, Any]]) -> Path:
        path = self.events_root / f"{name}.jsonl"
        with path.open("ab") as handle:
            for record in records:
                handle.write(orjson.dumps(record, option=orjson.OPT_SORT_KEYS))
                handle.write(b"\n")
        return path

    def load_events(self, name: str) -> list[dict[str, Any]]:
        path = self.events_root / f"{name}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("rb") as handle:
            for raw in handle:
                line = raw.strip()
                if line:
                    rows.append(orjson.loads(line))
        return rows

    def migrate_legacy_timeframe_layout(self, *, dry_run: bool = True) -> dict[str, Any]:
        bars_root = self.root / "bars"
        bars_root.mkdir(parents=True, exist_ok=True)
        collision_labels = set(legacy_case_collision_groups().keys())
        report: dict[str, Any] = {
            "status": "ok",
            "dry_run": dry_run,
            "planned_moves": [],
            "applied_moves": [],
            "ambiguous_dirs": [],
            "skipped_unknown_dirs": [],
        }
        timeframe_dirs = sorted(
            [path for path in bars_root.iterdir() if path.is_dir() and path.name.startswith("timeframe=")],
            key=lambda path: path.name.lower(),
        )
        for source in timeframe_dirs:
            raw = source.name.split("=", 1)[1]
            if raw.lower() in collision_labels:
                report["ambiguous_dirs"].append(
                    {
                        "source": str(source),
                        "reason": (
                            "case-colliding timeframe namespace on legacy layout; "
                            "manual cleanup and full backfill rerun required"
                        ),
                    }
                )
                continue
            if raw not in SUPPORTED_TIMEFRAMES:
                report["skipped_unknown_dirs"].append(str(source))
                continue

            target = bars_root / f"timeframe={storage_timeframe_token(raw)}"
            if source == target:
                continue

            report["planned_moves"].append({"from": str(source), "to": str(target)})
            if dry_run:
                continue

            files_moved = _move_tree_with_merge(source=source, target=target)
            report["applied_moves"].append(
                {"from": str(source), "to": str(target), "files_moved": files_moved}
            )

        if report["ambiguous_dirs"]:
            report["status"] = "error"
        return report


def _move_tree_with_merge(source: Path, target: Path) -> int:
    if not source.exists():
        return 0
    files_moved = 0
    if not target.exists():
        files_moved = len([path for path in source.rglob("*") if path.is_file()])
        source.rename(target)
        return files_moved

    for path in sorted([item for item in source.rglob("*") if item.is_file()], key=lambda item: str(item)):
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise RuntimeError(
                "Storage migration refused to overwrite existing file: "
                f"{destination}"
            )
        path.replace(destination)
        files_moved += 1

    for directory in sorted(
        [item for item in source.rglob("*") if item.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        source.rmdir()
    except OSError:
        pass
    return files_moved


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
