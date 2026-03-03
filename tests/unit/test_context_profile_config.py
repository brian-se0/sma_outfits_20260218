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


def test_context_profile_uses_vixy_422_context_routes(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"
        ),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    vixy_long = routes_by_id["vixy_30m_author"]
    vixy_short = routes_by_id["vixy_30m_author_short"]

    assert vixy_long.key_period == 422
    assert vixy_short.key_period == 422
    assert vixy_long.micro_periods == [26, 52, 106, 211]
    assert vixy_short.micro_periods == [26, 52, 106, 211]


def test_context_profile_preserves_svix_844_baseline_routes(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"
        ),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    svix_long = routes_by_id["svix_30m_author"]
    svix_short = routes_by_id["svix_30m_author_short"]

    assert svix_long.key_period == 844
    assert svix_short.key_period == 844
    assert svix_long.micro_periods == [26, 52, 106, 211, 422]
    assert svix_short.micro_periods == [26, 52, 106, 211, 422]
