from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from sma_outfits import cli
from sma_outfits.data.storage import StorageManager


def test_report_writes_zero_summary_when_no_stored_events(settings, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    cli.report(
        config=Path("configs/settings.example.yaml"),
        date=None,
        range_=None,
    )

    output = capsys.readouterr().out
    assert '"attribution_mode": "both"' in output
    assert '"total_strikes": 0' in output
    assert '"total_signals": 0' in output
    assert "report_markdown=" in output
    assert (Path(settings.archive.root) / "reports" / "all_time.md").exists()
    assert (Path(settings.archive.root) / "reports" / "all_time.csv").exists()


def test_resolve_report_range_accepts_comma_for_full_timestamps() -> None:
    start, end = cli._resolve_report_range(
        date=None,
        range_="2025-01-02T14:30:00Z,2025-01-31T21:00:00Z",
    )
    assert start == pd.Timestamp("2025-01-02T14:30:00Z")
    assert end == pd.Timestamp("2025-01-31T21:00:00Z")


def test_resolve_report_range_accepts_colon_for_date_only() -> None:
    start, end = cli._resolve_report_range(
        date=None,
        range_="2025-01-02:2025-01-31",
    )
    assert start == pd.Timestamp("2025-01-02T00:00:00Z")
    assert end == pd.Timestamp("2025-01-31T00:00:00Z")


def test_resolve_report_range_rejects_ambiguous_timestamp_colon_format() -> None:
    with pytest.raises(ValueError, match="start:end \\(date-only\\) or start,end"):
        cli._resolve_report_range(
            date=None,
            range_="2025-01-02T14:30:00Z:2025-01-31T21:00:00Z",
        )


def test_report_range_preserves_close_attribution_for_signals_closed_in_window(
    settings,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    storage = StorageManager(
        Path(settings.storage_root),
        events_root=Path(settings.events_root),
    )
    storage.append_events(
        "strikes",
        [
            {
                "id": "strike-old",
                "symbol": "SPY",
                "timeframe": "1m",
                "outfit_id": "old",
                "period": 20,
                "sma_value": 100.0,
                "bar_ts": "2025-01-01T14:30:00+00:00",
                "tolerance": 0.001,
                "trigger_mode": "cross",
            },
            {
                "id": "strike-in-window",
                "symbol": "QQQ",
                "timeframe": "1m",
                "outfit_id": "in-window",
                "period": 20,
                "sma_value": 200.0,
                "bar_ts": "2025-01-03T15:30:00+00:00",
                "tolerance": 0.001,
                "trigger_mode": "cross",
            },
        ],
    )
    storage.append_events(
        "signals",
        [
            {
                "id": "signal-old",
                "strike_id": "strike-old",
                "route_id": "route-old",
                "side": "LONG",
                "signal_type": "long_break",
                "entry": 100.0,
                "stop": 99.0,
                "confidence": "A",
                "session_type": "regular",
            },
            {
                "id": "signal-in-window",
                "strike_id": "strike-in-window",
                "route_id": "route-in-window",
                "side": "LONG",
                "signal_type": "long_break",
                "entry": 200.0,
                "stop": 199.0,
                "confidence": "A",
                "session_type": "regular",
            },
        ],
    )
    storage.append_events(
        "positions",
        [
            {
                "id": "position-old-close",
                "signal_id": "signal-old",
                "action": "close",
                "qty": 1.0,
                "price": 101.0,
                "reason": "target",
                "ts": "2025-01-03T16:00:00+00:00",
            },
            {
                "id": "position-in-window-open",
                "signal_id": "signal-in-window",
                "action": "open",
                "qty": 1.0,
                "price": 200.0,
                "reason": "entry",
                "ts": "2025-01-03T15:31:00+00:00",
            },
        ],
    )

    cli.report(
        config=Path("configs/settings.example.yaml"),
        date=None,
        range_="2025-01-03T00:00:00Z,2025-01-03T23:59:59Z",
    )

    output = capsys.readouterr().out
    summary = json.loads(output.split("report_markdown=", 1)[0].strip())
    assert summary["strike_attribution"]["total_signals"] == 1
    assert summary["close_attribution"]["total_signals"] == 1
