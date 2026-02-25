from __future__ import annotations

from pathlib import Path

from sma_outfits import cli
from sma_outfits.data.storage import StorageManager


def test_report_writes_academic_appendix_sidecars(settings, monkeypatch) -> None:
    report_settings = settings.model_copy(deep=True)
    report_settings.validation.bootstrap.samples = 120
    report_settings.validation.random_strategy_mc_samples = 120
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: report_settings)

    storage = StorageManager(
        Path(report_settings.storage_root),
        events_root=Path(report_settings.events_root),
    )
    storage.append_events(
        "strikes",
        [
            {
                "id": "strike-1",
                "symbol": "SPY",
                "timeframe": "1m",
                "outfit_id": "outfit-a",
                "period": 20,
                "sma_value": 100.0,
                "bar_ts": "2025-01-02T15:00:00+00:00",
                "tolerance": 0.001,
                "trigger_mode": "bar_touch",
            },
            {
                "id": "strike-2",
                "symbol": "VIXY",
                "timeframe": "1m",
                "outfit_id": "outfit-b",
                "period": 20,
                "sma_value": 50.0,
                "bar_ts": "2025-01-02T16:00:00+00:00",
                "tolerance": 0.001,
                "trigger_mode": "bar_touch",
            },
        ],
    )
    storage.append_events(
        "signals",
        [
            {
                "id": "signal-1",
                "strike_id": "strike-1",
                "route_id": "route-spy",
                "side": "LONG",
                "signal_type": "precision_buy",
                "entry": 100.0,
                "stop": 99.0,
                "confidence": "A",
                "session_type": "regular",
            },
            {
                "id": "signal-2",
                "strike_id": "strike-2",
                "route_id": "route-vixy",
                "side": "LONG",
                "signal_type": "precision_buy",
                "entry": 50.0,
                "stop": 49.0,
                "confidence": "A",
                "session_type": "regular",
            },
        ],
    )
    storage.append_events(
        "positions",
        [
            {
                "id": "position-1",
                "signal_id": "signal-1",
                "action": "close",
                "qty": 1.0,
                "price": 101.1,
                "reason": "target",
                "ts": "2025-01-02T15:30:00+00:00",
            },
            {
                "id": "position-2",
                "signal_id": "signal-2",
                "action": "close",
                "qty": 1.0,
                "price": 50.8,
                "reason": "target",
                "ts": "2025-01-02T16:30:00+00:00",
            },
        ],
    )

    cli.report(
        config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"),
        date=None,
        range_="2025-01-02T00:00:00Z,2025-01-02T23:59:59Z",
    )

    label = "20250102_20250102"
    report_root = Path(report_settings.archive.root) / "reports"
    markdown_path = report_root / f"{label}.md"
    assert markdown_path.exists()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Academic Validation Appendix" in markdown
    assert "Execution Realism Sensitivity" in markdown
    assert (report_root / f"{label}_academic_validation.json").exists()
    assert (report_root / f"{label}_wfo_table.csv").exists()
    assert (report_root / f"{label}_pvalues.csv").exists()
    assert (report_root / f"{label}_bootstrap_bins.csv").exists()
    assert (report_root / "figures" / f"{label}_bootstrap_hist.png").exists()

