from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sma_outfits.config.models import RouteRule
from sma_outfits.data.storage import StorageManager
from sma_outfits.replay.engine import ReplayEngine


def _author_test_settings(settings, tmp_path: Path):
    outfits_path = tmp_path / "author_routes_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: qqq_test",
                "    periods: [2, 3]",
                "    description: qqq test",
                "    source_configuration: qqq",
                "    source_ambiguous: false",
                "  - id: rwm_test",
                "    periods: [2, 3]",
                "    description: rwm test",
                "    source_configuration: rwm",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    replay_settings = settings.model_copy(deep=True)
    replay_settings.outfits_path = str(outfits_path)
    replay_settings.universe.symbols = ["QQQ", "RWM"]
    replay_settings.timeframes.live = ["30m", "1h"]
    replay_settings.archive.enabled = False
    replay_settings.strategy.price_basis = "close"
    replay_settings.strategy.strict_routing = True
    replay_settings.strategy.allow_same_bar_exit = False
    replay_settings.strategy.routes = [
        RouteRule(
            id="qqq_1h_test",
            symbol="QQQ",
            timeframe="1h",
            outfit_id="qqq_test",
            key_period=2,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[3],
            ignore_close_below_key_when_micro_positive=True,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
        RouteRule(
            id="rwm_30m_test",
            symbol="RWM",
            timeframe="30m",
            outfit_id="rwm_test",
            key_period=2,
            side="LONG",
            signal_type="magnetized_buy",
            micro_periods=[3],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
    ]
    return replay_settings


def _cross_context_test_settings(settings, tmp_path: Path):
    outfits_path = tmp_path / "cross_context_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: qqq_test",
                "    periods: [2, 3]",
                "    description: qqq test",
                "    source_configuration: qqq",
                "    source_ambiguous: false",
                "  - id: rwm_test",
                "    periods: [2, 3]",
                "    description: rwm test",
                "    source_configuration: rwm",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    replay_settings = settings.model_copy(deep=True)
    replay_settings.outfits_path = str(outfits_path)
    replay_settings.universe.symbols = ["QQQ", "RWM"]
    replay_settings.timeframes.live = ["30m", "1h"]
    replay_settings.archive.enabled = False
    replay_settings.strategy.price_basis = "close"
    replay_settings.strategy.strict_routing = True
    replay_settings.strategy.allow_same_bar_exit = False
    replay_settings.strategy.routes = [
        RouteRule(
            id="qqq_1h_ref",
            symbol="QQQ",
            timeframe="1h",
            outfit_id="qqq_test",
            key_period=2,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[3],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
        RouteRule(
            id="rwm_30m_cross",
            symbol="RWM",
            timeframe="30m",
            outfit_id="rwm_test",
            key_period=2,
            side="LONG",
            signal_type="magnetized_buy",
            micro_periods=[3],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
            cross_symbol_context={
                "enabled": True,
                "rules": [
                    {
                        "reference_route_id": "qqq_1h_ref",
                        "require_macro_positive": True,
                        "require_micro_positive": True,
                    }
                ],
            },
        ),
    ]
    return replay_settings


def _frame(
    *,
    start: str,
    freq: str,
    closes: list[float],
    lows: list[float],
) -> pd.DataFrame:
    ts = pd.date_range(start=start, periods=len(closes), freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "ts": ts,
            "open": closes,
            "high": [value + 0.2 for value in closes],
            "low": lows,
            "close": closes,
            "volume": [1000.0 for _ in closes],
        }
    )


@pytest.fixture
def rwm_jan31_regression_bars() -> pd.DataFrame:
    strike_index = 843
    total_bars = strike_index + 3
    timestamps = pd.date_range(
        start="2025-01-14T06:30:00Z",
        periods=total_bars,
        freq="30min",
        tz="UTC",
    )
    closes = [18.00 for _ in range(total_bars)]
    opens = [18.00 for _ in range(total_bars)]
    highs = [18.05 for _ in range(total_bars)]
    lows = [17.95 for _ in range(total_bars)]
    volumes = [1000.0 for _ in range(total_bars)]

    # Jan 31 strike bar crosses above key SMA with required volume spike.
    closes[strike_index] = 18.04
    opens[strike_index] = 18.04
    highs[strike_index] = 18.09
    lows[strike_index] = 17.99
    volumes[strike_index] = 2000.0

    # Post-entry rise that trails the ATR stop above entry.
    closes[strike_index + 1] = 18.40
    opens[strike_index + 1] = 18.40
    highs[strike_index + 1] = 18.45
    lows[strike_index + 1] = 18.30

    # Pullback that hits trailed ATR stop while still profitable.
    closes[strike_index + 2] = 18.20
    opens[strike_index + 2] = 18.20
    highs[strike_index + 2] = 18.22
    lows[strike_index + 2] = 18.18

    return pd.DataFrame(
        {
            "ts": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_replay_qqq_micro_positive_override_and_rwm_singular_close(
    settings,
    tmp_path: Path,
) -> None:
    replay_settings = _author_test_settings(settings, tmp_path)
    storage = StorageManager(Path(replay_settings.storage_root))

    qqq_bars = _frame(
        start="2025-01-02T14:00:00Z",
        freq="1h",
        closes=[100.0, 100.0, 101.0, 100.8, 100.2],
        lows=[99.8, 99.8, 100.8, 100.48, 100.0],
    )
    rwm_bars = _frame(
        start="2025-01-02T14:00:00Z",
        freq="30min",
        closes=[50.0, 50.0, 51.0, 50.6],
        lows=[49.9, 49.9, 50.8, 50.48],
    )
    storage.write_bars(qqq_bars, symbol="QQQ", timeframe="1h")
    storage.write_bars(rwm_bars, symbol="RWM", timeframe="30m")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:00:00Z"),
        end=pd.Timestamp("2025-01-03T00:00:00Z"),
        symbols=["QQQ", "RWM"],
        timeframes=["30m", "1h"],
    )

    qqq_signals = [signal for signal in result.signals if signal.route_id == "qqq_1h_test"]
    rwm_signals = [signal for signal in result.signals if signal.route_id == "rwm_30m_test"]
    assert len(qqq_signals) == 1
    assert len(rwm_signals) == 1
    assert qqq_signals[0].signal_type == "optimized_buy"
    assert rwm_signals[0].signal_type == "magnetized_buy"

    qqq_events = [event for event in result.position_events if event.signal_id == qqq_signals[0].id]
    rwm_events = [event for event in result.position_events if event.signal_id == rwm_signals[0].id]
    qqq_override_bar_ts = pd.Timestamp("2025-01-02T17:00:00Z").to_pydatetime()
    qqq_close_bar_ts = pd.Timestamp("2025-01-02T18:00:00Z").to_pydatetime()
    rwm_close_bar_ts = pd.Timestamp("2025-01-02T15:30:00Z").to_pydatetime()

    assert all(event.ts != qqq_override_bar_ts for event in qqq_events)
    assert any(event.ts == qqq_close_bar_ts for event in qqq_events)
    assert any(event.reason == "singular_point_hard_stop" for event in qqq_events)
    assert any(event.ts == rwm_close_bar_ts for event in rwm_events)
    assert any(event.reason == "singular_point_hard_stop" for event in rwm_events)
    open_events = [event for event in result.position_events if event.action == "open"]
    close_events = [event for event in result.position_events if event.action == "close"]
    assert len(open_events) == len(result.signals)
    assert len(close_events) == len(result.signals)


def test_replay_fails_when_outfits_path_missing(settings) -> None:
    broken_settings = settings.model_copy(deep=True)
    broken_settings.outfits_path = "does/not/exist/outfits.yaml"
    storage = StorageManager(Path(broken_settings.storage_root))

    try:
        ReplayEngine(settings=broken_settings, storage=storage)
    except FileNotFoundError as exc:
        assert "Configured outfits catalog path does not exist" in str(exc)
    else:
        raise AssertionError("Expected ReplayEngine initialization to fail")


def test_replay_atr_dynamic_stop_exits_with_atr_reason(settings, tmp_path: Path) -> None:
    outfits_path = tmp_path / "atr_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: atr_test",
                "    periods: [2, 3]",
                "    description: atr test",
                "    source_configuration: atr",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    replay_settings = settings.model_copy(deep=True)
    replay_settings.outfits_path = str(outfits_path)
    replay_settings.universe.symbols = ["SPY"]
    replay_settings.timeframes.live = ["1h"]
    replay_settings.archive.enabled = False
    replay_settings.strategy.price_basis = "close"
    replay_settings.strategy.strict_routing = True
    replay_settings.strategy.allow_same_bar_exit = False
    replay_settings.strategy.routes = [
        RouteRule(
            id="spy_1h_atr",
            symbol="SPY",
            timeframe="1h",
            outfit_id="atr_test",
            key_period=2,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[3],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="atr_dynamic_stop",
            stop_offset=0.01,
            atr={"period": 2, "multiplier": 1.0},
        )
    ]
    storage = StorageManager(Path(replay_settings.storage_root))
    bars = _frame(
        start="2025-01-02T14:00:00Z",
        freq="1h",
        closes=[100.0, 100.0, 101.0, 104.0, 102.0],
        lows=[99.8, 99.8, 100.8, 103.8, 101.0],
    )
    storage.write_bars(bars, symbol="SPY", timeframe="1h")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:00:00Z"),
        end=pd.Timestamp("2025-01-03T00:00:00Z"),
        symbols=["SPY"],
        timeframes=["1h"],
    )

    assert len(result.signals) >= 1
    assert any(event.reason == "atr_dynamic_stop" for event in result.position_events)


def test_replay_atr_dynamic_stop_fails_when_entry_atr_unavailable(
    settings,
    tmp_path: Path,
) -> None:
    outfits_path = tmp_path / "atr_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: atr_test",
                "    periods: [2, 3]",
                "    description: atr test",
                "    source_configuration: atr",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    replay_settings = settings.model_copy(deep=True)
    replay_settings.outfits_path = str(outfits_path)
    replay_settings.universe.symbols = ["SPY"]
    replay_settings.timeframes.live = ["1h"]
    replay_settings.archive.enabled = False
    replay_settings.strategy.price_basis = "close"
    replay_settings.strategy.strict_routing = True
    replay_settings.strategy.allow_same_bar_exit = False
    replay_settings.strategy.routes = [
        RouteRule(
            id="spy_1h_atr",
            symbol="SPY",
            timeframe="1h",
            outfit_id="atr_test",
            key_period=2,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[3],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="atr_dynamic_stop",
            stop_offset=0.01,
            atr={"period": 5, "multiplier": 1.0},
        )
    ]
    storage = StorageManager(Path(replay_settings.storage_root))
    bars = _frame(
        start="2025-01-02T14:00:00Z",
        freq="1h",
        closes=[100.0, 100.0, 101.0],
        lows=[99.8, 99.8, 100.8],
    )
    storage.write_bars(bars, symbol="SPY", timeframe="1h")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    try:
        engine.run(
            start=pd.Timestamp("2025-01-02T14:00:00Z"),
            end=pd.Timestamp("2025-01-03T00:00:00Z"),
            symbols=["SPY"],
            timeframes=["1h"],
        )
    except RuntimeError as exc:
        assert "ATR unavailable at entry" in str(exc)
    else:
        raise AssertionError("Expected replay ATR route to fail when entry ATR is unavailable")


def test_replay_regression_rwm_jan31_event_path_is_profitable(
    settings,
    tmp_path: Path,
    rwm_jan31_regression_bars: pd.DataFrame,
) -> None:
    outfits_path = tmp_path / "jan31_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: svix_211_116",
                "    periods: [26, 52, 116, 211, 422, 844]",
                "    description: svix route 116 variant",
                "    source_configuration: 26/52/116/211/422/844 (211)",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    replay_settings = settings.model_copy(deep=True)
    replay_settings.outfits_path = str(outfits_path)
    replay_settings.universe.symbols = ["RWM"]
    replay_settings.timeframes.live = ["30m"]
    replay_settings.archive.enabled = False
    replay_settings.strategy.price_basis = "ohlc4"
    replay_settings.strategy.strict_routing = True
    replay_settings.strategy.allow_same_bar_exit = False
    replay_settings.strategy.routes = [
        RouteRule(
            id="rwm_30m_jan31_regression",
            symbol="RWM",
            timeframe="30m",
            outfit_id="svix_211_116",
            key_period=844,
            side="LONG",
            signal_type="magnetized_buy",
            micro_periods=[26, 52, 116, 211, 422],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="atr_dynamic_stop",
            stop_offset=0.01,
            confluence={
                "enabled": True,
                "min_outfit_alignment_count": 3,
                "volume_lookback_bars": 20,
                "volume_spike_ratio": 1.5,
            },
            atr={"period": 14, "multiplier": 1.5},
        )
    ]
    storage = StorageManager(Path(replay_settings.storage_root))
    storage.write_bars(rwm_jan31_regression_bars, symbol="RWM", timeframe="30m")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-14T06:30:00Z"),
        end=pd.Timestamp("2025-01-31T21:00:00Z"),
        symbols=["RWM"],
        timeframes=["30m"],
    )

    assert len(result.strikes) == 1
    strike = result.strikes[0]
    assert strike.outfit_id == "svix_211_116"
    assert strike.bar_ts == pd.Timestamp("2025-01-31T20:00:00Z").to_pydatetime()

    assert len(result.signals) == 1
    signal = result.signals[0]
    assert signal.route_id == "rwm_30m_jan31_regression"
    assert signal.signal_type == "magnetized_buy"
    assert signal.entry == 18.0
    assert signal.stop < (signal.entry - 0.01)

    close_events = [event for event in result.position_events if event.action == "close"]
    assert len(close_events) == 1
    close_event = close_events[0]
    assert close_event.reason == "atr_dynamic_stop"
    assert close_event.ts == pd.Timestamp("2025-01-31T21:00:00Z").to_pydatetime()
    assert close_event.price > signal.entry

    assert result.summary["closed_positions"] == 1
    assert result.summary["win_rate"] == 1.0
    assert result.summary["r_outcome"]["total_realized_r"] > 0.0


def test_replay_cross_symbol_context_same_timestamp_pass(
    settings,
    tmp_path: Path,
) -> None:
    replay_settings = _cross_context_test_settings(settings, tmp_path)
    storage = StorageManager(Path(replay_settings.storage_root))
    qqq_bars = _frame(
        start="2025-01-02T14:00:00Z",
        freq="1h",
        closes=[100.0, 100.0, 101.0],
        lows=[99.8, 99.8, 100.8],
    )
    rwm_bars = _frame(
        start="2025-01-02T15:00:00Z",
        freq="30min",
        closes=[50.0, 50.0, 51.0],
        lows=[49.8, 49.8, 50.8],
    )
    storage.write_bars(qqq_bars, symbol="QQQ", timeframe="1h")
    storage.write_bars(rwm_bars, symbol="RWM", timeframe="30m")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:00:00Z"),
        end=pd.Timestamp("2025-01-02T17:00:00Z"),
        symbols=["QQQ", "RWM"],
        timeframes=["30m", "1h"],
    )

    rwm_signals = [signal for signal in result.signals if signal.route_id == "rwm_30m_cross"]
    assert len(rwm_signals) == 1


def test_replay_cross_symbol_context_same_timestamp_block(
    settings,
    tmp_path: Path,
) -> None:
    replay_settings = _cross_context_test_settings(settings, tmp_path)
    storage = StorageManager(Path(replay_settings.storage_root))
    qqq_bars = _frame(
        start="2025-01-02T14:00:00Z",
        freq="1h",
        closes=[100.0, 100.0, 99.0],
        lows=[99.8, 99.8, 98.8],
    )
    rwm_bars = _frame(
        start="2025-01-02T15:00:00Z",
        freq="30min",
        closes=[50.0, 50.0, 51.0],
        lows=[49.8, 49.8, 50.8],
    )
    storage.write_bars(qqq_bars, symbol="QQQ", timeframe="1h")
    storage.write_bars(rwm_bars, symbol="RWM", timeframe="30m")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:00:00Z"),
        end=pd.Timestamp("2025-01-02T17:00:00Z"),
        symbols=["QQQ", "RWM"],
        timeframes=["30m", "1h"],
    )

    rwm_signals = [signal for signal in result.signals if signal.route_id == "rwm_30m_cross"]
    assert rwm_signals == []


def test_replay_cross_symbol_context_missing_reference_bars_blocks_without_abort(
    settings,
    tmp_path: Path,
) -> None:
    replay_settings = _cross_context_test_settings(settings, tmp_path)
    storage = StorageManager(Path(replay_settings.storage_root))
    rwm_bars = _frame(
        start="2025-01-02T15:00:00Z",
        freq="30min",
        closes=[50.0, 50.0, 51.0],
        lows=[49.8, 49.8, 50.8],
    )
    storage.write_bars(rwm_bars, symbol="RWM", timeframe="30m")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:00:00Z"),
        end=pd.Timestamp("2025-01-02T17:00:00Z"),
        symbols=["QQQ", "RWM"],
        timeframes=["30m", "1h"],
    )

    rwm_signals = [signal for signal in result.signals if signal.route_id == "rwm_30m_cross"]
    assert rwm_signals == []


def test_replay_cross_symbol_context_preflight_fails_when_reference_pair_not_selected(
    settings,
    tmp_path: Path,
) -> None:
    replay_settings = _cross_context_test_settings(settings, tmp_path)
    storage = StorageManager(Path(replay_settings.storage_root))

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    with pytest.raises(RuntimeError, match="Cross-symbol context preflight failed for replay"):
        engine.run(
            start=pd.Timestamp("2025-01-02T14:00:00Z"),
            end=pd.Timestamp("2025-01-02T17:00:00Z"),
            symbols=["RWM"],
            timeframes=["30m"],
        )


def test_replay_penny_reference_break_closes_on_cross_symbol_invalidation(
    settings,
    tmp_path: Path,
) -> None:
    outfits_path = tmp_path / "penny_refbreak_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: qqq_outfit",
                "    periods: [1]",
                "    description: qqq",
                "    source_configuration: qqq",
                "    source_ambiguous: false",
                "  - id: spy_outfit",
                "    periods: [1]",
                "    description: spy",
                "    source_configuration: spy",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    replay_settings = settings.model_copy(deep=True)
    replay_settings.outfits_path = str(outfits_path)
    replay_settings.universe.symbols = ["QQQ", "SPY"]
    replay_settings.timeframes.live = ["1m"]
    replay_settings.archive.enabled = False
    replay_settings.strategy.price_basis = "close"
    replay_settings.strategy.strict_routing = True
    replay_settings.strategy.allow_same_bar_exit = False
    replay_settings.strategy.routes = [
        RouteRule(
            id="qqq_1m_ref",
            symbol="QQQ",
            timeframe="1m",
            outfit_id="qqq_outfit",
            key_period=1,
            side="LONG",
            signal_type="precision_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
        RouteRule(
            id="spy_1m_primary",
            symbol="SPY",
            timeframe="1m",
            outfit_id="spy_outfit",
            key_period=1,
            side="LONG",
            signal_type="precision_buy",
            micro_periods=[1],
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
        ),
    ]
    storage = StorageManager(Path(replay_settings.storage_root))
    qqq_bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-02T14:31:00Z"),
            ],
            "open": [200.0, 199.98],
            "high": [200.1, 200.0],
            "low": [199.9, 199.95],
            "close": [200.0, 199.98],
            "volume": [1000.0, 1100.0],
        }
    )
    spy_bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-02T14:31:00Z"),
            ],
            "open": [100.0, 100.2],
            "high": [100.1, 100.25],
            "low": [99.99, 100.15],
            "close": [100.0, 100.2],
            "volume": [900.0, 950.0],
        }
    )
    storage.write_bars(qqq_bars, symbol="QQQ", timeframe="1m")
    storage.write_bars(spy_bars, symbol="SPY", timeframe="1m")

    engine = ReplayEngine(settings=replay_settings, storage=storage)
    result = engine.run(
        start=pd.Timestamp("2025-01-02T14:30:00Z"),
        end=pd.Timestamp("2025-01-02T14:31:00Z"),
        symbols=["QQQ", "SPY"],
        timeframes=["1m"],
    )

    assert len(result.signals) >= 1
    assert any(
        event.reason == "cross_symbol_reference_break"
        for event in result.position_events
    )
