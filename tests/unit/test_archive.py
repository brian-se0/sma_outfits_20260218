from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from sma_outfits.archive.charts import write_signal_chart
from sma_outfits.archive.thread_writer import append_thread_markdown
from sma_outfits.events import SignalEvent, StrikeEvent


def test_archive_generation_creates_png_and_markdown(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_write_image(self, file, width, height, scale):  # noqa: ANN001
        Path(file).write_bytes(b"png")

    monkeypatch.setattr(go.Figure, "write_image", fake_write_image, raising=False)

    bars = pd.DataFrame(
        {
            "ts": pd.date_range("2025-01-02T14:30:00Z", periods=120, freq="1min"),
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.1,
            "volume": 1000.0,
        }
    )
    strike = StrikeEvent(
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
    signal = SignalEvent(
        id="signal-1",
        strike_id="strike-1",
        side="LONG",
        signal_type="precision_buy",
        entry=100.1,
        stop=100.09,
        confidence="HIGH",
        session_type="regular",
    )

    chart_path = tmp_path / "chart.png"
    output_chart = write_signal_chart(
        bars=bars,
        strike=strike,
        signal=signal,
        outfit_periods=[19, 37, 73, 143, 279, 548],
        output_path=chart_path,
    )
    assert output_chart.exists()

    markdown_path = append_thread_markdown(
        root=tmp_path / "threads",
        strike=strike,
        signal=signal,
        chart_path=output_chart,
    )
    body = markdown_path.read_text(encoding="utf-8")
    assert "signal_id" in body
    assert "warings_problem" in body
