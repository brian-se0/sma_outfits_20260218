from __future__ import annotations

from collections.abc import Sequence
import math

import numpy as np

TRADING_PERIODS_PER_YEAR = 252.0


def max_drawdown(values: Sequence[float]) -> float:
    drawdowns = _drawdowns(values)
    return float(np.min(drawdowns)) if drawdowns.size else 0.0


def ulcer_index(values: Sequence[float]) -> float:
    drawdowns = _drawdowns(values)
    if not drawdowns.size:
        return 0.0
    return float(math.sqrt(float(np.mean(np.square(drawdowns)))))


def max_time_under_water(values: Sequence[float]) -> int:
    drawdowns = _drawdowns(values)
    max_streak = 0
    streak = 0
    for value in drawdowns.tolist():
        if value < 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0
    return max_streak


def annualized_sharpe_ratio(
    values: Sequence[float],
    *,
    periods_per_year: float = TRADING_PERIODS_PER_YEAR,
) -> float:
    samples = _samples(values)
    if samples.size == 0:
        return 0.0
    std_value = float(np.std(samples, ddof=1)) if samples.size > 1 else 0.0
    if std_value <= 0:
        return 0.0
    mean_value = float(np.mean(samples))
    return (mean_value / std_value) * math.sqrt(periods_per_year)


def annualized_sortino_ratio(
    values: Sequence[float],
    *,
    periods_per_year: float = TRADING_PERIODS_PER_YEAR,
) -> float:
    samples = _samples(values)
    if samples.size == 0:
        return 0.0
    downside = samples[samples < 0.0]
    downside_std = float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
    if downside_std <= 0:
        return 0.0
    mean_value = float(np.mean(samples))
    return (mean_value / downside_std) * math.sqrt(periods_per_year)


def annualized_calmar_ratio(
    values: Sequence[float],
    *,
    periods_per_year: float = TRADING_PERIODS_PER_YEAR,
) -> float:
    samples = _samples(values)
    if samples.size == 0:
        return 0.0
    annualized_return = float(np.mean(samples) * periods_per_year)
    drawdown = max_drawdown(values)
    if drawdown < 0:
        return annualized_return / abs(drawdown)
    return annualized_return if annualized_return > 0 else 0.0


def _samples(values: Sequence[float]) -> np.ndarray:
    return np.array(values, dtype=float)


def _drawdowns(values: Sequence[float]) -> np.ndarray:
    samples = _samples(values)
    if samples.size == 0:
        return np.array([], dtype=float)
    equity = np.cumsum(samples)
    peaks = np.maximum.accumulate(equity)
    return equity - peaks
