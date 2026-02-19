from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from sma_outfits.events import PositionEvent, SignalEvent, StrikeEvent, event_to_record
from sma_outfits.reporting.summary import (
    _r_breakdown,
    _rate_breakdown,
    build_summary,
    build_summary_from_records,
)


def test_build_summary_includes_r_outcomes_and_breakdowns() -> None:
    strikes = [
        StrikeEvent(
            id="strike-1",
            symbol="SPY",
            timeframe="1m",
            outfit_id="outfit-a",
            period=10,
            sma_value=100.0,
            bar_ts=datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc),
            tolerance=0.01,
            trigger_mode="bar_touch",
        ),
        StrikeEvent(
            id="strike-2",
            symbol="QQQ",
            timeframe="1m",
            outfit_id="outfit-b",
            period=20,
            sma_value=200.0,
            bar_ts=datetime(2025, 1, 2, 15, 30, tzinfo=timezone.utc),
            tolerance=0.01,
            trigger_mode="bar_touch",
        ),
    ]
    signals = [
        SignalEvent(
            id="signal-1",
            strike_id="strike-1",
            side="LONG",
            signal_type="precision_buy",
            entry=100.0,
            stop=99.0,
            confidence="HIGH",
            session_type="regular",
        ),
        SignalEvent(
            id="signal-2",
            strike_id="strike-2",
            side="SHORT",
            signal_type="automated_short",
            entry=200.0,
            stop=201.0,
            confidence="HIGH",
            session_type="regular",
        ),
    ]
    positions = [
        PositionEvent(
            id="p1",
            signal_id="signal-1",
            action="partial_take",
            qty=0.25,
            price=101.0,
            reason="+1R_partial_and_breakeven_stop",
            ts=datetime(2025, 1, 2, 14, 31, tzinfo=timezone.utc),
        ),
        PositionEvent(
            id="p2",
            signal_id="signal-1",
            action="close",
            qty=0.75,
            price=103.0,
            reason="+3R_final_take",
            ts=datetime(2025, 1, 2, 14, 32, tzinfo=timezone.utc),
        ),
        PositionEvent(
            id="p3",
            signal_id="signal-2",
            action="close",
            qty=1.0,
            price=201.0,
            reason="singular_point_hard_stop",
            ts=datetime(2025, 1, 2, 15, 31, tzinfo=timezone.utc),
        ),
    ]

    summary = build_summary(strikes=strikes, signals=signals, position_events=positions)

    assert summary["closed_positions"] == 2
    assert summary["hit_rate"] == 0.5
    assert summary["r_outcome"]["total_realized_r"] == 1.5
    assert summary["r_outcome"]["bucket_counts"]["1R_to_3R"] == 1
    assert summary["r_outcome"]["bucket_counts"]["<=-1R"] == 1
    assert summary["hit_rate_by_side"]
    assert summary["period_summary_daily"]


def test_build_summary_from_records_applies_time_range() -> None:
    strike = StrikeEvent(
        id="strike-1",
        symbol="SPY",
        timeframe="1m",
        outfit_id="outfit-a",
        period=10,
        sma_value=100.0,
        bar_ts=datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc),
        tolerance=0.01,
        trigger_mode="bar_touch",
    )
    signal = SignalEvent(
        id="signal-1",
        strike_id="strike-1",
        side="LONG",
        signal_type="precision_buy",
        entry=100.0,
        stop=99.0,
        confidence="HIGH",
        session_type="regular",
    )
    in_range_close = PositionEvent(
        id="close-in",
        signal_id="signal-1",
        action="close",
        qty=1.0,
        price=103.0,
        reason="+3R_final_take",
        ts=datetime(2025, 1, 2, 14, 35, tzinfo=timezone.utc),
    )
    out_of_range_close = PositionEvent(
        id="close-out",
        signal_id="signal-1",
        action="close",
        qty=1.0,
        price=99.0,
        reason="singular_point_hard_stop",
        ts=datetime(2025, 1, 3, 14, 35, tzinfo=timezone.utc),
    )

    summary = build_summary_from_records(
        strike_rows=[event_to_record(strike)],
        signal_rows=[event_to_record(signal)],
        position_rows=[
            event_to_record(in_range_close),
            event_to_record(out_of_range_close),
        ],
        start=pd.Timestamp("2025-01-02T00:00:00Z"),
        end=pd.Timestamp("2025-01-02T23:59:59Z"),
    )

    assert summary["closed_positions"] == 1
    assert summary["hit_rate"] == 1.0


def test_build_summary_fails_when_signal_references_missing_strike() -> None:
    signal = SignalEvent(
        id="signal-missing",
        strike_id="strike-missing",
        side="LONG",
        signal_type="precision_buy",
        entry=100.0,
        stop=99.0,
        confidence="HIGH",
        session_type="regular",
    )

    with pytest.raises(RuntimeError, match="missing strike_id"):
        build_summary(strikes=[], signals=[signal], position_events=[])


def test_breakdown_fails_when_label_key_missing() -> None:
    with pytest.raises(RuntimeError, match="missing required key 'signal_type'"):
        _rate_breakdown(rows=[{"realized_r": 1.0}], key="signal_type")
    with pytest.raises(RuntimeError, match="missing required key 'signal_type'"):
        _r_breakdown(rows=[{"realized_r": 1.0}], key="signal_type")
