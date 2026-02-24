from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from sma_outfits import cli
from sma_outfits.data.storage import StorageManager


def _write_readiness_bars(
    *,
    storage: StorageManager,
    start: str,
    end: str,
) -> None:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    month_range_start = pd.Timestamp(
        year=start_ts.year,
        month=start_ts.month,
        day=1,
        tz="UTC",
    )
    month_starts = pd.date_range(start=month_range_start, end=end_ts.normalize(), freq="MS", tz="UTC")
    ts_values: list[pd.Timestamp] = [start_ts]
    close_values: list[float] = [100.0]
    last_close = 100.0
    month_index = 0
    for month_start in month_starts:
        first_ts = month_start + pd.Timedelta(days=4, hours=14, minutes=30)
        second_ts = month_start + pd.Timedelta(days=19, hours=14, minutes=30)
        if first_ts <= start_ts or first_ts >= end_ts:
            continue
        ts_values.append(first_ts)
        first_close = last_close * (1.0 + 0.001)
        close_values.append(first_close)
        if second_ts < end_ts:
            ts_values.append(second_ts)
            intra_month_jump = 0.03 if (month_index % 2) == 0 else 0.01
            second_close = first_close * (1.0 + intra_month_jump)
            close_values.append(second_close)
            last_close = second_close
        else:
            last_close = first_close
        month_index += 1
    if ts_values[-1] != end_ts:
        ts_values.append(end_ts)
        close_values.append(last_close * (1.0 + 0.001))

    bars = pd.DataFrame({"ts": ts_values, "close": close_values}).sort_values("ts").reset_index(drop=True)
    bars["open"] = bars["close"] * 0.999
    bars["high"] = bars["close"] * 1.001
    bars["low"] = bars["close"] * 0.998
    bars["volume"] = 1000.0
    bars = bars.loc[:, ["ts", "open", "high", "low", "close", "volume"]]
    storage.write_bars(bars, symbol="SPY", timeframe="1m")
    storage.write_bars(bars, symbol="QQQ", timeframe="1m")
    storage.write_bars(bars, symbol="VIXY", timeframe="1m")


def _append_outcomes(
    *,
    storage: StorageManager,
    start: pd.Timestamp,
    months: int,
    trades_per_month: int,
    weak: bool,
) -> None:
    strikes: list[dict[str, object]] = []
    signals: list[dict[str, object]] = []
    positions: list[dict[str, object]] = []
    counter = 0
    for month_index in range(months):
        month_start = start + pd.DateOffset(months=month_index)
        for trade_index in range(trades_per_month):
            counter += 1
            strike_id = f"strike-{counter}"
            signal_id = f"signal-{counter}"
            symbol = "VIXY" if (trade_index % 2) == 1 else "SPY"
            signal_type = "precision_buy"
            if weak:
                realized_r = 0.05 if (counter % 2 == 0) else -0.05
            elif symbol == "VIXY":
                realized_r = 1.2 if (month_index % 2 == 0) else 0.6
            else:
                realized_r = 1.0
            close_ts = month_start + pd.Timedelta(days=trade_index, hours=15, minutes=30)
            entry = 100.0
            stop = 99.0
            strikes.append(
                {
                    "id": strike_id,
                    "symbol": symbol,
                    "timeframe": "1m",
                    "outfit_id": "outfit-a",
                    "period": 20,
                    "sma_value": 100.0,
                    "bar_ts": (close_ts - pd.Timedelta(minutes=1)).isoformat(),
                    "tolerance": 0.001,
                    "trigger_mode": "bar_touch",
                }
            )
            signals.append(
                {
                    "id": signal_id,
                    "strike_id": strike_id,
                    "route_id": f"route-{symbol.lower()}",
                    "side": "LONG",
                    "signal_type": signal_type,
                    "entry": entry,
                    "stop": stop,
                    "confidence": "A",
                    "session_type": "regular",
                }
            )
            positions.append(
                {
                    "id": f"position-{counter}",
                    "signal_id": signal_id,
                    "action": "close",
                    "qty": 1.0,
                    "price": entry + realized_r,
                    "reason": "target",
                    "ts": close_ts.isoformat(),
                }
            )
    storage.append_events("strikes", strikes)
    storage.append_events("signals", signals)
    storage.append_events("positions", positions)


def test_verify_readiness_fails_academic_gate_with_insufficient_edge(
    settings,
    monkeypatch,
) -> None:
    weak_settings = settings.model_copy(deep=True)
    weak_settings.validation.bootstrap.samples = 120
    weak_settings.validation.random_strategy_mc_samples = 120
    weak_settings.validation.regime.proxy_timeframe = "1m"
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: weak_settings)

    storage = StorageManager(
        Path(weak_settings.storage_root),
        events_root=Path(weak_settings.events_root),
    )
    _write_readiness_bars(
        storage=storage,
        start="2020-01-02T14:30:00Z",
        end="2024-12-31T21:00:00Z",
    )
    _append_outcomes(
        storage=storage,
        start=pd.Timestamp("2020-01-01T00:00:00Z"),
        months=36,
        trades_per_month=3,
        weak=True,
    )

    with pytest.raises(RuntimeError, match="academic validation gate failed"):
        cli.verify_readiness(
            config=Path("configs/settings.example.yaml"),
            start="2020-01-02T14:30:00Z",
            end="2024-12-31T21:00:00Z",
            symbols="",
            timeframes="1m",
            output=Path("ignored.json"),
            require_report_artifacts=False,
            require_gap_quality=False,
            require_run_manifest=False,
            require_academic_validation=True,
        )


def test_verify_readiness_passes_academic_gate_with_strict_fixture_data(
    settings,
    monkeypatch,
    tmp_path: Path,
) -> None:
    strong_settings = settings.model_copy(deep=True)
    strong_settings.validation.bootstrap.samples = 160
    strong_settings.validation.random_strategy_mc_samples = 160
    strong_settings.validation.regime.proxy_timeframe = "1m"
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: strong_settings)

    storage = StorageManager(
        Path(strong_settings.storage_root),
        events_root=Path(strong_settings.events_root),
    )
    _write_readiness_bars(
        storage=storage,
        start="2018-01-02T14:30:00Z",
        end="2025-12-31T21:00:00Z",
    )
    _append_outcomes(
        storage=storage,
        start=pd.Timestamp("2018-01-01T00:00:00Z"),
        months=78,
        trades_per_month=10,
        weak=False,
    )

    output_path = tmp_path / "readiness_acceptance.json"
    cli.verify_readiness(
        config=Path("configs/settings.example.yaml"),
        start="2018-01-02T14:30:00Z",
        end="2025-12-31T21:00:00Z",
        symbols="",
        timeframes="1m",
        output=output_path,
        require_report_artifacts=False,
        require_gap_quality=False,
        require_run_manifest=False,
        require_academic_validation=True,
    )

    assert output_path.exists()
    manifest = json.loads(output_path.read_text(encoding="utf-8"))
    assert manifest["academic_validation"]["ready"] is True
