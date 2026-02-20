from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sma_outfits import cli


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
