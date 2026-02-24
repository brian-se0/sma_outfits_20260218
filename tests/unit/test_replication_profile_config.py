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


def test_replication_profile_has_soxl_1h_author_route(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml"
        ),
        env_path=env_path,
    )

    route = next((item for item in settings.strategy.routes if item.id == "soxl_1h_author"), None)
    assert route is not None
    assert route.symbol == "SOXL"
    assert route.timeframe == "1h"
    assert route.outfit_id == "warings_problem"
    assert route.key_period == 548
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [19, 37, 73, 143, 279]
    assert route.ignore_close_below_key_when_micro_positive is False
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True
    assert route.confluence.min_outfit_alignment_count == 2
    assert route.confluence.volume_lookback_bars == 20
    assert route.confluence.volume_spike_ratio == 1.2
    assert route.atr.period == 14
    assert route.atr.multiplier == 1.5
    assert route.cross_symbol_context.enabled is True
    assert len(route.cross_symbol_context.rules) == 2
    assert route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert route.cross_symbol_context.rules[0].require_macro_positive is True
    assert route.cross_symbol_context.rules[0].require_micro_positive is True
    assert route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert route.cross_symbol_context.rules[1].require_macro_positive is True
    assert route.cross_symbol_context.rules[1].require_micro_positive is True


def test_replication_profile_has_soxl_30m_author_warings_gate(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml"
        ),
        env_path=env_path,
    )

    route = next((item for item in settings.strategy.routes if item.id == "soxl_30m_author"), None)
    assert route is not None
    assert route.symbol == "SOXL"
    assert route.timeframe == "30m"
    assert route.outfit_id == "warings_problem"
    assert route.key_period == 548
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [19, 37, 73, 143, 279]
    assert route.ignore_close_below_key_when_micro_positive is False
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True
    assert route.confluence.min_outfit_alignment_count == 2
    assert route.confluence.volume_lookback_bars == 20
    assert route.confluence.volume_spike_ratio == 1.2
    assert route.atr.period == 14
    assert route.atr.multiplier == 1.5
    assert route.cross_symbol_context.enabled is True
    assert len(route.cross_symbol_context.rules) == 2
    assert route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert route.cross_symbol_context.rules[0].require_macro_positive is True
    assert route.cross_symbol_context.rules[0].require_micro_positive is True
    assert route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert route.cross_symbol_context.rules[1].require_macro_positive is True
    assert route.cross_symbol_context.rules[1].require_micro_positive is True


def test_replication_profile_tightens_weak_30m_cross_symbol_context(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path(
            "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml"
        ),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}

    svix_route = routes_by_id["svix_30m_author"]
    assert svix_route.cross_symbol_context.enabled is True
    assert len(svix_route.cross_symbol_context.rules) == 2
    assert svix_route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert svix_route.cross_symbol_context.rules[0].require_macro_positive is True
    assert svix_route.cross_symbol_context.rules[0].require_micro_positive is True
    assert svix_route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert svix_route.cross_symbol_context.rules[1].require_macro_positive is True
    assert svix_route.cross_symbol_context.rules[1].require_micro_positive is True

    sqqq_route = routes_by_id["sqqq_30m_author"]
    assert sqqq_route.cross_symbol_context.enabled is True
    assert len(sqqq_route.cross_symbol_context.rules) == 2
    assert sqqq_route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert sqqq_route.cross_symbol_context.rules[0].require_macro_positive is False
    assert sqqq_route.cross_symbol_context.rules[0].require_micro_positive is False
    assert sqqq_route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert sqqq_route.cross_symbol_context.rules[1].require_macro_positive is False
    assert sqqq_route.cross_symbol_context.rules[1].require_micro_positive is False

    xlf_route = routes_by_id["xlf_30m_author"]
    assert xlf_route.cross_symbol_context.enabled is True
    assert len(xlf_route.cross_symbol_context.rules) == 2
    assert xlf_route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert xlf_route.cross_symbol_context.rules[0].require_macro_positive is True
    assert xlf_route.cross_symbol_context.rules[0].require_micro_positive is True
    assert xlf_route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert xlf_route.cross_symbol_context.rules[1].require_macro_positive is True
    assert xlf_route.cross_symbol_context.rules[1].require_micro_positive is True

    vixy_route = routes_by_id["vixy_30m_author"]
    assert vixy_route.cross_symbol_context.enabled is True
    assert len(vixy_route.cross_symbol_context.rules) == 2
    assert vixy_route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert vixy_route.cross_symbol_context.rules[0].require_macro_positive is False
    assert vixy_route.cross_symbol_context.rules[0].require_micro_positive is False
    assert vixy_route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert vixy_route.cross_symbol_context.rules[1].require_macro_positive is False
    assert vixy_route.cross_symbol_context.rules[1].require_micro_positive is False

    tqqq_route = routes_by_id["tqqq_30m_author"]
    assert tqqq_route.cross_symbol_context.enabled is True
    assert len(tqqq_route.cross_symbol_context.rules) == 2
    assert tqqq_route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert tqqq_route.cross_symbol_context.rules[0].require_macro_positive is True
    assert tqqq_route.cross_symbol_context.rules[0].require_micro_positive is True
    assert tqqq_route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert tqqq_route.cross_symbol_context.rules[1].require_macro_positive is True
    assert tqqq_route.cross_symbol_context.rules[1].require_micro_positive is True

    spy_route = routes_by_id["spy_30m_author"]
    assert spy_route.cross_symbol_context.enabled is True
    assert len(spy_route.cross_symbol_context.rules) == 2
    assert spy_route.cross_symbol_context.rules[0].reference_route_id == "qqq_1h_author"
    assert spy_route.cross_symbol_context.rules[0].require_macro_positive is True
    assert spy_route.cross_symbol_context.rules[0].require_micro_positive is True
    assert spy_route.cross_symbol_context.rules[1].reference_route_id == "smh_2h_author"
    assert spy_route.cross_symbol_context.rules[1].require_macro_positive is True
    assert spy_route.cross_symbol_context.rules[1].require_micro_positive is True


def test_strict_profile_validation_targets_match_current_cycle(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        env_path=env_path,
    )

    assert settings.validation.scope_symbols == [
        "RWM",
        "SPY",
        "TQQQ",
        "SQQQ",
        "SVIX",
        "VIXY",
        "IWM",
        "XLF",
        "SOXL",
        "UPRO",
    ]
    assert settings.validation.wfo.train_months == 23
    assert settings.validation.wfo.test_months == 12
    assert settings.validation.wfo.step_months == 6
    assert settings.validation.wfo.min_folds == 3
    assert settings.validation.wfo.min_closed_trades_per_fold == 14
    assert settings.validation.thresholds.oos_sharpe_min == 1.5
    assert settings.validation.thresholds.oos_calmar_min == 2.0
    assert settings.validation.thresholds.bootstrap_pvalue_max == 0.06
    assert settings.validation.thresholds.fdr_qvalue_max == 0.05
    assert settings.validation.thresholds.replication_score_min == 0.7
