from __future__ import annotations

import pytest

from sma_outfits.reporting.metrics import (
    annualized_calmar_ratio,
    annualized_sharpe_ratio,
    annualized_sortino_ratio,
    max_drawdown,
    max_time_under_water,
    ulcer_index,
)


def test_reporting_metrics_share_consistent_drawdown_and_ratio_math() -> None:
    values = [1.0, -2.0, 1.0, -1.0, 2.0]

    assert max_drawdown(values) == pytest.approx(-2.0, rel=1e-12)
    assert max_time_under_water(values) == 3
    assert ulcer_index(values) == pytest.approx(1.3416407864998738, rel=1e-12)
    assert annualized_calmar_ratio(values) == pytest.approx(25.2, rel=1e-12)
    assert annualized_sharpe_ratio(values) == pytest.approx(1.932183566158592, rel=1e-12)
    assert annualized_sortino_ratio(values) == pytest.approx(4.48998886412873, rel=1e-12)
