from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sma_outfits.config.models import RouteRule
from sma_outfits.events import BarEvent, SignalEvent
from sma_outfits.risk.manager import RiskManager
from sma_outfits.signals.detector import RouteBarContext


def _route(
    *,
    route_id: str = "spy_1m_author",
    ignore_micro_override: bool = False,
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
        risk_mode="singular_penny_only",
        stop_offset=0.01,
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
