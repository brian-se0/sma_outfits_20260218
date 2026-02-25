from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from sma_outfits import cli
from sma_outfits.config.models import (
    AlpacaConfig,
    SessionsConfig,
    TimeframesConfig,
    UniverseConfig,
)
from sma_outfits.data.storage import StorageManager


class _FakeDiscoveryClient:
    def __init__(self, _config: AlpacaConfig) -> None:
        pass

    def discover_earliest_bar_frame(
        self,
        symbol: str,
        timeframe: str,
        market: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        assert market == "stocks"
        assert symbol == "SPY"
        assert start < end
        ts = (
            pd.Timestamp("2024-09-04T13:31:00Z")
            if timeframe == "1m"
            else pd.Timestamp("2024-09-04T00:00:00Z")
        )
        return pd.DataFrame(
            [
                {
                    "ts": ts,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000.0,
                }
            ]
        )


def test_discover_range_writes_manifest_and_hash(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(
        cli,
        "_load_discovery_runtime",
        lambda _config: (
            AlpacaConfig(
                api_key="test-key",
                secret_key="test-secret",
                base_url="https://paper-api.alpaca.markets",
                data_url="https://data.alpaca.markets",
                data_feed="iex",
            ),
            UniverseConfig(
                symbols=["SPY", "BTC/USD"],
                symbol_markets={"SPY": "stocks", "BTC/USD": "crypto"},
            ),
            TimeframesConfig(live=["1m"], derived=["1D"]),
            SessionsConfig(timezone="America/New_York"),
        ),
    )
    monkeypatch.setattr(cli, "AlpacaRESTClient", _FakeDiscoveryClient)

    output_path = tmp_path / "discovered_range_manifest.json"
    cli.discover_range(
        config=None,
        symbols="",
        timeframes="",
        output=output_path,
        start="2024-01-01T00:00:00Z",
        end="2025-01-01T00:00:00Z",
    )

    stdout = capsys.readouterr().out
    assert "manifest_path=" in stdout
    assert output_path.exists()
    hash_path = output_path.with_suffix(output_path.suffix + ".sha256")
    assert hash_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["stocks"] == ["SPY"]
    assert payload["full_range_start"] == "2024-09-04T13:31:00+00:00"
    assert len(payload["records"]) == 2
    assert all(row["symbol"] == "SPY" for row in payload["records"])


def test_discover_range_fails_when_no_stock_symbols(monkeypatch) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(
        cli,
        "_load_discovery_runtime",
        lambda _config: (
            AlpacaConfig(
                api_key="test-key",
                secret_key="test-secret",
                base_url="https://paper-api.alpaca.markets",
                data_url="https://data.alpaca.markets",
                data_feed="iex",
            ),
            UniverseConfig(
                symbols=["BTC/USD"],
                symbol_markets={"BTC/USD": "crypto"},
            ),
            TimeframesConfig(live=["1m"], derived=["1D"]),
            SessionsConfig(timezone="America/New_York"),
        ),
    )

    with pytest.raises(RuntimeError, match="No stock symbols available"):
        cli.discover_range(
            config=None,
            symbols="",
            timeframes="",
            output=Path("ignored.json"),
            start="2024-01-01T00:00:00Z",
            end="2025-01-01T00:00:00Z",
        )


def test_verify_readiness_writes_acceptance_manifest(
    settings,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    storage = StorageManager(Path(settings.storage_root))
    bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-02T14:31:00Z"),
            ],
            "open": [100.0, 100.1],
            "high": [100.2, 100.3],
            "low": [99.9, 100.0],
            "close": [100.1, 100.2],
            "volume": [1000.0, 1100.0],
        }
    )
    storage.write_bars(bars, symbol="SPY", timeframe="1m")
    storage.write_bars(bars, symbol="QQQ", timeframe="1m")

    output_path = tmp_path / "readiness_acceptance.json"
    cli.verify_readiness(
        config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        start="2025-01-02T14:30:00Z",
        end="2025-01-02T21:00:00Z",
        symbols="",
        timeframes="1m",
        output=output_path,
        require_report_artifacts=False,
        require_run_manifest=False,
        require_academic_validation=False,
    )

    assert output_path.exists()
    hash_path = output_path.with_suffix(output_path.suffix + ".sha256")
    assert hash_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["pairs_checked"] == 2
    assert payload["timeframes"] == ["1m"]
    assert "academic_validation" in payload
    assert set(payload["academic_validation"].keys()) >= {
        "ready",
        "blocking_reasons",
        "fold_count",
        "min_fold_trade_count",
        "bootstrap_p_value",
        "fdr_summary",
    }


def test_verify_readiness_fails_when_backfill_coverage_missing(
    settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    storage = StorageManager(Path(settings.storage_root))
    bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-02T14:31:00Z"),
            ],
            "open": [100.0, 100.1],
            "high": [100.2, 100.3],
            "low": [99.9, 100.0],
            "close": [100.1, 100.2],
            "volume": [1000.0, 1100.0],
        }
    )
    storage.write_bars(bars, symbol="SPY", timeframe="1m")

    with pytest.raises(RuntimeError, match="missing backfill coverage"):
        cli.verify_readiness(
            config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
            start="2025-01-02T14:30:00Z",
            end="2025-01-02T21:00:00Z",
            symbols="",
            timeframes="1m",
            output=Path("ignored.json"),
            require_report_artifacts=False,
            require_run_manifest=False,
            require_academic_validation=False,
        )


def test_verify_readiness_fails_when_boundary_coverage_violation_detected(
    settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    storage = StorageManager(Path(settings.storage_root))
    late_bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-02-10T14:30:00Z"),
                pd.Timestamp("2025-02-10T14:31:00Z"),
            ],
            "open": [100.0, 100.1],
            "high": [100.2, 100.3],
            "low": [99.9, 100.0],
            "close": [100.1, 100.2],
            "volume": [1000.0, 1100.0],
        }
    )
    storage.write_bars(late_bars, symbol="SPY", timeframe="1m")
    storage.write_bars(late_bars, symbol="QQQ", timeframe="1m")

    with pytest.raises(RuntimeError, match="boundary coverage violations"):
        cli.verify_readiness(
            config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
            start="2025-01-02T14:30:00Z",
            end="2025-02-10T21:00:00Z",
            symbols="",
            timeframes="1m",
            output=Path("ignored.json"),
            require_report_artifacts=False,
            require_run_manifest=False,
            require_academic_validation=False,
        )


def test_verify_readiness_fails_when_gap_quality_violation_detected(
    settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    storage = StorageManager(Path(settings.storage_root))
    gappy_bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-08T14:30:00Z"),
            ],
            "open": [100.0, 100.1],
            "high": [100.2, 100.3],
            "low": [99.9, 100.0],
            "close": [100.1, 100.2],
            "volume": [1000.0, 1100.0],
        }
    )
    storage.write_bars(gappy_bars, symbol="SPY", timeframe="1m")
    storage.write_bars(gappy_bars, symbol="QQQ", timeframe="1m")

    with pytest.raises(RuntimeError, match="unexpected gap quality violations"):
        cli.verify_readiness(
            config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
            start="2025-01-02T14:30:00Z",
            end="2025-01-08T21:00:00Z",
            symbols="",
            timeframes="1m",
            output=Path("ignored.json"),
            require_report_artifacts=False,
            require_run_manifest=False,
            require_academic_validation=False,
        )


def test_verify_readiness_fails_when_run_manifest_required_and_missing(
    settings,
    monkeypatch,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    storage = StorageManager(Path(settings.storage_root))
    bars = pd.DataFrame(
        {
            "ts": [
                pd.Timestamp("2025-01-02T14:30:00Z"),
                pd.Timestamp("2025-01-02T14:31:00Z"),
            ],
            "open": [100.0, 100.1],
            "high": [100.2, 100.3],
            "low": [99.9, 100.0],
            "close": [100.1, 100.2],
            "volume": [1000.0, 1100.0],
        }
    )
    storage.write_bars(bars, symbol="SPY", timeframe="1m")
    storage.write_bars(bars, symbol="QQQ", timeframe="1m")

    with pytest.raises(RuntimeError, match="no run manifest found"):
        cli.verify_readiness(
            config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
            start="2025-01-02T14:30:00Z",
            end="2025-01-02T21:00:00Z",
            symbols="",
            timeframes="1m",
            output=Path("ignored.json"),
            require_report_artifacts=False,
            require_run_manifest=True,
            require_academic_validation=False,
        )


def test_write_run_manifest_writes_expected_payload(
    settings,
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    output_path = tmp_path / "run_manifest.json"
    cli.write_run_manifest(
        config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        profile="custom",
        stages="validate-config,backfill,replay,report",
        analysis_start="2025-01-01T00:00:00Z",
        analysis_end="2025-12-31T23:59:59Z",
        warmup_days=120,
        warmup_start="2024-09-03T00:00:00Z",
        backfill_start="2024-09-03T00:00:00Z",
        backfill_end="2025-12-31T23:59:59Z",
        replay_start="2024-09-03T00:00:00Z",
        replay_end="2025-12-31T23:59:59Z",
        report_range="2025-01-01T00:00:00Z,2025-12-31T23:59:59Z",
        symbols="SPY,QQQ",
        timeframes="1m,1D",
        command="make e2e",
        run_id="unit_test_run",
        output=output_path,
    )
    stdout = capsys.readouterr().out
    assert "run_manifest_path=" in stdout
    assert output_path.exists()
    assert output_path.with_suffix(".json.sha256").exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["profile"] == "custom"
    assert payload["stages_requested"] == [
        "validate-config",
        "backfill",
        "replay",
        "report",
    ]
    assert payload["resolved_windows"]["warmup_days"] == 120

