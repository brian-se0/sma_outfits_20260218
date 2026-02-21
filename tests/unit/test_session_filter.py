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
    sessions = {
        "2025-01-02": (
            pd.Timestamp("2025-01-02 09:30:00", tz=timezone).tz_convert("UTC"),
            pd.Timestamp("2025-01-02 16:00:00", tz=timezone).tz_convert("UTC"),
        )
    }
    filtered = apply_regular_session_filter(
        frame,
        session_windows=sessions,
        timezone=timezone,
    )
    kept_local = filtered["ts"].dt.tz_convert(timezone).dt.strftime("%H:%M").to_list()
    assert kept_local == ["09:30", "16:00"]


def test_regular_session_filter_respects_early_close_from_calendar() -> None:
    timezone = "America/New_York"
    local_times = [
        pd.Timestamp("2025-11-28 12:59:00", tz=timezone),
        pd.Timestamp("2025-11-28 13:00:00", tz=timezone),
        pd.Timestamp("2025-11-28 13:01:00", tz=timezone),
    ]
    frame = pd.DataFrame(
        {
            "ts": [ts.tz_convert("UTC") for ts in local_times],
            "open": [1.0, 1.0, 1.0],
            "high": [1.1, 1.1, 1.1],
            "low": [0.9, 0.9, 0.9],
            "close": [1.0, 1.0, 1.0],
            "volume": [10, 10, 10],
        }
    )
    sessions = {
        "2025-11-28": (
            pd.Timestamp("2025-11-28 09:30:00", tz=timezone).tz_convert("UTC"),
            pd.Timestamp("2025-11-28 13:00:00", tz=timezone).tz_convert("UTC"),
        )
    }
    filtered = apply_regular_session_filter(
        frame,
        session_windows=sessions,
        timezone=timezone,
    )
    kept_local = filtered["ts"].dt.tz_convert(timezone).dt.strftime("%H:%M").to_list()
    assert kept_local == ["12:59", "13:00"]


def test_regular_session_filter_fails_when_calendar_date_is_missing() -> None:
    timezone = "America/New_York"
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-02T14:30:00Z")],
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.0],
            "volume": [10],
        }
    )
    sessions: dict[str, tuple[pd.Timestamp, pd.Timestamp] | None] = {}
    try:
        apply_regular_session_filter(
            frame,
            session_windows=sessions,
            timezone=timezone,
        )
    except RuntimeError as exc:
        assert "Missing dates" in str(exc)
    else:
        raise AssertionError("Expected regular-session filter to fail for missing calendar date")


def test_regular_session_filter_fails_for_closed_session_date_with_bars() -> None:
    timezone = "America/New_York"
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2025-01-04T15:00:00Z")],
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.0],
            "volume": [10],
        }
    )
    sessions = {"2025-01-04": None}
    try:
        apply_regular_session_filter(
            frame,
            session_windows=sessions,
            timezone=timezone,
        )
    except RuntimeError as exc:
        assert "closed sessions" in str(exc)
    else:
        raise AssertionError("Expected regular-session filter to fail for closed-session bars")
