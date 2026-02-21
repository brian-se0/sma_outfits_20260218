from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd

from sma_outfits.config.models import RouteRule
from sma_outfits.data.alpaca_clients import LiveBar, StreamDisconnectedError
from sma_outfits.data.storage import StorageManager
from sma_outfits.live import LiveRunner


class MockStreamFactory:
    def __init__(self) -> None:
        self._calls = 0

    def __call__(self, market: str, symbols: list[str]):
        self._calls += 1
        attempt = self._calls

        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            if attempt == 1:
                yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
                yield _bar("SPY", "2025-01-02T14:31:00Z", 101.0)
                raise StreamDisconnectedError("synthetic disconnect")

            yield _bar("SPY", "2025-01-02T14:31:00Z", 101.0)
            yield _bar("SPY", "2025-01-02T14:32:00Z", 102.0)
            while True:
                await asyncio.sleep(1.0)

        return _generator()


class MalformedStreamFactory:
    def __call__(self, market: str, symbols: list[str]):
        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
            yield {"T": "b", "symbol": "SPY"}  # type: ignore[misc]
            while True:
                await asyncio.sleep(1.0)

        return _generator()


class CrossContextStreamFactory:
    def __call__(self, market: str, symbols: list[str]):
        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            yield _bar("QQQ", "2025-01-02T14:30:00Z", 200.0)
            yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
            yield _bar("QQQ", "2025-01-02T14:31:00Z", 201.0)
            yield _bar("SPY", "2025-01-02T14:31:00Z", 101.0)
            while True:
                await asyncio.sleep(1.0)

        return _generator()


class DeterministicStreamFactory:
    def __call__(self, market: str, symbols: list[str]):
        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
            yield _bar("SPY", "2025-01-02T14:31:00Z", 101.0)
            while True:
                await asyncio.sleep(1.0)

        return _generator()


class GapAndStaleStreamFactory:
    def __call__(self, market: str, symbols: list[str]):
        async def _generator():
            if market != "stocks":
                while True:
                    await asyncio.sleep(1.0)
            yield _bar("QQQ", "2025-01-02T14:30:00Z", 200.0)
            yield _bar("SPY", "2025-01-02T14:30:00Z", 100.0)
            yield _bar("SPY", "2025-01-02T14:35:00Z", 102.0)
            while True:
                await asyncio.sleep(1.0)

        return _generator()


class MockReconciliationRESTClient:
    def fetch_open_positions(self):
        return [{"symbol": "QQQ"}]

    def fetch_open_orders(self):
        return [{"symbol": "QQQ"}]

    def fetch_bars(self, *args, **kwargs):
        raise RuntimeError("fetch_bars should not be called in this test")

    def fetch_calendar_sessions(self, *args, **kwargs):
        raise RuntimeError("fetch_calendar_sessions should not be called in this test")


def _live_settings_with_routes(
    settings,
    tmp_path: Path,
    routes: list[RouteRule],
):
    outfits_path = tmp_path / "test_outfits.yaml"
    outfits_path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test_outfit",
                "    periods: [1]",
                "    description: test",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    live_settings = settings.model_copy(deep=True)
    live_settings.outfits_path = str(outfits_path)
    live_settings.universe.symbols = list(dict.fromkeys([route.symbol for route in routes]))
    live_settings.timeframes.live = ["1m"]
    live_settings.archive.enabled = False
    live_settings.sessions.regular_only = False
    live_settings.strategy.strict_routing = True
    live_settings.strategy.routes = routes
    live_settings.live.reconnect_base_delay_seconds = 0.01
    live_settings.live.reconnect_max_delay_seconds = 0.01
    live_settings.live.reconnect_max_attempts = 3
    return live_settings


def test_live_pipeline_routed_pairs_succeed(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="spy_1m_author",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=True,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        )
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=MockStreamFactory(),
    )
    progress_snapshots: list[dict[str, object]] = []

    result = asyncio.run(
        runner.run(
            symbols=["SPY"],
            timeframes=["1m"],
            runtime_seconds=1.0,
            warmup_minutes=0,
            progress_callback=lambda payload: progress_snapshots.append(dict(payload)),
        )
    )

    assert result.reconnects >= 1
    assert progress_snapshots
    assert any(snapshot["status"] == "starting" for snapshot in progress_snapshots)
    assert any(snapshot["status"] == "completed" for snapshot in progress_snapshots)

    bars = storage.read_bars("SPY", "1m")
    assert len(bars) >= 2

    signals = storage.load_events("signals")
    strikes = storage.load_events("strikes")
    assert signals
    assert strikes


def test_live_pipeline_fails_fast_for_unrouted_pair(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="qqq_1m_author",
            symbol="QQQ",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=True,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        )
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=MockStreamFactory(),
    )

    try:
        asyncio.run(
            runner.run(
                symbols=["SPY"],
                timeframes=["1m"],
                runtime_seconds=0.3,
                warmup_minutes=0,
            )
        )
    except RuntimeError as exc:
        assert "Strict routing preflight failed for run-live" in str(exc)
    else:
        raise AssertionError("Expected live run to fail for unrouted pair")


def test_live_pipeline_fails_fast_on_malformed_stream_payload(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="spy_1m_author",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="precision_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        )
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    live_settings.live.reconnect_max_attempts = 1
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=MalformedStreamFactory(),
    )

    try:
        asyncio.run(
            runner.run(
                symbols=["SPY"],
                timeframes=["1m"],
                runtime_seconds=1.0,
                warmup_minutes=0,
            )
        )
    except RuntimeError as exc:
        assert "Fatal error in stocks live stream" in str(exc)
    else:
        raise AssertionError("Expected live run to fail on malformed payload")


def test_live_pipeline_supports_atr_route_selected(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="spy_1m_atr",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="atr_dynamic_stop",
            stop_offset=0.01,
            atr={"period": 1, "multiplier": 1.5},
        )
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=MockStreamFactory(),
    )

    result = asyncio.run(
        runner.run(
            symbols=["SPY"],
            timeframes=["1m"],
            runtime_seconds=1.0,
            warmup_minutes=0,
        )
    )
    assert result.bars_received >= 1


def test_live_pipeline_supports_cross_symbol_context_route_selected(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="qqq_1m_ref",
            symbol="QQQ",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
        RouteRule(
            id="spy_1m_cross",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
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
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=CrossContextStreamFactory(),
    )

    result = asyncio.run(
        runner.run(
            symbols=["QQQ", "SPY"],
            timeframes=["1m"],
            runtime_seconds=0.5,
            warmup_minutes=0,
        )
    )

    assert result.bars_received >= 2
    signals = storage.load_events("signals")
    assert any(signal["route_id"] == "spy_1m_cross" for signal in signals)


def test_live_pipeline_persists_state_and_prevents_duplicate_signals_on_restart(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="spy_1m_author",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        )
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    live_settings.live.state_persistence_enabled = True
    live_settings.live.state_file = str(Path(live_settings.storage_root) / "live_state.json")
    storage = StorageManager(Path(live_settings.storage_root))

    runner_one = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=DeterministicStreamFactory(),
    )
    asyncio.run(
        runner_one.run(
            symbols=["SPY"],
            timeframes=["1m"],
            runtime_seconds=0.4,
            warmup_minutes=0,
        )
    )
    first_signal_rows = storage.load_events("signals")
    assert first_signal_rows

    runner_two = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=DeterministicStreamFactory(),
    )
    asyncio.run(
        runner_two.run(
            symbols=["SPY"],
            timeframes=["1m"],
            runtime_seconds=0.4,
            warmup_minutes=0,
        )
    )
    second_signal_rows = storage.load_events("signals")
    assert len(second_signal_rows) == len(first_signal_rows)
    assert Path(live_settings.live.state_file).exists()


def test_live_pipeline_reports_data_gap_and_stale_symbol_monitoring(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="spy_1m_author",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
        RouteRule(
            id="qqq_1m_author",
            symbol="QQQ",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        ),
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    live_settings.live.data_gap_threshold_seconds = 60
    live_settings.live.symbol_stale_threshold_seconds = 120
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        stream_factory=GapAndStaleStreamFactory(),
    )

    result = asyncio.run(
        runner.run(
            symbols=["SPY", "QQQ"],
            timeframes=["1m"],
            runtime_seconds=0.5,
            warmup_minutes=0,
        )
    )

    assert result.data_gaps_detected >= 1
    assert result.stale_symbol_warnings >= 1


def test_live_pipeline_reconciliation_tracks_mismatch_counts(
    settings,
    tmp_path: Path,
) -> None:
    routes = [
        RouteRule(
            id="spy_1m_author",
            symbol="SPY",
            timeframe="1m",
            outfit_id="test_outfit",
            key_period=1,
            side="LONG",
            signal_type="optimized_buy",
            micro_periods=[1],
            ignore_close_below_key_when_micro_positive=False,
            macro_gate="none",
            risk_mode="singular_penny_only",
            stop_offset=0.01,
        )
    ]
    live_settings = _live_settings_with_routes(settings, tmp_path, routes)
    live_settings.live.reconciliation_enabled = True
    live_settings.live.reconciliation_interval_seconds = 0.01
    storage = StorageManager(Path(live_settings.storage_root))
    runner = LiveRunner(
        settings=live_settings,
        storage=storage,
        rest_client=MockReconciliationRESTClient(),  # type: ignore[arg-type]
        stream_factory=DeterministicStreamFactory(),
    )

    result = asyncio.run(
        runner.run(
            symbols=["SPY"],
            timeframes=["1m"],
            runtime_seconds=0.4,
            warmup_minutes=0,
        )
    )

    assert result.reconciliation_checks >= 1
    assert result.reconciliation_mismatches >= 1


def _bar(symbol: str, ts: str, close: float) -> LiveBar:
    timestamp = pd.Timestamp(ts).tz_convert("UTC")
    return LiveBar(
        symbol=symbol,
        ts=timestamp,
        open=close - 0.05,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1000.0,
        source="mock",
    )
