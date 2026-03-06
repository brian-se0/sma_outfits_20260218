from __future__ import annotations

from pathlib import Path

from sma_outfits import cli
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

    assert svix_long.key_period == 844
    assert svix_long.micro_periods == [26, 52, 106, 211, 422]


def test_strict_profile_keeps_vixy_844_baseline_routes(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    vixy_long = routes_by_id["vixy_30m_author"]

    assert vixy_long.key_period == 844
    assert vixy_long.micro_periods == [26, 52, 106, 211, 422]


def test_active_profiles_use_isolated_artifact_roots(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    strict_settings = load_settings(
        config_path=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        env_path=env_path,
    )
    context_settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"
        ),
        env_path=env_path,
    )

    assert strict_settings.archive.root == "artifacts/svix211_106/strict"
    assert strict_settings.storage_root == "artifacts/svix211_106/strict/storage"
    assert strict_settings.events_root == "artifacts/svix211_106/strict/events"
    assert context_settings.archive.root == "artifacts/svix211_106/context"
    assert context_settings.storage_root == "artifacts/svix211_106/context/storage"
    assert context_settings.events_root == "artifacts/svix211_106/context/events"


def test_cli_default_readiness_outputs_follow_profile_namespace() -> None:
    assert cli._default_readiness_output(
        Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        "readiness_acceptance.json",
    ) == Path("artifacts/readiness/strict/readiness_acceptance.json")
    assert cli._default_readiness_output(
        Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"),
        "paper_hardening_init.json",
    ) == Path("artifacts/readiness/context/paper_hardening_init.json")


def test_cli_default_config_path_remains_context() -> None:
    assert cli._DEFAULT_CONFIG_PATH == Path(
        "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"
    )
    assert not hasattr(cli, "_REPLICATION_CONFIG_PATH")
