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


def test_strategy_strict_routing_requires_routes(tmp_path: Path) -> None:
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
    config = {"strategy": {"strict_routing": True, "routes": []}}
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="strategy.routes must be non-empty"):
        load_settings(config_path=config_path, env_path=env_path)


def test_strategy_duplicate_route_key_rejected(tmp_path: Path) -> None:
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
    route = {
        "symbol": "SPY",
        "timeframe": "1m",
        "outfit_id": "base2_nvda",
        "key_period": 16,
        "side": "LONG",
        "signal_type": "precision_buy",
        "micro_periods": [16],
        "ignore_close_below_key_when_micro_positive": False,
        "macro_gate": "none",
        "risk_mode": "singular_penny_only",
        "stop_offset": 0.01,
    }
    config = {
        "strategy": {
            "strict_routing": True,
            "routes": [
                {"id": "route-1", **route},
                {"id": "route-2", **route},
            ],
        }
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate strategy route key"):
        load_settings(config_path=config_path, env_path=env_path)


def test_strategy_route_outfit_and_period_membership_validation(tmp_path: Path) -> None:
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
    outfits_path = tmp_path / "outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test_outfit",
                "    periods: [10, 20]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_missing_outfit = {
        "outfits_path": str(outfits_path),
        "strategy": {
            "strict_routing": True,
            "routes": [
                {
                    "id": "route-1",
                    "symbol": "SPY",
                    "timeframe": "1m",
                    "outfit_id": "unknown_outfit",
                    "key_period": 10,
                    "side": "LONG",
                    "signal_type": "precision_buy",
                    "micro_periods": [10],
                    "ignore_close_below_key_when_micro_positive": False,
                    "macro_gate": "none",
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                }
            ],
        },
    }
    missing_outfit_path = tmp_path / "missing_outfit.yaml"
    missing_outfit_path.write_text(
        yaml.safe_dump(config_missing_outfit),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown outfit_id"):
        load_settings(config_path=missing_outfit_path, env_path=env_path)

    config_bad_period = {
        "outfits_path": str(outfits_path),
        "strategy": {
            "strict_routing": True,
            "routes": [
                {
                    "id": "route-1",
                    "symbol": "SPY",
                    "timeframe": "1m",
                    "outfit_id": "test_outfit",
                    "key_period": 99,
                    "side": "LONG",
                    "signal_type": "precision_buy",
                    "micro_periods": [10],
                    "ignore_close_below_key_when_micro_positive": False,
                    "macro_gate": "none",
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                }
            ],
        },
    }
    bad_period_path = tmp_path / "bad_period.yaml"
    bad_period_path.write_text(
        yaml.safe_dump(config_bad_period),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="period\\(s\\) not present in outfit"):
        load_settings(config_path=bad_period_path, env_path=env_path)


def test_strategy_ambiguity_policy_fail_rejects_ambiguous_outfit(tmp_path: Path) -> None:
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
    outfits_path = tmp_path / "outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: ambiguous_outfit",
                "    periods: [10]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "outfits_path": str(outfits_path),
        "strategy": {
            "ambiguity_policy": "fail",
            "strict_routing": True,
            "routes": [
                {
                    "id": "route-1",
                    "symbol": "SPY",
                    "timeframe": "1m",
                    "outfit_id": "ambiguous_outfit",
                    "key_period": 10,
                    "side": "LONG",
                    "signal_type": "precision_buy",
                    "micro_periods": [10],
                    "ignore_close_below_key_when_micro_positive": False,
                    "macro_gate": "none",
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="references ambiguous outfit"):
        load_settings(config_path=config_path, env_path=env_path)


def test_strategy_route_confluence_alignment_bound_rejected(tmp_path: Path) -> None:
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
    outfits_path = tmp_path / "outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test_outfit",
                "    periods: [10, 20]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "outfits_path": str(outfits_path),
        "strategy": {
            "strict_routing": True,
            "routes": [
                {
                    "id": "route-1",
                    "symbol": "SPY",
                    "timeframe": "1m",
                    "outfit_id": "test_outfit",
                    "key_period": 10,
                    "side": "LONG",
                    "signal_type": "precision_buy",
                    "micro_periods": [10],
                    "ignore_close_below_key_when_micro_positive": False,
                    "macro_gate": "none",
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                    "confluence": {
                        "enabled": True,
                        "min_outfit_alignment_count": 3,
                        "volume_lookback_bars": 20,
                        "volume_spike_ratio": 1.5,
                    },
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="confluence.min_outfit_alignment_count=.*exceeds"):
        load_settings(config_path=config_path, env_path=env_path)


def test_strategy_route_atr_validation_rejects_non_positive_multiplier(tmp_path: Path) -> None:
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
    outfits_path = tmp_path / "outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test_outfit",
                "    periods: [10]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "outfits_path": str(outfits_path),
        "strategy": {
            "strict_routing": True,
            "routes": [
                {
                    "id": "route-1",
                    "symbol": "SPY",
                    "timeframe": "1m",
                    "outfit_id": "test_outfit",
                    "key_period": 10,
                    "side": "LONG",
                    "signal_type": "precision_buy",
                    "micro_periods": [10],
                    "ignore_close_below_key_when_micro_positive": False,
                    "macro_gate": "none",
                    "risk_mode": "atr_dynamic_stop",
                    "stop_offset": 0.01,
                    "atr": {"period": 14, "multiplier": 0.0},
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="atr multiplier must be > 0"):
        load_settings(config_path=config_path, env_path=env_path)
