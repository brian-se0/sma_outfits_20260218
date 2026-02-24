from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from sma_outfits.config.models import CitationsConfig, ValidationConfig
from sma_outfits.reporting.academic_validation import build_academic_validation_payload
from sma_outfits.utils import ensure_utc_timestamp


def _synthetic_closed_outcomes(
    *,
    months: int,
    trades_per_month: int,
    weak_alt_signal: bool = False,
) -> list[dict[str, object]]:
    base = pd.Timestamp(datetime(2018, 1, 1, 15, 30, tzinfo=timezone.utc))
    rows: list[dict[str, object]] = []
    signal_counter = 0
    for month_index in range(months):
        month_start = base + pd.DateOffset(months=month_index)
        for trade_index in range(trades_per_month):
            signal_counter += 1
            is_proxy = (trade_index % 2) == 1
            symbol = "VIXY" if is_proxy else "SPY"
            signal_type = "alt_signal" if (weak_alt_signal and trade_index % 5 == 0) else "primary_signal"
            if signal_type == "alt_signal":
                realized_r = 0.02 if (trade_index % 2 == 0) else -0.02
            elif is_proxy:
                realized_r = 1.2 if (month_index % 2 == 0) else 0.6
            else:
                realized_r = 1.0
            close_ts = month_start + pd.Timedelta(days=int(trade_index % 20))
            rows.append(
                {
                    "signal_id": f"signal-{signal_counter}",
                    "route_id": f"route-{symbol.lower()}",
                    "signal_type": signal_type,
                    "side": "LONG",
                    "symbol": symbol,
                    "outfit_id": "outfit-a",
                    "timeframe": "1h",
                    "realized_r": realized_r,
                    "entry": 100.0,
                    "stop": 99.0,
                    "risk_unit": 1.0,
                    "avg_exit_price": 101.0,
                    "closed": True,
                    "close_reason": "close",
                    "close_ts": close_ts.isoformat(),
                }
            )
    return rows


def _overlay_from_outcomes(outcomes: list[dict[str, object]]) -> dict[str, object]:
    signal_r = {str(row["signal_id"]): float(row["realized_r"]) for row in outcomes}
    avg = sum(signal_r.values()) / len(signal_r) if signal_r else 0.0
    return {
        "gate_scenario_id": "net_s3",
        "gate_scenario_metrics": {"avg_realized_r": avg},
        "gate_scenario_signal_r": signal_r,
    }


def _proxy_monthly_vol_map(outcomes: list[dict[str, object]]) -> dict[str, float]:
    month_keys = sorted(
        {
            ensure_utc_timestamp(str(row["close_ts"])).strftime("%Y-%m")
            for row in outcomes
            if row.get("close_ts") is not None
        }
    )
    return {
        month: (0.02 if (index % 2) == 0 else 0.01)
        for index, month in enumerate(month_keys)
    }


def test_academic_validation_fold_construction_is_deterministic() -> None:
    outcomes = _synthetic_closed_outcomes(months=78, trades_per_month=10)
    overlay = _overlay_from_outcomes(outcomes)
    proxy_monthly_vol = _proxy_monthly_vol_map(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 250, "alpha": 0.05},
        random_strategy_mc_samples=250,
        seed=11,
    )

    payload_a = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )
    payload_b = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )

    assert payload_a["wfo_folds"] == payload_b["wfo_folds"]
    assert payload_a["fold_count"] >= validation.wfo.min_folds
    assert payload_a["ready"] is True


def test_academic_validation_hard_fails_when_any_fold_trade_count_below_minimum() -> None:
    outcomes = _synthetic_closed_outcomes(months=60, trades_per_month=4)
    overlay = _overlay_from_outcomes(outcomes)
    proxy_monthly_vol = _proxy_monthly_vol_map(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 200, "alpha": 0.05},
        random_strategy_mc_samples=200,
        seed=7,
    )

    payload = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )

    assert payload["ready"] is False
    assert any(
        str(reason).startswith("wfo_min_closed_trades_per_fold_violation")
        for reason in payload["blocking_reasons"]
    )


def test_academic_validation_bootstrap_reproducibility_with_fixed_seed() -> None:
    outcomes = _synthetic_closed_outcomes(months=72, trades_per_month=9)
    overlay = _overlay_from_outcomes(outcomes)
    proxy_monthly_vol = _proxy_monthly_vol_map(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 300, "alpha": 0.05},
        random_strategy_mc_samples=300,
        seed=123,
    )

    payload_a = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )
    payload_b = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )

    assert payload_a["bootstrap"]["mean"] == pytest.approx(payload_b["bootstrap"]["mean"])
    assert payload_a["bootstrap"]["ci"] == payload_b["bootstrap"]["ci"]
    assert payload_a["bootstrap"]["one_sided_p_value_mean_gt_zero"] == pytest.approx(
        payload_b["bootstrap"]["one_sided_p_value_mean_gt_zero"]
    )


def test_academic_validation_fdr_adjustment_orders_q_values_correctly() -> None:
    outcomes = _synthetic_closed_outcomes(months=78, trades_per_month=10, weak_alt_signal=True)
    overlay = _overlay_from_outcomes(outcomes)
    proxy_monthly_vol = _proxy_monthly_vol_map(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 250, "alpha": 0.05},
        random_strategy_mc_samples=250,
        seed=19,
    )

    payload = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )

    rows = payload["pvalues"]["rows"]
    assert len(rows) >= 2
    by_label = {row["label"]: row for row in rows}
    assert "primary_signal" in by_label
    assert "alt_signal" in by_label
    assert by_label["primary_signal"]["raw_p_value"] <= by_label["alt_signal"]["raw_p_value"]
    assert by_label["primary_signal"]["fdr_q_value"] <= by_label["alt_signal"]["fdr_q_value"]


def test_academic_validation_reports_wfo_window_infeasible_for_config() -> None:
    outcomes = _synthetic_closed_outcomes(months=30, trades_per_month=8)
    overlay = _overlay_from_outcomes(outcomes)
    proxy_monthly_vol = _proxy_monthly_vol_map(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 120, "alpha": 0.05},
        random_strategy_mc_samples=120,
        seed=5,
    )

    payload = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )

    feasibility = payload["wfo_feasibility"]
    assert feasibility["is_feasible"] is False
    assert feasibility["max_feasible_folds"] < validation.wfo.min_folds
    assert "wfo_window_infeasible_for_config" in payload["blocking_reasons"]


def test_academic_validation_uses_bar_based_regime_mapping_without_proxy_trades() -> None:
    outcomes = _synthetic_closed_outcomes(months=24, trades_per_month=8)
    for row in outcomes:
        row["symbol"] = "SPY"
    overlay = _overlay_from_outcomes(outcomes)
    proxy_monthly_vol = _proxy_monthly_vol_map(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 120, "alpha": 0.05},
        random_strategy_mc_samples=120,
        seed=13,
    )

    payload = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol=proxy_monthly_vol,
    )

    regime = payload["regime_stability"]
    assert regime["proxy_month_count"] == len(proxy_monthly_vol)
    assert regime["mapped_trade_month_count"] > 0
    assert regime["missing_proxy_month_count"] == 0


def test_academic_validation_regime_missing_proxy_monthly_vol_hard_fails() -> None:
    outcomes = _synthetic_closed_outcomes(months=24, trades_per_month=8)
    overlay = _overlay_from_outcomes(outcomes)
    validation = ValidationConfig(
        bootstrap={"samples": 120, "alpha": 0.05},
        random_strategy_mc_samples=120,
        seed=31,
    )

    payload = build_academic_validation_payload(
        closed_outcomes=outcomes,
        validation=validation,
        citations=CitationsConfig(),
        execution_realism_overlay=overlay,
        regime_proxy_monthly_vol={},
    )

    assert "regime_stability_gate_failed" in payload["blocking_reasons"]
    assert payload["regime_stability"]["blocking_reasons"] == [
        "regime_proxy_monthly_vol_missing"
    ]
