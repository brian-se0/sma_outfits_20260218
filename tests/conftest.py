from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sma_outfits.config.models import load_settings


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env.local"
    path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
                "APP_TIMEZONE=America/New_York",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    outfits_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sma_outfits"
        / "config"
        / "outfits.yaml"
    )
    config = {
        "universe": {"symbols": ["SPY", "QQQ"]},
        "timeframes": {"live": ["1m"], "derived": ["1D"]},
        "archive": {"enabled": False, "root": str(tmp_path / "archive")},
        "storage_root": str(tmp_path / "storage"),
        "events_root": str(tmp_path / "events"),
        "outfits_path": str(outfits_path),
    }
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def settings(config_file: Path, env_file: Path):
    return load_settings(config_file, env_file)
