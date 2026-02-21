from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from sma_outfits.config.models import RouteRule
from sma_outfits.events import BarEvent, SignalEvent
from sma_outfits.risk.manager import RiskManager
from sma_outfits.signals.detector import RouteBarContext


def _route(
    *,
    route_id: str = "spy_1m_author",
    ignore_micro_override: bool = False,
    risk_mode: str = "singular_penny_only",
    atr_period: int = 14,
    atr_multiplier: float = 1.5,
) -> RouteRule:
    return RouteRule(
        id=route_id,
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=ignore_micro_override,
        macro_gate="none",
        risk_mode=risk_mode,  # type: ignore[arg-type]
        stop_offset=0.01,
        atr={
            "period": atr_period,
            "multiplier": atr_multiplier,
        },
    )


def _signal(signal_id: str, route_id: str, entry: float) -> SignalEvent:
    return SignalEvent(
        id=signal_id,
        strike_id=f"strike-{signal_id}",
        route_id=route_id,
        side="LONG",
        signal_type="optimized_buy",
        entry=entry,
        stop=entry - 0.01,
        confidence="HIGH",
        session_type="regular",
    )


def _bar(ts: datetime, close: float, high: float, low: float) -> BarEvent:
    return BarEvent(
        symbol="SPY",
        timeframe="1m",
        ts=ts,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1000,
        source="unit-test",
    )


def _history_from_rows(
    rows: list[tuple[str, float, float, float]],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [pd.Timestamp(ts).tz_convert("UTC") for ts, _, _, _ in rows],
            "high": [high for _, high, _, _ in rows],
            "low": [low for _, _, low, _ in rows],
            "close": [close for _, _, _, close in rows],
        }
    )


def test_singular_only_lifecycle_disables_partial_final_and_timeout() -> None:
    route = _route()
    manager = RiskManager(
        timeout_bars=1,
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=False,
    )
    opened_ts = datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc)
    position = manager.open_position(
        signal=_signal("singular", route.id, 100.0),
        symbol="SPY",
        ts=opened_ts,
    )

    same_bar = manager.evaluate_bar(
        position,
        _bar(opened_ts, close=102.0, high=110.0, low=99.5),
        proxy_prices={},
    )
    assert same_bar == []

    second_bar = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=1), close=103.0, high=111.0, low=100.2),
        proxy_prices={},
    )
    assert second_bar == []
    assert not position.closed

    stop_bar_events = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=2), close=99.8, high=100.1, low=99.0),
        proxy_prices={},
    )
    assert len(stop_bar_events) == 1
    assert stop_bar_events[0].reason == "singular_point_hard_stop"
    assert all(event.action != "partial_take" for event in stop_bar_events)


def test_micro_term_stop_override_keeps_position_open_until_micro_negative() -> None:
    route = _route(ignore_micro_override=True)
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=True,
    )
    opened_ts = datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc)
    position = manager.open_position(
        signal=_signal("override", route.id, 100.0),
        symbol="SPY",
        ts=opened_ts,
    )
    route_context_positive = RouteBarContext(
        route=route,
        key_sma=100.0,
        micro_positive=True,
        macro_positive=True,
    )

    events = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=1), close=100.2, high=100.3, low=99.98),
        proxy_prices={},
        route_context=route_context_positive,
    )
    assert events == []
    assert not position.closed

    route_context_negative = RouteBarContext(
        route=route,
        key_sma=100.0,
        micro_positive=False,
        macro_positive=True,
    )
    close_events = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=2), close=99.8, high=100.0, low=99.5),
        proxy_prices={},
        route_context=route_context_negative,
    )
    assert len(close_events) == 1
    assert close_events[0].reason == "singular_point_hard_stop"
    assert position.closed


def test_no_same_bar_exit_when_disabled() -> None:
    route = _route()
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=False,
    )
    opened_ts = datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc)
    position = manager.open_position(
        signal=_signal("same-bar", route.id, 100.0),
        symbol="SPY",
        ts=opened_ts,
    )

    same_bar_events = manager.evaluate_bar(
        position,
        _bar(opened_ts, close=99.7, high=100.0, low=99.0),
        proxy_prices={},
    )
    assert same_bar_events == []
    assert not position.closed

    next_bar_events = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=1), close=99.7, high=100.0, low=99.0),
        proxy_prices={},
    )
    assert len(next_bar_events) == 1
    assert next_bar_events[0].reason == "singular_point_hard_stop"


def test_risk_migration_rule_remains_supported() -> None:
    route = _route(route_id="amdl_1m_author")
    manager = RiskManager(
        migrations={
            "AMDL": {
                "proxy_symbol": "SMH",
                "break_level": 374.24,
                "mode": "below",
                "offset": 0.01,
            }
        },
        routes={route.id: route},
        allow_same_bar_exit=True,
    )
    signal = SignalEvent(
        id="migration",
        strike_id="strike-migration",
        route_id=route.id,
        side="LONG",
        signal_type="optimized_buy",
        entry=12.43,
        stop=12.42,
        confidence="HIGH",
        session_type="regular",
    )
    position = manager.open_position(
        signal=signal,
        symbol="AMDL",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    events = manager.evaluate_bar(
        position,
        _bar(datetime(2025, 1, 2, 15, 1, tzinfo=timezone.utc), close=12.5, high=12.55, low=12.4),
        proxy_prices={"SMH": 374.20},
    )
    assert len(events) == 1
    assert events[0].reason == "risk_migration_cut"


def test_requires_explicit_routes_and_proxy_mappings() -> None:
    route = _route()
    with pytest.raises(TypeError, match="routes must be an explicit dict"):
        RiskManager(migrations={}, routes=None)  # type: ignore[arg-type]

    manager = RiskManager(migrations={}, routes={route.id: route})
    position = manager.open_position(
        signal=_signal("proxy", route.id, 100.0),
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(TypeError, match="proxy_prices must be an explicit dict"):
        manager.evaluate_bar(
            position,
            _bar(datetime(2025, 1, 2, 15, 1, tzinfo=timezone.utc), close=100.0, high=100.2, low=99.8),
            proxy_prices=None,  # type: ignore[arg-type]
        )


def test_atr_dynamic_stop_lifecycle_updates_and_closes_position() -> None:
    route = _route(
        route_id="spy_1m_atr",
        risk_mode="atr_dynamic_stop",
        atr_period=2,
        atr_multiplier=1.0,
    )
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=True,
    )

    signal = _signal("atr", route.id, 100.0)
    entry_history = _history_from_rows(
        [
            ("2025-01-02T15:00:00Z", 101.0, 99.0, 100.0),
            ("2025-01-02T15:01:00Z", 102.0, 100.0, 101.0),
            ("2025-01-02T15:02:00Z", 103.0, 101.0, 102.0),
        ]
    )
    prepared_signal = manager.prepare_signal_for_entry(signal, route_history=entry_history)
    assert prepared_signal.stop == 98.0

    position = manager.open_position(
        signal=prepared_signal,
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 2, tzinfo=timezone.utc),
    )

    trailing_history = _history_from_rows(
        [
            ("2025-01-02T15:01:00Z", 102.0, 100.0, 101.0),
            ("2025-01-02T15:02:00Z", 103.0, 101.0, 102.0),
            ("2025-01-02T15:03:00Z", 105.0, 103.0, 104.0),
        ]
    )
    first_events = manager.evaluate_bar(
        position,
        _bar(datetime(2025, 1, 2, 15, 3, tzinfo=timezone.utc), close=104.0, high=105.0, low=103.0),
        proxy_prices={},
        route_history=trailing_history,
    )
    assert first_events == []
    assert position.stop == 101.5

    close_events = manager.evaluate_bar(
        position,
        _bar(datetime(2025, 1, 2, 15, 4, tzinfo=timezone.utc), close=102.1, high=102.2, low=101.5),
        proxy_prices={},
        route_history=trailing_history,
    )
    assert len(close_events) == 1
    assert close_events[0].reason == "atr_dynamic_stop"
    assert close_events[0].price == 101.5


def test_atr_dynamic_stop_requires_entry_lookback() -> None:
    route = _route(
        route_id="spy_1m_atr",
        risk_mode="atr_dynamic_stop",
        atr_period=3,
        atr_multiplier=1.5,
    )
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=True,
    )

    with pytest.raises(RuntimeError, match="ATR unavailable at entry"):
        manager.prepare_signal_for_entry(
            _signal("atr-missing", route.id, 100.0),
            route_history=_history_from_rows(
                [
                    ("2025-01-02T15:00:00Z", 101.0, 99.0, 100.0),
                    ("2025-01-02T15:01:00Z", 102.0, 100.0, 101.0),
                    ("2025-01-02T15:02:00Z", 103.0, 101.0, 102.0),
                ]
            ),
        )


def test_atr_dynamic_stop_requires_route_history_during_evaluation() -> None:
    route = _route(
        route_id="spy_1m_atr",
        risk_mode="atr_dynamic_stop",
        atr_period=2,
        atr_multiplier=1.0,
    )
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=True,
    )
    signal = manager.prepare_signal_for_entry(
        _signal("atr-history", route.id, 100.0),
        route_history=_history_from_rows(
            [
                ("2025-01-02T15:00:00Z", 101.0, 99.0, 100.0),
                ("2025-01-02T15:01:00Z", 102.0, 100.0, 101.0),
                ("2025-01-02T15:02:00Z", 103.0, 101.0, 102.0),
            ]
        ),
    )
    position = manager.open_position(
        signal=signal,
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 2, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError, match="requires explicit route_history input"):
        manager.evaluate_bar(
            position,
            _bar(datetime(2025, 1, 2, 15, 3, tzinfo=timezone.utc), close=102.0, high=102.5, low=101.5),
            proxy_prices={},
            route_history=None,
        )


def test_penny_reference_break_closes_on_primary_symbol_boundary() -> None:
    route = _route(
        route_id="spy_1m_refbreak",
        risk_mode="penny_reference_break",
    )
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=True,
    )
    opened_ts = datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc)
    route_context = RouteBarContext(
        route=route,
        key_sma=100.0,
        micro_positive=False,
        macro_positive=True,
    )
    position = manager.open_position(
        signal=_signal("refbreak-primary", route.id, 100.0),
        symbol="SPY",
        ts=opened_ts,
        route_context=route_context,
    )

    events = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=1), close=99.95, high=100.0, low=99.98),
        proxy_prices={},
        route_context=route_context,
    )
    assert len(events) == 1
    assert events[0].reason == "penny_reference_break"
    assert events[0].price == 99.99


def test_penny_reference_break_supports_cross_symbol_reference_cut() -> None:
    reference_route = RouteRule(
        id="qqq_1m_ref",
        symbol="QQQ",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    primary_route = RouteRule(
        id="spy_1m_primary",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="penny_reference_break",
        stop_offset=0.01,
        cross_symbol_context={
            "enabled": True,
            "rules": [
                {
                    "reference_route_id": "qqq_1m_ref",
                    "require_macro_positive": True,
                    "require_micro_positive": True,
                }
            ],
        },
    )
    manager = RiskManager(
        migrations={},
        routes={
            primary_route.id: primary_route,
            reference_route.id: reference_route,
        },
        allow_same_bar_exit=True,
    )
    opened_ts = datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc)
    primary_context = RouteBarContext(
        route=primary_route,
        key_sma=100.0,
        micro_positive=True,
        macro_positive=True,
    )
    reference_context = RouteBarContext(
        route=reference_route,
        key_sma=200.0,
        micro_positive=True,
        macro_positive=True,
    )
    position = manager.open_position(
        signal=_signal("refbreak-cross", primary_route.id, 100.0),
        symbol="SPY",
        ts=opened_ts,
        route_context=primary_context,
        cross_context_lookup=lambda route_id, _ts: (
            reference_context if route_id == "qqq_1m_ref" else None
        ),
    )

    events = manager.evaluate_bar(
        position,
        _bar(opened_ts + timedelta(minutes=1), close=100.2, high=100.3, low=100.1),
        proxy_prices={"QQQ": 199.98},
        route_context=primary_context,
    )
    assert len(events) == 1
    assert events[0].reason == "cross_symbol_reference_break"
    assert events[0].price == 199.98


def test_penny_reference_break_requires_route_context_on_open() -> None:
    route = _route(route_id="spy_1m_refbreak", risk_mode="penny_reference_break")
    manager = RiskManager(
        migrations={},
        routes={route.id: route},
        allow_same_bar_exit=True,
    )
    with pytest.raises(RuntimeError, match="requires explicit route_context"):
        manager.open_position(
            signal=_signal("refbreak-context", route.id, 100.0),
            symbol="SPY",
            ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
        )
