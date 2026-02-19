from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sma_outfits.events import BarEvent, SignalEvent
from sma_outfits.risk.manager import RiskManager


def _signal(signal_id: str, side: str, entry: float, stop: float) -> SignalEvent:
    return SignalEvent(
        id=signal_id,
        strike_id=f"strike-{signal_id}",
        side=side,  # type: ignore[arg-type]
        signal_type="precision_buy" if side == "LONG" else "automated_short",  # type: ignore[arg-type]
        entry=entry,
        stop=stop,
        confidence="HIGH",
        session_type="regular",
    )


def _bar(ts_minute: int, close: float, high: float, low: float) -> BarEvent:
    ts = datetime(2025, 1, 2, 15, ts_minute, tzinfo=timezone.utc)
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


def test_stop_logic_for_long_and_short() -> None:
    manager = RiskManager(migrations={})
    long = manager.open_position(
        signal=_signal("long", "LONG", 10.0, 9.99),
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    events = manager.evaluate_bar(
        long,
        _bar(1, close=9.995, high=10.01, low=9.98),
        proxy_prices={},
    )
    assert events and events[0].reason == "singular_point_hard_stop"

    short = manager.open_position(
        signal=_signal("short", "SHORT", 10.0, 10.01),
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    events = manager.evaluate_bar(
        short,
        _bar(2, close=10.005, high=10.02, low=9.99),
        proxy_prices={},
    )
    assert events and events[0].reason == "singular_point_hard_stop"


def test_partial_final_and_timeout_lifecycle() -> None:
    manager = RiskManager(timeout_bars=2, migrations={})
    position = manager.open_position(
        signal=_signal("lifecycle", "LONG", 100.0, 99.0),
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    first = manager.evaluate_bar(
        position,
        _bar(1, close=100.5, high=101.2, low=99.5),
        proxy_prices={},
    )
    assert any(event.action == "partial_take" for event in first)
    assert position.stop == 100.0

    second = manager.evaluate_bar(
        position,
        _bar(2, close=102.0, high=103.5, low=100.5),
        proxy_prices={},
    )
    assert any(event.reason == "+3R_final_take" for event in second)
    assert position.closed

    timeout_position = manager.open_position(
        signal=_signal("timeout", "LONG", 50.0, 49.0),
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    manager.evaluate_bar(
        timeout_position,
        _bar(3, close=50.2, high=50.3, low=49.8),
        proxy_prices={},
    )
    manager.evaluate_bar(
        timeout_position,
        _bar(4, close=50.2, high=50.25, low=49.9),
        proxy_prices={},
    )
    timeout_events = manager.evaluate_bar(
        timeout_position,
        _bar(5, close=50.1, high=50.2, low=49.9),
        proxy_prices={},
    )
    assert timeout_events and timeout_events[0].reason == "timeout"


def test_risk_migration_rule() -> None:
    manager = RiskManager(
        migrations={
            "AMDL": {
                "proxy_symbol": "SMH",
                "break_level": 374.24,
                "mode": "below",
                "offset": 0.01,
            }
        }
    )
    position = manager.open_position(
        signal=_signal("migration", "LONG", 12.43, 12.42),
        symbol="AMDL",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    events = manager.evaluate_bar(
        position,
        _bar(1, close=12.5, high=12.55, low=12.4),
        proxy_prices={"SMH": 374.20},
    )
    assert events and events[0].reason == "risk_migration_cut"


def test_requires_explicit_migrations_mapping() -> None:
    with pytest.raises(TypeError, match="migrations must be an explicit dict"):
        RiskManager(migrations=None)  # type: ignore[arg-type]


def test_requires_explicit_proxy_prices_mapping() -> None:
    manager = RiskManager(migrations={})
    position = manager.open_position(
        signal=_signal("proxy", "LONG", 10.0, 9.99),
        symbol="SPY",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(TypeError, match="proxy_prices must be an explicit dict"):
        manager.evaluate_bar(
            position,
            _bar(1, close=10.0, high=10.02, low=9.98),
            proxy_prices=None,  # type: ignore[arg-type]
        )
