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


def test_qqq_1h_pair_config_is_isolated_and_scoped(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/qqq_1h.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}

    assert set(routes_by_id) == {"qqq_1h_author", "qqq_1h_author_short"}
    assert set(settings.universe.symbols) == {"QQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["QQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/qqq_1h/context"
    assert settings.storage_root == "artifacts/pairs/qqq_1h/context/storage"
    assert settings.events_root == "artifacts/pairs/qqq_1h/context/events"

    for route_id, expected_side in (
        ("qqq_1h_author", "LONG"),
        ("qqq_1h_author_short", "SHORT"),
    ):
        route = routes_by_id[route_id]
        assert route.symbol == "QQQ"
        assert route.timeframe == "1h"
        assert route.outfit_id == "base2_nvda"
        assert route.key_period == 512
        assert route.side == expected_side
        assert route.macro_gate == "nas"
        assert route.risk_mode == "penny_reference_break"
        assert route.stop_offset == 0.01
        assert route.dynamic_reference_migration is True


def test_qqq_1h_evidence_long_pair_config_is_isolated_and_scoped(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/qqq_1h_evidence_long.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"qqq_1h_author"}
    assert set(settings.universe.symbols) == {"QQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["QQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/qqq_1h_evidence_long/context"
    assert settings.storage_root == "artifacts/pairs/qqq_1h_evidence_long/context/storage"
    assert settings.events_root == "artifacts/pairs/qqq_1h_evidence_long/context/events"

    route = routes_by_id["qqq_1h_author"]
    assert route.symbol == "QQQ"
    assert route.timeframe == "1h"
    assert route.outfit_id == "base2_nvda"
    assert route.key_period == 512
    assert route.side == "LONG"
    assert route.signal_type == "optimized_buy"
    assert route.macro_gate == "nas"
    assert route.risk_mode == "close_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.ignore_close_below_key_when_micro_positive is True
    assert route.confluence.enabled is False


def test_spy_30m_pair_config_uses_spx_system_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/spy_30m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"spy_30m_author"}
    assert set(settings.universe.symbols) == {"SPY", "VIXY"}
    assert settings.validation.scope_symbols == ["SPY"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/spy_30m/context"
    assert settings.storage_root == "artifacts/pairs/spy_30m/context/storage"
    assert settings.events_root == "artifacts/pairs/spy_30m/context/events"

    route = routes_by_id["spy_30m_author"]
    assert route.symbol == "SPY"
    assert route.timeframe == "30m"
    assert route.outfit_id == "spx_system"
    assert route.key_period == 200
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [10, 50]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_spy_5m_pair_config_uses_spy_29_58_116_232_464_928_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/spy_5m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"spy_5m_author"}
    assert set(settings.universe.symbols) == {"SPY", "VIXY"}
    assert settings.validation.scope_symbols == ["SPY"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/spy_5m/context"
    assert settings.storage_root == "artifacts/pairs/spy_5m/context/storage"
    assert settings.events_root == "artifacts/pairs/spy_5m/context/events"

    route = routes_by_id["spy_5m_author"]
    assert route.symbol == "SPY"
    assert route.timeframe == "5m"
    assert route.outfit_id == "spy_29_58_116_232_464_928"
    assert route.key_period == 464
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [29, 58, 116, 232]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_qqq_20m_pair_config_uses_nas_system_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/qqq_20m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"qqq_20m_author"}
    assert set(settings.universe.symbols) == {"QQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["QQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/qqq_20m/context"
    assert settings.storage_root == "artifacts/pairs/qqq_20m/context/storage"
    assert settings.events_root == "artifacts/pairs/qqq_20m/context/events"

    route = routes_by_id["qqq_20m_author"]
    assert route.symbol == "QQQ"
    assert route.timeframe == "20m"
    assert route.outfit_id == "nas_system"
    assert route.key_period == 250
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [20, 100]
    assert route.macro_gate == "nas"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_qqq_30m_pair_config_uses_nas_system_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/qqq_30m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"qqq_30m_author"}
    assert set(settings.universe.symbols) == {"QQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["QQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/qqq_30m/context"
    assert settings.storage_root == "artifacts/pairs/qqq_30m/context/storage"
    assert settings.events_root == "artifacts/pairs/qqq_30m/context/events"

    route = routes_by_id["qqq_30m_author"]
    assert route.symbol == "QQQ"
    assert route.timeframe == "30m"
    assert route.outfit_id == "nas_system"
    assert route.key_period == 250
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [20, 100]
    assert route.macro_gate == "nas"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_dia_15m_pair_config_uses_dji_system_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/dia_15m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"dia_15m_author"}
    assert set(settings.universe.symbols) == {"DIA", "VIXY"}
    assert settings.validation.scope_symbols == ["DIA"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/dia_15m/context"
    assert settings.storage_root == "artifacts/pairs/dia_15m/context/storage"
    assert settings.events_root == "artifacts/pairs/dia_15m/context/events"

    route = routes_by_id["dia_15m_author"]
    assert route.symbol == "DIA"
    assert route.timeframe == "15m"
    assert route.outfit_id == "dji_system"
    assert route.key_period == 900
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [30, 60, 90, 300, 600]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_dia_1h_pair_config_uses_dji_system_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/dia_1h.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"dia_1h_author"}
    assert set(settings.universe.symbols) == {"DIA", "VIXY"}
    assert settings.validation.scope_symbols == ["DIA"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/dia_1h/context"
    assert settings.storage_root == "artifacts/pairs/dia_1h/context/storage"
    assert settings.events_root == "artifacts/pairs/dia_1h/context/events"

    route = routes_by_id["dia_1h_author"]
    assert route.symbol == "DIA"
    assert route.timeframe == "1h"
    assert route.outfit_id == "dji_system"
    assert route.key_period == 900
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [30, 60, 90, 300, 600]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_erx_30m_pair_config_uses_an_22_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/erx_30m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"erx_30m_author"}
    assert set(settings.universe.symbols) == {"ERX", "VIXY"}
    assert settings.validation.scope_symbols == ["ERX"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/erx_30m/context"
    assert settings.storage_root == "artifacts/pairs/erx_30m/context/storage"
    assert settings.events_root == "artifacts/pairs/erx_30m/context/events"

    route = routes_by_id["erx_30m_author"]
    assert route.symbol == "ERX"
    assert route.timeframe == "30m"
    assert route.outfit_id == "an_22"
    assert route.key_period == 777
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [22, 55, 77, 222, 555]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_qqq_1m_pair_config_uses_an_11_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/qqq_1m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"qqq_1m_author"}
    assert set(settings.universe.symbols) == {"QQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["QQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/qqq_1m/context"
    assert settings.storage_root == "artifacts/pairs/qqq_1m/context/storage"
    assert settings.events_root == "artifacts/pairs/qqq_1m/context/events"

    route = routes_by_id["qqq_1m_author"]
    assert route.symbol == "QQQ"
    assert route.timeframe == "1m"
    assert route.outfit_id == "an_11"
    assert route.key_period == 444
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [11, 44, 88, 111]
    assert route.macro_gate == "nas"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_soxl_2h_pair_config_uses_us_president_46_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/soxl_2h.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"soxl_2h_author"}
    assert set(settings.universe.symbols) == {"SOXL", "VIXY"}
    assert settings.validation.scope_symbols == ["SOXL"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/soxl_2h/context"
    assert settings.storage_root == "artifacts/pairs/soxl_2h/context/storage"
    assert settings.events_root == "artifacts/pairs/soxl_2h/context/events"

    route = routes_by_id["soxl_2h_author"]
    assert route.symbol == "SOXL"
    assert route.timeframe == "2h"
    assert route.outfit_id == "us_president_46"
    assert route.key_period == 736
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [23, 46, 92, 184, 368]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_sqqq_15m_pair_config_uses_russia_president_2000_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/sqqq_15m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"sqqq_15m_author"}
    assert set(settings.universe.symbols) == {"SQQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["SQQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/sqqq_15m/context"
    assert settings.storage_root == "artifacts/pairs/sqqq_15m/context/storage"
    assert settings.events_root == "artifacts/pairs/sqqq_15m/context/events"

    route = routes_by_id["sqqq_15m_author"]
    assert route.symbol == "SQQQ"
    assert route.timeframe == "15m"
    assert route.outfit_id == "russia_president_2000"
    assert route.key_period == 31
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [31]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_sqqq_30m_pair_config_uses_an_33_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/sqqq_30m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"sqqq_30m_author"}
    assert set(settings.universe.symbols) == {"SQQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["SQQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/sqqq_30m/context"
    assert settings.storage_root == "artifacts/pairs/sqqq_30m/context/storage"
    assert settings.events_root == "artifacts/pairs/sqqq_30m/context/events"

    route = routes_by_id["sqqq_30m_author"]
    assert route.symbol == "SQQQ"
    assert route.timeframe == "30m"
    assert route.outfit_id == "an_33"
    assert route.key_period == 33
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [33]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_svxy_1h_pair_config_uses_turkiye_president_12_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/svxy_1h.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"svxy_1h_author"}
    assert set(settings.universe.symbols) == {"SVXY", "VIXY"}
    assert settings.validation.scope_symbols == ["SVXY"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/svxy_1h/context"
    assert settings.storage_root == "artifacts/pairs/svxy_1h/context/storage"
    assert settings.events_root == "artifacts/pairs/svxy_1h/context/events"

    route = routes_by_id["svxy_1h_author"]
    assert route.symbol == "SVXY"
    assert route.timeframe == "1h"
    assert route.outfit_id == "turkiye_president_12"
    assert route.key_period == 384
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [24, 48, 96, 192]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_iwm_1d_pair_config_uses_base_10_50_iwm_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/iwm_1d.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"iwm_1d_author"}
    assert set(settings.universe.symbols) == {"IWM", "VIXY"}
    assert settings.validation.scope_symbols == ["IWM"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/iwm_1d/context"
    assert settings.storage_root == "artifacts/pairs/iwm_1d/context/storage"
    assert settings.events_root == "artifacts/pairs/iwm_1d/context/events"

    route = routes_by_id["iwm_1d_author"]
    assert route.symbol == "IWM"
    assert route.timeframe == "1D"
    assert route.outfit_id == "base_10_50_iwm"
    assert route.key_period == 50
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [10]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_svix_1d_pair_config_uses_svix_17_33_66_132_264_528_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/svix_1d.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"svix_1d_author"}
    assert set(settings.universe.symbols) == {"SVIX", "VIXY"}
    assert settings.validation.scope_symbols == ["SVIX"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/svix_1d/context"
    assert settings.storage_root == "artifacts/pairs/svix_1d/context/storage"
    assert settings.events_root == "artifacts/pairs/svix_1d/context/events"

    route = routes_by_id["svix_1d_author"]
    assert route.symbol == "SVIX"
    assert route.timeframe == "1D"
    assert route.outfit_id == "svix_17_33_66_132_264_528"
    assert route.key_period == 528
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [17, 33, 66, 132, 264]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_tsla_2h_pair_config_uses_tsla_33_66_131_262_626_919_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/tsla_2h.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"tsla_2h_author"}
    assert set(settings.universe.symbols) == {"TSLA", "VIXY"}
    assert settings.validation.scope_symbols == ["TSLA"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/tsla_2h/context"
    assert settings.storage_root == "artifacts/pairs/tsla_2h/context/storage"
    assert settings.events_root == "artifacts/pairs/tsla_2h/context/events"

    route = routes_by_id["tsla_2h_author"]
    assert route.symbol == "TSLA"
    assert route.timeframe == "2h"
    assert route.outfit_id == "tsla_33_66_131_262_626_919"
    assert route.key_period == 919
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [33, 66, 131, 262, 626]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_tqqq_10m_pair_config_uses_warings_problem_and_is_isolated(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/tqqq_10m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"tqqq_10m_author"}
    assert set(settings.universe.symbols) == {"TQQQ", "VIXY"}
    assert settings.validation.scope_symbols == ["TQQQ"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/tqqq_10m/context"
    assert settings.storage_root == "artifacts/pairs/tqqq_10m/context/storage"
    assert settings.events_root == "artifacts/pairs/tqqq_10m/context/events"

    route = routes_by_id["tqqq_10m_author"]
    assert route.symbol == "TQQQ"
    assert route.timeframe == "10m"
    assert route.outfit_id == "warings_problem"
    assert route.key_period == 279
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [19, 37, 73, 143]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


def test_nvda_30m_pair_config_uses_ma50_nvda_and_is_isolated(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    _write_required_env(env_path)

    settings = load_settings(
        config_path=Path("configs/pairs/context/nvda_30m.yaml"),
        env_path=env_path,
    )

    routes_by_id = {route.id: route for route in settings.strategy.routes}
    assert set(routes_by_id) == {"nvda_30m_author"}
    assert set(settings.universe.symbols) == {"NVDA", "VIXY"}
    assert settings.validation.scope_symbols == ["NVDA"]
    assert settings.validation.regime.proxy_symbol == "VIXY"
    assert settings.archive.root == "artifacts/pairs/nvda_30m/context"
    assert settings.storage_root == "artifacts/pairs/nvda_30m/context/storage"
    assert settings.events_root == "artifacts/pairs/nvda_30m/context/events"

    route = routes_by_id["nvda_30m_author"]
    assert route.symbol == "NVDA"
    assert route.timeframe == "30m"
    assert route.outfit_id == "ma50_nvda"
    assert route.key_period == 50
    assert route.side == "LONG"
    assert route.signal_type == "magnetized_buy"
    assert route.micro_periods == [50]
    assert route.macro_gate == "none"
    assert route.risk_mode == "penny_reference_break"
    assert route.stop_offset == 0.01
    assert route.dynamic_reference_migration is True
    assert route.confluence.enabled is True


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
