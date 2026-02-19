from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from sma_outfits.data.resample import ensure_ohlcv_schema


class StorageManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "bars").mkdir(parents=True, exist_ok=True)

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
            path = directory / "bars.parquet"
            next_chunk = chunk.drop(columns=["session_date"])
            if path.exists():
                existing = pd.read_parquet(path)
                next_chunk = pd.concat([existing, next_chunk], ignore_index=True)
                next_chunk["ts"] = pd.to_datetime(next_chunk["ts"], utc=True)
                next_chunk = (
                    next_chunk.sort_values("ts")
                    .drop_duplicates(subset=["ts"])
                    .reset_index(drop=True)
                )
            next_chunk.to_parquet(path, index=False)
            written += len(next_chunk)
        return written

    def read_bars(
        self,
        symbol: str,
        timeframe: str,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        base = self._bars_base(symbol, timeframe)
        if not base.exists():
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        frames: list[pd.DataFrame] = []
        for path in sorted(base.glob("date=*/bars.parquet")):
            frames.append(pd.read_parquet(path))
        if not frames:
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        out = pd.concat(frames, ignore_index=True)
        out["ts"] = pd.to_datetime(out["ts"], utc=True)
        if start is not None:
            out = out.loc[out["ts"] >= pd.Timestamp(start).tz_convert("UTC")]
        if end is not None:
            out = out.loc[out["ts"] <= pd.Timestamp(end).tz_convert("UTC")]
        out = out.sort_values("ts").drop_duplicates(subset=["ts"]).reset_index(drop=True)
        return out

    def append_events(self, name: str, records: list[dict[str, Any]]) -> Path:
        events_root = self.root / "events"
        events_root.mkdir(parents=True, exist_ok=True)
        path = events_root / f"{name}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True))
                handle.write("\n")
        return path

    def load_events(self, name: str) -> list[dict[str, Any]]:
        path = self.root / "events" / f"{name}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def open_duckdb(self) -> duckdb.DuckDBPyConnection:
        db_path = self.root / "sma_outfits.duckdb"
        connection = duckdb.connect(str(db_path))
        parquet_glob = str(self.root / "bars" / "timeframe=*" / "symbol=*" / "date=*" / "bars.parquet")
        connection.execute(
            "CREATE OR REPLACE VIEW bars AS SELECT * FROM read_parquet(?)",
            [parquet_glob],
        )
        return connection
