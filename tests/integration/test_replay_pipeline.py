from __future__ import annotations

from pathlib import Path

import pandas as pd

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
