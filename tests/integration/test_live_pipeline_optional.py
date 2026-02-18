from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sma_outfits.config.models import load_settings
from sma_outfits.data.storage import StorageManager
from sma_outfits.live import LiveRunner


def test_optional_alpaca_live_stream_one_hour() -> None:
    import pytest

    if os.getenv("SMA_OUTFITS_ENABLE_LIVE_INTEGRATION", "0") != "1":
        pytest.skip("Set SMA_OUTFITS_ENABLE_LIVE_INTEGRATION=1 to run live Alpaca test")

    symbol = os.getenv("SMA_OUTFITS_LIVE_SYMBOL", "SPY").upper()
    timeframe = os.getenv("SMA_OUTFITS_LIVE_TIMEFRAME", "1m")
    config_path = Path(
        os.getenv("SMA_OUTFITS_LIVE_CONFIG", "configs/settings.example.yaml")
    )

    settings = load_settings(config_path=config_path, env_path=Path(".env.local"))
    live_settings = settings.model_copy(deep=True)
    live_settings.universe.symbols = [symbol]
    live_settings.timeframes.live = [timeframe]
    live_settings.archive.enabled = False

    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(settings=live_settings, storage=storage)

    result = asyncio.run(
        runner.run(
            symbols=[symbol],
            timeframes=[timeframe],
            runtime_minutes=60,
            warmup_minutes=60,
        )
    )

    assert result.bars_received > 0
    bars = storage.read_bars(symbol, timeframe)
    assert not bars.empty
