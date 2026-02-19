from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd

from sma_outfits.data.alpaca_clients import LiveBar, StreamDisconnectedError
from sma_outfits.data.storage import StorageManager
from sma_outfits.live import LiveRunner


class MockStreamFactory:
    def __init__(self) -> None:
        self._calls = 0

    def __call__(self, market: str, symbols: list[str]):
        self._calls += 1
        attempt = self._calls

        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            if attempt == 1:
                yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
                yield _bar("SPY", "2025-01-02T14:31:00Z", 101.0)
                raise StreamDisconnectedError("synthetic disconnect")

            yield _bar("SPY", "2025-01-02T14:31:00Z", 101.0)
            yield _bar("SPY", "2025-01-02T14:32:00Z", 102.0)
            while True:
                await asyncio.sleep(1.0)

        return _generator()


class MalformedStreamFactory:
    def __call__(self, market: str, symbols: list[str]):
        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
            yield {"T": "b", "symbol": "SPY"}  # type: ignore[misc]
            while True:
                await asyncio.sleep(1.0)

        return _generator()


def test_live_pipeline_mocked_stream_reconnect_and_idempotency(
    settings,
    tmp_path: Path,
) -> None:
    outfits_path = tmp_path / "test_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test_outfit",
                "    periods: [1]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    live_settings = settings.model_copy(deep=True)
    live_settings.outfits_path = str(outfits_path)
    live_settings.universe.symbols = ["SPY"]
    live_settings.timeframes.live = ["1m"]
    live_settings.archive.enabled = False
    live_settings.sessions.regular_only = False
    live_settings.live.reconnect_base_delay_seconds = 0.01
    live_settings.live.reconnect_max_delay_seconds = 0.01
    live_settings.live.reconnect_max_attempts = 3

    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=MockStreamFactory(),
    )
    progress_snapshots: list[dict[str, object]] = []

    result = asyncio.run(
        runner.run(
            symbols=["SPY"],
            timeframes=["1m"],
            runtime_seconds=0.3,
            warmup_minutes=0,
            progress_callback=lambda payload: progress_snapshots.append(dict(payload)),
        )
    )

    assert result.reconnects >= 1
    assert result.duplicate_bars_skipped >= 1
    assert progress_snapshots
    assert all("status" in snapshot for snapshot in progress_snapshots)
    assert any(snapshot["status"] == "starting" for snapshot in progress_snapshots)
    assert any(snapshot["status"] == "completed" for snapshot in progress_snapshots)

    bars = storage.read_bars("SPY", "1m")
    assert len(bars) == 3

    signals = storage.load_events("signals")
    strikes = storage.load_events("strikes")
    assert len(signals) == 3
    assert len(strikes) == 3


def test_live_pipeline_fails_fast_on_malformed_stream_payload(
    settings,
    tmp_path: Path,
) -> None:
    outfits_path = tmp_path / "test_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test_outfit",
                "    periods: [1]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    live_settings = settings.model_copy(deep=True)
    live_settings.outfits_path = str(outfits_path)
    live_settings.universe.symbols = ["SPY"]
    live_settings.timeframes.live = ["1m"]
    live_settings.archive.enabled = False
    live_settings.sessions.regular_only = False
    live_settings.live.reconnect_max_attempts = 1

    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=MalformedStreamFactory(),
    )

    try:
        asyncio.run(
            runner.run(
                symbols=["SPY"],
                timeframes=["1m"],
                runtime_seconds=1.0,
                warmup_minutes=0,
            )
        )
    except RuntimeError as exc:
        assert "Fatal error in stocks live stream" in str(exc)
    else:
        raise AssertionError("Expected live run to fail on malformed payload")


def _bar(symbol: str, ts: str, close: float) -> LiveBar:
    timestamp = pd.Timestamp(ts).tz_convert("UTC")
    return LiveBar(
        symbol=symbol,
        ts=timestamp,
        open=close - 0.05,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000.0,
        source="mock",
    )
