from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from sma_outfits.config.models import RouteRule
from sma_outfits.events import BarEvent, SMAState
from sma_outfits.signals.detector import (
    OutfitDefinition,
    RouteBarContext,
    StrikeDetector,
    load_outfits,
)


def _bar(
    *,
    symbol: str = "SPY",
    timeframe: str = "1m",
    close: float,
    volume: float = 1000.0,
    minute: int,
) -> BarEvent:
    ts = datetime(2025, 1, 2, 15, minute, tzinfo=timezone.utc)
    return BarEvent(
        symbol=symbol,
        timeframe=timeframe,
        ts=ts,
        open=close,
        high=close + 0.2,
        low=close - 0.2,
        close=close,
        volume=volume,
        source="unit-test",
    )


def _history(*closes: float, volumes: list[float] | None = None) -> pd.DataFrame:
    rows = list(closes)
    volume_rows = volumes if volumes is not None else [1000.0 for _ in rows]
    if len(volume_rows) != len(rows):
        raise ValueError("history volumes length must match closes length")
    return pd.DataFrame(
        {
            "close": rows,
            "open": rows,
            "high": [value + 0.1 for value in rows],
            "low": [value - 0.1 for value in rows],
            "volume": volume_rows,
        }
    )


def _state(bar: BarEvent, period: int, value: float) -> SMAState:
    return SMAState(bar.symbol, bar.timeframe, period, value, bar.ts)


def test_detector_emits_only_route_outfit() -> None:
    outfits = [
        OutfitDefinition("route_outfit", (10,), "route", "10"),
        OutfitDefinition("ignored_outfit", (20,), "ignored", "20"),
    ]
    routes = [
        RouteRule(
            id="spy_1m_route",
            symbol="SPY",
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
    ]
    detector = StrikeDetector(outfits=outfits, routes=routes, strict_routing=True, tolerance=0.01)
    bar = _bar(close=100.0, minute=0)
    states = {
        10: _state(bar, 10, 100.0),
        20: _state(bar, 20, 100.0),
    }
    strikes, signals = detector.detect(bar=bar, sma_states=states, history=_history(99.5, 100.0))

    assert len(strikes) == 1
    assert len(signals) == 1
    assert strikes[0].outfit_id == "route_outfit"
    assert strikes[0].period == 10
    assert signals[0].route_id == "spy_1m_route"
    assert signals[0].signal_type == "optimized_buy"


def test_close_touch_or_cross_trigger_long_and_short() -> None:
    long_route = RouteRule(
        id="long_route",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    short_route = RouteRule(
        id="short_route",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="SHORT",
        signal_type="automated_short",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    outfits = [OutfitDefinition("route_outfit", (10,), "route", "10")]
    detector = StrikeDetector(outfits=outfits, routes=[long_route, short_route], strict_routing=True)

    long_cross_bar = _bar(symbol="SPY", close=101.0, minute=1)
    long_cross_states = {10: _state(long_cross_bar, 10, 100.0)}
    _, long_cross_signals = detector.detect(
        bar=long_cross_bar,
        sma_states=long_cross_states,
        history=_history(99.0, 101.0),
    )
    assert len(long_cross_signals) == 1
    assert long_cross_signals[0].side == "LONG"

    long_touch_bar = _bar(symbol="SPY", close=100.009, minute=2)
    long_touch_states = {10: _state(long_touch_bar, 10, 100.0)}
    _, long_touch_signals = detector.detect(
        bar=long_touch_bar,
        sma_states=long_touch_states,
        history=_history(100.5, 100.009),
    )
    assert len(long_touch_signals) == 1
    assert long_touch_signals[0].side == "LONG"

    short_cross_bar = _bar(symbol="SPY", close=99.0, minute=3)
    short_cross_states = {10: _state(short_cross_bar, 10, 100.0)}
    _, short_cross_signals = detector.detect(
        bar=short_cross_bar,
        sma_states=short_cross_states,
        history=_history(101.0, 99.0),
    )
    assert len(short_cross_signals) == 1
    assert short_cross_signals[0].side == "SHORT"


def test_detector_rejects_unsupported_trigger_mode() -> None:
    route = RouteRule(
        id="long_route",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    outfits = [OutfitDefinition("route_outfit", (10,), "route", "10")]
    with pytest.raises(RuntimeError, match="Unsupported strategy trigger_mode"):
        StrikeDetector(
            outfits=outfits,
            routes=[route],
            strict_routing=True,
            trigger_mode="mixed_author_v1",
        )


def test_macro_gate_short_requires_bearish_regime() -> None:
    route = RouteRule(
        id="short_with_macro_gate",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="SHORT",
        signal_type="automated_short",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="nas",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[route],
        strict_routing=True,
    )

    bearish_bar = _bar(symbol="SPY", close=99.0, minute=9)
    bearish_states = {
        10: _state(bearish_bar, 10, 100.0),
        20: _state(bearish_bar, 20, 99.0),
        100: _state(bearish_bar, 100, 100.0),
    }
    _, bearish_signals = detector.detect(
        bar=bearish_bar,
        sma_states=bearish_states,
        history=_history(101.0, 99.0),
    )
    assert len(bearish_signals) == 1
    assert bearish_signals[0].side == "SHORT"

    bullish_bar = _bar(symbol="SPY", close=99.0, minute=10)
    bullish_states = {
        10: _state(bullish_bar, 10, 100.0),
        20: _state(bullish_bar, 20, 101.0),
        100: _state(bullish_bar, 100, 100.0),
    }
    _, bullish_signals = detector.detect(
        bar=bullish_bar,
        sma_states=bullish_states,
        history=_history(101.0, 99.0),
    )
    assert bullish_signals == []


def test_micro_confirmation_blocks_signal_when_not_positive() -> None:
    route = RouteRule(
        id="spy_1m_micro",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5, 8],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True)
    bar = _bar(close=100.0, minute=4)
    states = {
        10: _state(bar, 10, 100.0),
        5: _state(bar, 5, 99.0),
        8: _state(bar, 8, 101.0),
    }
    strikes, signals = detector.detect(bar=bar, sma_states=states, history=_history(99.0, 100.0))
    assert not strikes
    assert not signals


def test_micro_confirmation_allows_within_tolerance() -> None:
    route = RouteRule(
        id="spy_1m_micro_tol",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5, 8],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True, tolerance=0.01)
    bar = _bar(close=100.0, minute=6)
    states = {
        10: _state(bar, 10, 100.0),
        5: _state(bar, 5, 99.99),
        8: _state(bar, 8, 100.008),
    }
    strikes, signals = detector.detect(bar=bar, sma_states=states, history=_history(99.0, 100.0))
    assert len(strikes) == 1
    assert len(signals) == 1


def test_strict_routing_missing_route_fails() -> None:
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[
            RouteRule(
                id="qqq_1m_route",
                symbol="QQQ",
                timeframe="1m",
                outfit_id="route_outfit",
                key_period=10,
                side="LONG",
                signal_type="precision_buy",
                micro_periods=[10],
                ignore_close_below_key_when_micro_positive=False,
                macro_gate="none",
                risk_mode="singular_penny_only",
                stop_offset=0.01,
            )
        ],
        strict_routing=True,
    )
    bar = _bar(symbol="SPY", close=100.0, minute=5)
    with pytest.raises(RuntimeError, match="Strict routing violation"):
        detector.detect(
            bar=bar,
            sma_states={10: _state(bar, 10, 100.0)},
            history=_history(99.0, 100.0),
        )


def test_cross_symbol_context_passes_when_reference_matches() -> None:
    reference_route = RouteRule(
        id="qqq_1m_ref",
        symbol="QQQ",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    primary_route = RouteRule(
        id="spy_1m_cross",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        cross_symbol_context={
            "enabled": True,
            "rules": [
                {
                    "reference_route_id": "qqq_1m_ref",
                    "require_macro_positive": False,
                    "require_micro_positive": False,
                }
            ],
        },
    )
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[primary_route, reference_route],
        strict_routing=True,
    )
    bar = _bar(symbol="SPY", close=100.0, minute=12)
    states = {10: _state(bar, 10, 100.0)}
    reference_context = RouteBarContext(
        route=reference_route,
        key_sma=100.0,
        micro_positive=False,
        macro_positive=False,
    )

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.0, 100.0),
        cross_context_lookup=lambda route_id, _ts: (
            reference_context if route_id == "qqq_1m_ref" else None
        ),
    )
    assert len(strikes) == 1
    assert len(signals) == 1


def test_cross_symbol_context_fails_on_macro_mismatch() -> None:
    reference_route = RouteRule(
        id="qqq_1m_ref",
        symbol="QQQ",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    primary_route = RouteRule(
        id="spy_1m_cross",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        cross_symbol_context={
            "enabled": True,
            "rules": [
                {
                    "reference_route_id": "qqq_1m_ref",
                    "require_macro_positive": False,
                    "require_micro_positive": False,
                }
            ],
        },
    )
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[primary_route, reference_route],
        strict_routing=True,
    )
    bar = _bar(symbol="SPY", close=100.0, minute=13)
    states = {10: _state(bar, 10, 100.0)}
    reference_context = RouteBarContext(
        route=reference_route,
        key_sma=100.0,
        micro_positive=False,
        macro_positive=True,
    )

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.0, 100.0),
        cross_context_lookup=lambda _route_id, _ts: reference_context,
    )
    assert strikes == []
    assert signals == []


def test_cross_symbol_context_fails_on_micro_mismatch() -> None:
    reference_route = RouteRule(
        id="qqq_1m_ref",
        symbol="QQQ",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    primary_route = RouteRule(
        id="spy_1m_cross",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        cross_symbol_context={
            "enabled": True,
            "rules": [
                {
                    "reference_route_id": "qqq_1m_ref",
                    "require_macro_positive": False,
                    "require_micro_positive": False,
                }
            ],
        },
    )
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[primary_route, reference_route],
        strict_routing=True,
    )
    bar = _bar(symbol="SPY", close=100.0, minute=14)
    states = {10: _state(bar, 10, 100.0)}
    reference_context = RouteBarContext(
        route=reference_route,
        key_sma=100.0,
        micro_positive=True,
        macro_positive=False,
    )

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.0, 100.0),
        cross_context_lookup=lambda _route_id, _ts: reference_context,
    )
    assert strikes == []
    assert signals == []


def test_cross_symbol_context_fails_when_reference_missing() -> None:
    reference_route = RouteRule(
        id="qqq_1m_ref",
        symbol="QQQ",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
    )
    primary_route = RouteRule(
        id="spy_1m_cross",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        cross_symbol_context={
            "enabled": True,
            "rules": [
                {
                    "reference_route_id": "qqq_1m_ref",
                    "require_macro_positive": False,
                    "require_micro_positive": False,
                }
            ],
        },
    )
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[primary_route, reference_route],
        strict_routing=True,
    )
    bar = _bar(symbol="SPY", close=100.0, minute=15)
    states = {10: _state(bar, 10, 100.0)}

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.0, 100.0),
        cross_context_lookup=lambda _route_id, _ts: None,
    )
    assert strikes == []
    assert signals == []


def test_cross_symbol_context_requires_lookup_callback_when_enabled() -> None:
    primary_route = RouteRule(
        id="spy_1m_cross",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="precision_buy",
        micro_periods=[10],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        cross_symbol_context={
            "enabled": True,
            "rules": [
                {
                    "reference_route_id": "qqq_1m_ref",
                    "require_macro_positive": False,
                    "require_micro_positive": False,
                }
            ],
        },
    )
    detector = StrikeDetector(
        outfits=[OutfitDefinition("route_outfit", (10,), "route", "10")],
        routes=[primary_route],
        strict_routing=True,
    )
    bar = _bar(symbol="SPY", close=100.0, minute=16)
    states = {10: _state(bar, 10, 100.0)}

    with pytest.raises(RuntimeError, match="cross_symbol_context is enabled"):
        detector.detect(
            bar=bar,
            sma_states=states,
            history=_history(99.0, 100.0),
        )


def test_load_outfits_rejects_missing_required_keys(tmp_path) -> None:
    path = tmp_path / "outfits.yaml"
    path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test",
                "    periods: [10, 20]",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required keys"):
        load_outfits(path)


def test_load_outfits_accepts_complete_ambiguous_row(tmp_path) -> None:
    path = tmp_path / "outfits.yaml"
    path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test",
                "    periods: [10, 20]",
                "    description: ambiguous but complete",
                "    source_configuration: test",
                "    source_ambiguous: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    outfits = load_outfits(path)
    assert len(outfits) == 1
    assert outfits[0].source_ambiguous is True


def test_required_periods_expand_to_route_outfit_when_confluence_enabled() -> None:
    route = RouteRule(
        id="spy_1m_confluence",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        confluence={
            "enabled": True,
            "min_outfit_alignment_count": 2,
            "volume_lookback_bars": 3,
            "volume_spike_ratio": 1.5,
        },
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10, 20), "route", "5/8/10/20")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True)

    periods = detector.required_periods()
    assert periods.issuperset({5, 8, 10, 20})


def test_confluence_enabled_emits_signal_only_when_all_conditions_pass() -> None:
    route = RouteRule(
        id="spy_1m_confluence",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        confluence={
            "enabled": True,
            "min_outfit_alignment_count": 3,
            "volume_lookback_bars": 3,
            "volume_spike_ratio": 1.5,
        },
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True)
    bar = _bar(close=100.0, volume=2000.0, minute=7)
    states = {
        5: _state(bar, 5, 99.5),
        8: _state(bar, 8, 99.8),
        10: _state(bar, 10, 100.0),
    }

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.7, 99.8, 99.9, 100.0, volumes=[1000.0, 1000.0, 1000.0, 2000.0]),
    )
    assert len(strikes) == 1
    assert len(signals) == 1


def test_confluence_alignment_allows_within_tolerance() -> None:
    route = RouteRule(
        id="spy_1m_confluence_tol",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        confluence={
            "enabled": True,
            "min_outfit_alignment_count": 3,
            "volume_lookback_bars": 3,
            "volume_spike_ratio": 1.5,
        },
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True, tolerance=0.01)
    bar = _bar(close=100.0, volume=2000.0, minute=11)
    states = {
        5: _state(bar, 5, 99.99),
        8: _state(bar, 8, 100.008),
        10: _state(bar, 10, 100.0),
    }

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.7, 99.8, 99.9, 100.0, volumes=[1000.0, 1000.0, 1000.0, 2000.0]),
    )
    assert len(strikes) == 1
    assert len(signals) == 1


def test_confluence_fails_with_insufficient_outfit_alignment() -> None:
    route = RouteRule(
        id="spy_1m_confluence",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        confluence={
            "enabled": True,
            "min_outfit_alignment_count": 3,
            "volume_lookback_bars": 3,
            "volume_spike_ratio": 1.5,
        },
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True)
    bar = _bar(close=100.0, volume=2000.0, minute=8)
    states = {
        5: _state(bar, 5, 99.5),
        8: _state(bar, 8, 101.0),
        10: _state(bar, 10, 100.0),
    }

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.7, 99.8, 99.9, 100.0, volumes=[1000.0, 1000.0, 1000.0, 2000.0]),
    )
    assert strikes == []
    assert signals == []


def test_confluence_fails_without_volume_spike() -> None:
    route = RouteRule(
        id="spy_1m_confluence",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        confluence={
            "enabled": True,
            "min_outfit_alignment_count": 3,
            "volume_lookback_bars": 3,
            "volume_spike_ratio": 1.5,
        },
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True)
    bar = _bar(close=100.0, volume=1200.0, minute=9)
    states = {
        5: _state(bar, 5, 99.5),
        8: _state(bar, 8, 99.8),
        10: _state(bar, 10, 100.0),
    }

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(99.7, 99.8, 99.9, 100.0, volumes=[1000.0, 1000.0, 1000.0, 1200.0]),
    )
    assert strikes == []
    assert signals == []


def test_confluence_fails_when_touch_or_cross_condition_fails() -> None:
    route = RouteRule(
        id="spy_1m_confluence",
        symbol="SPY",
        timeframe="1m",
        outfit_id="route_outfit",
        key_period=10,
        side="LONG",
        signal_type="optimized_buy",
        micro_periods=[5],
        ignore_close_below_key_when_micro_positive=False,
        macro_gate="none",
        risk_mode="singular_penny_only",
        stop_offset=0.01,
        confluence={
            "enabled": True,
            "min_outfit_alignment_count": 3,
            "volume_lookback_bars": 3,
            "volume_spike_ratio": 1.1,
        },
    )
    outfits = [OutfitDefinition("route_outfit", (5, 8, 10), "route", "5/8/10")]
    detector = StrikeDetector(outfits=outfits, routes=[route], strict_routing=True)
    bar = _bar(close=102.0, volume=2000.0, minute=10)
    states = {
        5: _state(bar, 5, 100.0),
        8: _state(bar, 8, 100.0),
        10: _state(bar, 10, 100.0),
    }

    strikes, signals = detector.detect(
        bar=bar,
        sma_states=states,
        history=_history(101.5, 102.0, 102.0, 102.0, volumes=[1000.0, 1000.0, 1000.0, 2000.0]),
    )
    assert strikes == []
    assert signals == []
