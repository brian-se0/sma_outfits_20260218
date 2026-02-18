from __future__ import annotations

import pandas as pd

from sma_outfits.utils import apply_regular_session_filter


def test_regular_session_filter_only_keeps_regular_hours() -> None:
    timezone = "America/New_York"
    local_times = [
        pd.Timestamp("2025-01-02 09:29:00", tz=timezone),
        pd.Timestamp("2025-01-02 09:30:00", tz=timezone),
        pd.Timestamp("2025-01-02 16:00:00", tz=timezone),
        pd.Timestamp("2025-01-02 16:01:00", tz=timezone),
    ]
    frame = pd.DataFrame(
        {
            "ts": [ts.tz_convert("UTC") for ts in local_times],
            "open": [1.0, 1.0, 1.0, 1.0],
            "high": [1.1, 1.1, 1.1, 1.1],
            "low": [0.9, 0.9, 0.9, 0.9],
            "close": [1.0, 1.0, 1.0, 1.0],
            "volume": [10, 10, 10, 10],
        }
    )
    filtered = apply_regular_session_filter(frame, timezone=timezone)
    kept_local = filtered["ts"].dt.tz_convert(timezone).dt.strftime("%H:%M").to_list()
    assert kept_local == ["09:30", "16:00"]
