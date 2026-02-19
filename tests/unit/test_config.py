from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sma_outfits.config.models import load_settings


def test_missing_required_env_keys_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "ALPACA_API_KEY=test\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump({}), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required keys"):
        load_settings(config_path=config_path, env_path=env_path)


def test_invalid_timeframe_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {"timeframes": {"live": ["13m"], "derived": ["1D"]}}
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported timeframe"):
        load_settings(config_path=config_path, env_path=env_path)


def test_invalid_live_reconnect_bounds_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "live": {
            "reconnect_base_delay_seconds": 5.0,
            "reconnect_max_delay_seconds": 1.0,
        }
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="reconnect_max_delay_seconds"):
        load_settings(config_path=config_path, env_path=env_path)


def test_app_timezone_env_does_not_override_sessions_timezone_default(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
                "APP_TIMEZONE=UTC",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump({}), encoding="utf-8")

    settings = load_settings(config_path=config_path, env_path=env_path)
    assert settings.sessions.timezone == "America/New_York"


def test_missing_symbol_market_mapping_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "universe": {
            "symbols": ["SPY", "BTC/USD"],
            "symbol_markets": {"SPY": "stocks"},
        }
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="symbol_markets is missing entries"):
        load_settings(config_path=config_path, env_path=env_path)


def test_missing_timeframe_anchor_key_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {"timeframes": {"anchors": {"1W": "W-FRI", "1M": "ME"}}}
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="anchors is missing required keys"):
        load_settings(config_path=config_path, env_path=env_path)


def test_invalid_asof_date_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {"alpaca": {"asof": "20250101"}}
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="alpaca.asof must be valid YYYY-MM-DD"):
        load_settings(config_path=config_path, env_path=env_path)


def test_alpaca_base_url_with_path_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2",
                "ALPACA_DATA_URL=https://data.alpaca.markets",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump({}), encoding="utf-8")

    with pytest.raises(ValueError, match="alpaca.base_url must be host-only"):
        load_settings(config_path=config_path, env_path=env_path)


def test_alpaca_data_url_with_path_rejected(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "ALPACA_API_KEY=test-key",
                "ALPACA_SECRET_KEY=test-secret",
                "ALPACA_BASE_URL=https://paper-api.alpaca.markets",
                "ALPACA_DATA_URL=https://data.alpaca.markets/v2",
                "ALPACA_DATA_FEED=iex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump({}), encoding="utf-8")

    with pytest.raises(ValueError, match="alpaca.data_url must be host-only"):
        load_settings(config_path=config_path, env_path=env_path)
