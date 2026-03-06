from __future__ import annotations

from typing import Any

import numpy as np

from sma_outfits.config.models import ExecutionCostsConfig
from sma_outfits.reporting.metrics import annualized_calmar_ratio, annualized_sharpe_ratio, max_drawdown


def build_execution_realism_overlay(
    *,
    closed_outcomes: list[dict[str, Any]],
    execution_costs: ExecutionCostsConfig,
) -> dict[str, Any]:
    gross_values = [float(row["realized_r"]) for row in closed_outcomes]
    scenario_table: list[dict[str, Any]] = []
    scenario_signal_values: dict[str, dict[str, float]] = {}

    baseline_metrics = _series_metrics(gross_values)
    scenario_table.append(
        {
            "scenario_id": "baseline_gross",
            "slippage_bps": 0.0,
            "commission_bps": 0.0,
            "latency_bars": 0,
            **baseline_metrics,
        }
    )
    scenario_signal_values["baseline_gross"] = {
        str(row["signal_id"]): float(row["realized_r"]) for row in closed_outcomes
    }

    for index, (slippage_bps, commission_bps, latency_bars) in enumerate(
        zip(
            execution_costs.slippage_bps_scenarios,
            execution_costs.commission_bps_scenarios,
            execution_costs.latency_bars_scenarios,
            strict=True,
        ),
        start=1,
    ):
        scenario_id = f"net_s{index}"
        scenario_values: list[float] = []
        signal_map: dict[str, float] = {}
        for row in closed_outcomes:
            signal_id = str(row["signal_id"])
            gross_r = float(row["realized_r"])
            risk_unit = float(row.get("risk_unit", 0.0))
            entry_price = abs(float(row.get("entry", 0.0)))
            avg_exit_price = abs(float(row.get("avg_exit_price", entry_price)))

            cost_r = _execution_cost_r(
                risk_unit=risk_unit,
                entry_price=entry_price,
                avg_exit_price=avg_exit_price,
                slippage_bps=float(slippage_bps),
                commission_bps=float(commission_bps),
                latency_bars=int(latency_bars),
            )
            net_r = gross_r - cost_r
            scenario_values.append(net_r)
            signal_map[signal_id] = net_r

        metrics = _series_metrics(scenario_values)
        scenario_table.append(
            {
                "scenario_id": scenario_id,
                "slippage_bps": float(slippage_bps),
                "commission_bps": float(commission_bps),
                "latency_bars": int(latency_bars),
                **metrics,
            }
        )
        scenario_signal_values[scenario_id] = signal_map

    gate_scenario_id = scenario_table[-1]["scenario_id"] if scenario_table else "baseline_gross"
    gate_scenario_signal_values = scenario_signal_values[gate_scenario_id]
    gate_scenario_values = [
        float(gate_scenario_signal_values[str(row["signal_id"])]) for row in closed_outcomes
    ]

    return {
        "partial_fill_round_lot": bool(execution_costs.partial_fill_round_lot),
        "scenario_table": scenario_table,
        "scenario_ids": [str(row["scenario_id"]) for row in scenario_table],
        "gate_scenario_id": gate_scenario_id,
        "gate_scenario_metrics": dict(scenario_table[-1]) if scenario_table else {},
        "gate_scenario_realized_r": gate_scenario_values,
        "gate_scenario_signal_r": gate_scenario_signal_values,
    }


def public_execution_realism_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    sanitized.pop("gate_scenario_realized_r", None)
    sanitized.pop("gate_scenario_signal_r", None)
    return sanitized


def _execution_cost_r(
    *,
    risk_unit: float,
    entry_price: float,
    avg_exit_price: float,
    slippage_bps: float,
    commission_bps: float,
    latency_bars: int,
) -> float:
    if risk_unit <= 0:
        return 0.0
    round_trip_notional = entry_price + avg_exit_price
    slippage_cost_bps = slippage_bps * 2.0
    commission_cost_bps = commission_bps * 2.0
    latency_cost_bps = slippage_bps * max(float(latency_bars), 0.0)
    total_bps = slippage_cost_bps + commission_cost_bps + latency_cost_bps
    return (total_bps / 10000.0) * (round_trip_notional / risk_unit)


def _series_metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "closed_positions": 0,
            "total_realized_r": 0.0,
            "avg_realized_r": 0.0,
            "min_realized_r": 0.0,
            "max_realized_r": 0.0,
            "sharpe_annualized": 0.0,
            "calmar_annualized": 0.0,
            "max_drawdown_r": 0.0,
        }
    samples = np.array(values, dtype=float)
    mean_value = float(np.mean(samples))
    sharpe = annualized_sharpe_ratio(values)
    max_drawdown_r = max_drawdown(values)
    calmar = annualized_calmar_ratio(values)
    return {
        "closed_positions": int(samples.size),
        "total_realized_r": float(np.sum(samples)),
        "avg_realized_r": mean_value,
        "min_realized_r": float(np.min(samples)),
        "max_realized_r": float(np.max(samples)),
        "sharpe_annualized": sharpe,
        "calmar_annualized": calmar,
        "max_drawdown_r": max_drawdown_r,
    }
