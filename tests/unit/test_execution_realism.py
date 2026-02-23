from __future__ import annotations

import pytest

from sma_outfits.config.models import ExecutionCostsConfig
from sma_outfits.reporting.execution_realism import build_execution_realism_overlay


def test_execution_realism_overlay_applies_slippage_commission_and_latency() -> None:
    outcomes = [
        {
            "signal_id": "s1",
            "realized_r": 2.0,
            "risk_unit": 1.0,
            "entry": 100.0,
            "avg_exit_price": 110.0,
        }
    ]
    costs = ExecutionCostsConfig(
        slippage_bps_scenarios=[2.0],
        commission_bps_scenarios=[0.5],
        latency_bars_scenarios=[1],
        partial_fill_round_lot=True,
    )

    payload = build_execution_realism_overlay(
        closed_outcomes=outcomes,
        execution_costs=costs,
    )

    scenario_table = payload["scenario_table"]
    assert [row["scenario_id"] for row in scenario_table] == ["baseline_gross", "net_s1"]
    baseline = scenario_table[0]
    net = scenario_table[1]
    assert baseline["avg_realized_r"] == 2.0
    # cost_r = (2*slippage + 2*commission + latency*slippage) bps * notional / risk_unit
    #        = (4 + 1 + 2) bps * 210 / 10000 = 0.147
    assert net["avg_realized_r"] == pytest.approx(1.853, rel=1e-12)
    assert payload["gate_scenario_id"] == "net_s1"
    assert payload["gate_scenario_signal_r"]["s1"] == pytest.approx(1.853, rel=1e-12)


def test_execution_realism_scenario_table_has_expected_columns() -> None:
    outcomes = [
        {
            "signal_id": "s1",
            "realized_r": 1.5,
            "risk_unit": 1.0,
            "entry": 100.0,
            "avg_exit_price": 101.0,
        },
        {
            "signal_id": "s2",
            "realized_r": -0.5,
            "risk_unit": 1.0,
            "entry": 50.0,
            "avg_exit_price": 49.5,
        },
    ]
    payload = build_execution_realism_overlay(
        closed_outcomes=outcomes,
        execution_costs=ExecutionCostsConfig(),
    )
    required = {
        "scenario_id",
        "slippage_bps",
        "commission_bps",
        "latency_bars",
        "closed_positions",
        "avg_realized_r",
        "sharpe_annualized",
        "calmar_annualized",
    }
    for row in payload["scenario_table"]:
        assert required.issubset(row.keys())
