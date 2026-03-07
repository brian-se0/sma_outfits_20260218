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


def test_invalid_strategy_trigger_mode_rejected(tmp_path: Path) -> None:
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
    config = {"strategy": {"trigger_mode": "mixed_author_v1"}}
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="close_touch_or_cross"):
        load_settings(config_path=config_path, env_path=env_path)


def test_removed_signal_trigger_metadata_fields_rejected(tmp_path: Path) -> None:
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
        "signal": {
            "tolerance": 0.01,
            "trigger_mode": "bar_touch",
        }
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
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


def test_strategy_opposing_sides_same_route_key_allowed(tmp_path: Path) -> None:
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
    long_route = {
        "id": "route-long",
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
    short_route = {
        "id": "route-short",
        "symbol": "SPY",
        "timeframe": "1m",
        "outfit_id": "base2_nvda",
        "key_period": 16,
        "side": "SHORT",
        "signal_type": "automated_short",
        "micro_periods": [16],
        "ignore_close_below_key_when_micro_positive": False,
        "macro_gate": "none",
        "risk_mode": "singular_penny_only",
        "stop_offset": 0.01,
    }
    config = {
        "strategy": {
            "strict_routing": True,
            "routes": [long_route, short_route],
        }
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    settings = load_settings(config_path=config_path, env_path=env_path)
    assert {route.id for route in settings.strategy.routes} == {"route-long", "route-short"}
    assert {route.side for route in settings.strategy.routes} == {"LONG", "SHORT"}


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


def test_cross_symbol_context_enabled_requires_non_empty_rules(tmp_path: Path) -> None:
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
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                    "cross_symbol_context": {"enabled": True, "rules": []},
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="requires non-empty rules"):
        load_settings(config_path=config_path, env_path=env_path)


def test_cross_symbol_context_rejects_unknown_reference_route_id(tmp_path: Path) -> None:
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
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                    "cross_symbol_context": {
                        "enabled": True,
                        "rules": [
                            {
                                "reference_route_id": "missing-route",
                                "require_macro_positive": False,
                                "require_micro_positive": False,
                            }
                        ],
                    },
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown reference_route_id"):
        load_settings(config_path=config_path, env_path=env_path)


def test_cross_symbol_context_rejects_self_reference(tmp_path: Path) -> None:
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
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                    "cross_symbol_context": {
                        "enabled": True,
                        "rules": [
                            {
                                "reference_route_id": "route-1",
                                "require_macro_positive": False,
                                "require_micro_positive": False,
                            }
                        ],
                    },
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="self-reference is not allowed"):
        load_settings(config_path=config_path, env_path=env_path)


def test_cross_symbol_context_rejects_duplicate_reference_route_ids(tmp_path: Path) -> None:
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
                    "risk_mode": "singular_penny_only",
                    "stop_offset": 0.01,
                    "cross_symbol_context": {
                        "enabled": True,
                        "rules": [
                            {
                                "reference_route_id": "route-2",
                                "require_macro_positive": False,
                                "require_micro_positive": False,
                            },
                            {
                                "reference_route_id": "route-2",
                                "require_macro_positive": False,
                                "require_micro_positive": False,
                            },
                        ],
                    },
                },
                {
                    "id": "route-2",
                    "symbol": "QQQ",
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
                },
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate reference_route_id"):
        load_settings(config_path=config_path, env_path=env_path)


def test_strategy_route_accepts_penny_reference_break_risk_mode(tmp_path: Path) -> None:
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
                    "risk_mode": "penny_reference_break",
                    "stop_offset": 0.01,
                    "dynamic_reference_migration": True,
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    settings = load_settings(config_path=config_path, env_path=env_path)
    assert settings.strategy.routes[0].risk_mode == "penny_reference_break"
    assert settings.strategy.routes[0].dynamic_reference_migration is True


def test_strategy_route_accepts_close_reference_break_risk_mode(tmp_path: Path) -> None:
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
                    "ignore_close_below_key_when_micro_positive": True,
                    "macro_gate": "none",
                    "risk_mode": "close_reference_break",
                    "stop_offset": 0.01,
                    "dynamic_reference_migration": True,
                }
            ],
        },
    }
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    settings = load_settings(config_path=config_path, env_path=env_path)
    assert settings.strategy.routes[0].risk_mode == "close_reference_break"
    assert settings.strategy.routes[0].dynamic_reference_migration is True


def test_risk_dollar_per_trade_must_be_positive(tmp_path: Path) -> None:
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
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump({"risk": {"risk_dollar_per_trade": 0.0}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="risk.risk_dollar_per_trade must be > 0"):
        load_settings(config_path=config_path, env_path=env_path)


def test_close_only_routes_reject_non_default_inactive_risk_knobs(tmp_path: Path) -> None:
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
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "outfits_path": str(outfits_path),
                "risk": {
                    "partial_take_r": 2.0,
                    "final_take_r": 4.0,
                    "timeout_bars": 240,
                },
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
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inactive for close-only routes"):
        load_settings(config_path=config_path, env_path=env_path)


def test_execution_cost_scenario_lengths_must_match(tmp_path: Path) -> None:
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
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "execution_costs": {
                    "slippage_bps_scenarios": [2.0, 3.5, 5.0],
                    "commission_bps_scenarios": [0.5, 0.75],
                    "latency_bars_scenarios": [0, 1, 1],
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="commission_bps_scenarios length must match"):
        load_settings(config_path=config_path, env_path=env_path)


def test_missing_citation_pack_path_rejected(tmp_path: Path) -> None:
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
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "citations": {
                    "pack_path": str(tmp_path / "missing_citations.yaml"),
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="Citations pack not found"):
        load_settings(config_path=config_path, env_path=env_path)


def test_validation_regime_proxy_timeframe_accepts_supported_value(tmp_path: Path) -> None:
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
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump({"validation": {"regime": {"proxy_timeframe": "2h"}}}),
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_path=env_path)
    assert settings.validation.regime.proxy_timeframe == "2h"


def test_validation_regime_proxy_timeframe_rejects_unsupported_value(tmp_path: Path) -> None:
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
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(
        yaml.safe_dump({"validation": {"regime": {"proxy_timeframe": "13m"}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported validation.regime.proxy_timeframe"):
        load_settings(config_path=config_path, env_path=env_path)
