from __future__ import annotations

from pathlib import Path

from sma_outfits.config.models import load_settings


def _write_required_env(path: Path) -> None:
    path.write_text(
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


def test_mixed_trigger_profile_sets_author_trigger_mode(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_mixed_trigger_v1.yaml"
        ),
        env_path=env_path,
    )

    assert settings.strategy.trigger_mode == "mixed_author_v1"
    assert settings.strategy.mixed_trigger_volatility_lookback_bars == 20
    assert settings.strategy.mixed_trigger_volatility_percentile_threshold == 75.0


def test_mixed_trigger_profile_keeps_context_vixy_routes(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_mixed_trigger_v1.yaml"
        ),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    vixy_long = routes_by_id["vixy_30m_author"]
    short_route_ids = {
        route.id for route in settings.strategy.routes if route.signal_type == "automated_short"
    }

    assert vixy_long.key_period == 422
    assert vixy_long.micro_periods == [26, 52, 106, 211]
    assert short_route_ids == {
        "qqq_1h_author_short",
        "sqqq_30m_author_short",
        "svix_30m_author_short",
        "soxl_30m_author_short",
        "vixy_30m_author_short",
        "xlf_30m_author_short",
    }
