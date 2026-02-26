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
    write_summary_report,
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
            route_id="route-1",
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
            route_id="route-2",
            side="SHORT",
            signal_type="magnetized_buy",
            entry=200.0,
            stop=201.0,
            confidence="HIGH",
            session_type="regular",
        ),
    ]
    positions = [
        PositionEvent(
            id="p0",
            signal_id="signal-1",
            action="open",
            qty=1.0,
            price=100.0,
            reason="position_opened",
            ts=datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc),
        ),
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
            id="p2-open",
            signal_id="signal-2",
            action="open",
            qty=1.0,
            price=200.0,
            reason="position_opened",
            ts=datetime(2025, 1, 2, 15, 30, tzinfo=timezone.utc),
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
    assert summary["position_action_breakdown"] == {
        "open": 2,
        "partial_take": 1,
        "close": 2,
    }
    assert summary["r_outcome"]["total_realized_r"] == 1.5
    assert summary["r_outcome"]["bucket_counts"]["1R_to_3R"] == 1
    assert summary["r_outcome"]["bucket_counts"]["<=-1R"] == 1
    assert summary["hit_rate_by_side"]
    assert summary["period_summary_daily"]
    assert summary["statistical_validation"]["sample_size"]["closed_positions"] == 2
    assert summary["statistical_validation"]["production_readiness"]["ready_for_production"] is False
    signal_labels = {row["label"] for row in summary["hit_rate_by_signal_type"]}
    assert "magnetized_buy" in signal_labels


def test_build_summary_normalizes_r_by_total_realized_qty() -> None:
    strike = StrikeEvent(
        id="strike-qty",
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
        id="signal-qty",
        strike_id="strike-qty",
        route_id="route-qty",
        side="LONG",
        signal_type="precision_buy",
        entry=100.0,
        stop=99.0,
        confidence="HIGH",
        session_type="regular",
    )
    close_event = PositionEvent(
        id="p-qty-close",
        signal_id="signal-qty",
        action="close",
        qty=100.0,
        price=101.0,
        reason="+1R_final_take",
        ts=datetime(2025, 1, 2, 14, 31, tzinfo=timezone.utc),
    )
    open_event = PositionEvent(
        id="p-qty-open",
        signal_id="signal-qty",
        action="open",
        qty=100.0,
        price=100.0,
        reason="position_opened",
        ts=datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc),
    )

    summary = build_summary(
        strikes=[strike],
        signals=[signal],
        position_events=[open_event, close_event],
    )

    assert summary["r_outcome"]["total_realized_r"] == 1.0
    assert summary["r_outcome"]["avg_realized_r"] == 1.0
    assert summary["hit_rate"] == 1.0
    assert summary["position_action_breakdown"] == {
        "open": 1,
        "partial_take": 0,
        "close": 1,
    }


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
        route_id="route-1",
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

    assert summary["attribution_mode"] == "both"
    assert summary["strike_attribution"]["closed_positions"] == 1
    assert summary["strike_attribution"]["hit_rate"] == 1.0
    assert summary["close_attribution"]["closed_positions"] == 0
    assert summary["close_attribution"]["hit_rate"] == 0.0


def test_build_summary_fails_when_signal_references_missing_strike() -> None:
    signal = SignalEvent(
        id="signal-missing",
        strike_id="strike-missing",
        route_id="route-missing",
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


def test_build_summary_from_records_uses_explicit_strike_and_close_payloads() -> None:
    strike = StrikeEvent(
        id="strike-old",
        symbol="SPY",
        timeframe="1m",
        outfit_id="outfit-a",
        period=10,
        sma_value=100.0,
        bar_ts=datetime(2025, 1, 1, 14, 30, tzinfo=timezone.utc),
        tolerance=0.01,
        trigger_mode="bar_touch",
    )
    signal = SignalEvent(
        id="signal-close-in-range",
        strike_id="strike-old",
        route_id="route-1",
        side="LONG",
        signal_type="precision_buy",
        entry=100.0,
        stop=99.0,
        confidence="HIGH",
        session_type="regular",
    )
    close_event = PositionEvent(
        id="close-in-range",
        signal_id=signal.id,
        action="close",
        qty=1.0,
        price=101.0,
        reason="+1R_partial_and_breakeven_stop",
        ts=datetime(2025, 1, 2, 14, 35, tzinfo=timezone.utc),
    )

    summary = build_summary_from_records(
        strike_rows=[event_to_record(strike)],
        signal_rows=[event_to_record(signal)],
        position_rows=[event_to_record(close_event)],
        start=pd.Timestamp("2025-01-02T00:00:00Z"),
        end=pd.Timestamp("2025-01-02T23:59:59Z"),
    )

    assert summary["attribution_mode"] == "both"
    assert "closed_positions" not in summary
    assert summary["strike_attribution"]["closed_positions"] == 0
    assert summary["close_attribution"]["closed_positions"] == 1
    assert summary["close_attribution"]["total_signals"] == 1

def test_write_summary_report_both_mode_adds_close_columns_and_sections(tmp_path) -> None:
    strike = StrikeEvent(
        id="strike-old",
        symbol="SPY",
        timeframe="1m",
        outfit_id="outfit-a",
        period=10,
        sma_value=100.0,
        bar_ts=datetime(2025, 1, 1, 14, 30, tzinfo=timezone.utc),
        tolerance=0.01,
        trigger_mode="bar_touch",
    )
    signal = SignalEvent(
        id="signal-close-in-range",
        strike_id="strike-old",
        route_id="route-1",
        side="LONG",
        signal_type="precision_buy",
        entry=100.0,
        stop=99.0,
        confidence="HIGH",
        session_type="regular",
    )
    close_event = PositionEvent(
        id="close-in-range",
        signal_id=signal.id,
        action="close",
        qty=1.0,
        price=101.0,
        reason="+1R_partial_and_breakeven_stop",
        ts=datetime(2025, 1, 2, 14, 35, tzinfo=timezone.utc),
    )
    summary = build_summary_from_records(
        strike_rows=[event_to_record(strike)],
        signal_rows=[event_to_record(signal)],
        position_rows=[event_to_record(close_event)],
        start=pd.Timestamp("2025-01-02T00:00:00Z"),
        end=pd.Timestamp("2025-01-02T23:59:59Z"),
    )

    markdown_path, csv_path = write_summary_report(summary, tmp_path, "range_test")

    csv = pd.read_csv(csv_path)
    assert "attribution_mode" in csv.columns
    assert "strike_total_signals" in csv.columns
    assert "close_total_signals" in csv.columns
    assert str(csv.iloc[0]["attribution_mode"]) == "both"

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Strike-Time Attribution" in markdown
    assert "Close-Time Attribution" in markdown
    assert "position_action_breakdown" in markdown
    assert "Academic Validation Appendix" in markdown
    assert "Claim Scope (Statistical)" in markdown
    assert "null_hypothesis: `mean(net_realized_r) <= 0`" in markdown
    assert "supports_causal_inference: `False`" in markdown
    assert "Walk-Forward Optimization (WFO)" in markdown
    assert "available_months" in markdown
    assert "required_months_for_min_folds" in markdown
    assert "max_feasible_folds" in markdown
    assert "is_feasible" in markdown
    assert "Bootstrap Distribution" in markdown
    assert "P-Value and Multiple-Testing Summary" in markdown
    assert "Execution Realism Sensitivity" in markdown
    assert "Regime Stability" in markdown
    assert "mapped_trade_month_count" in markdown
    assert "missing_proxy_month_count" in markdown
    assert "Citation Pack" in markdown
    assert "white_2000_reality_check" in markdown

    assert (tmp_path / "range_test_academic_validation.json").exists()
    assert (tmp_path / "range_test_wfo_table.csv").exists()
    assert (tmp_path / "range_test_pvalues.csv").exists()
    assert (tmp_path / "range_test_bootstrap_bins.csv").exists()
    assert (tmp_path / "figures" / "range_test_bootstrap_hist.png").exists()
