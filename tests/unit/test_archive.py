from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sma_outfits.archive.thread_writer import append_thread_markdown
from sma_outfits.events import ArchiveRecord, SignalEvent, StrikeEvent, event_to_record


def _strike() -> StrikeEvent:
    return StrikeEvent(
        id="strike-1",
        symbol="SPY",
        timeframe="1m",
        outfit_id="warings_problem",
        period=37,
        sma_value=100.1,
        bar_ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
        tolerance=0.01,
        trigger_mode="bar_touch",
    )


def _signal() -> SignalEvent:
    return SignalEvent(
        id="signal-1",
        strike_id="strike-1",
        side="LONG",
        signal_type="precision_buy",
        entry=100.1,
        stop=100.09,
        confidence="HIGH",
        session_type="regular",
    )


def test_archive_thread_generation_creates_markdown(tmp_path: Path) -> None:
    markdown_path = append_thread_markdown(
        root=tmp_path / "threads",
        strike=_strike(),
        signal=_signal(),
    )
    body = markdown_path.read_text(encoding="utf-8")
    assert markdown_path.exists()
    assert "signal_id" in body
    assert "warings_problem" in body
    assert "strike_ts_utc" in body


def test_archive_record_serialization_is_machine_friendly() -> None:
    record = ArchiveRecord(
        signal_id="signal-1",
        markdown_path="artifacts/threads/2025-01-02.md",
        artifact_type="thread_markdown",
        caption="SPY 1m precision_buy at 100.10",
        ts=datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc),
    )
    payload = event_to_record(record)
    assert payload["signal_id"] == "signal-1"
    assert payload["artifact_type"] == "thread_markdown"
    assert payload["markdown_path"].endswith(".md")
