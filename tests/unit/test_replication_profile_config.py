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


def _load_profile_settings(config_name: str, env_path: Path):
    return load_settings(config_path=Path(f"configs/{config_name}"), env_path=env_path)


def test_replication_profile_routes_match_context_profile(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    replication = _load_profile_settings(
        "settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml",
        env_path,
    )
    context = _load_profile_settings(
        "settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml",
        env_path,
    )

    replication_routes = [route.model_dump(mode="python") for route in replication.strategy.routes]
    context_routes = [route.model_dump(mode="python") for route in context.strategy.routes]
    assert replication_routes == context_routes


def test_replication_profile_validation_gates_match_strict_profile(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    replication = _load_profile_settings(
        "settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml",
        env_path,
    )
    strict = _load_profile_settings(
        "settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml",
        env_path,
    )

    assert replication.validation.wfo.min_closed_trades_per_fold == 14
    assert strict.validation.wfo.min_closed_trades_per_fold == 14
    assert (
        replication.validation.wfo.min_closed_trades_per_fold
        == strict.validation.wfo.min_closed_trades_per_fold
    )

    assert replication.validation.thresholds.fdr_qvalue_max == 0.05
    assert strict.validation.thresholds.fdr_qvalue_max == 0.05
    assert replication.validation.thresholds.fdr_qvalue_max == strict.validation.thresholds.fdr_qvalue_max

    assert replication.validation.multiple_testing.method == "fdr_bh"
    assert strict.validation.multiple_testing.method == "fdr_bh"
    assert replication.validation.multiple_testing.method == strict.validation.multiple_testing.method
