from __future__ import annotations

import binascii
from collections import defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import struct
from typing import Any
import zlib

import numpy as np
import pandas as pd
import yaml

from sma_outfits.config.models import CitationsConfig, ValidationConfig
from sma_outfits.utils import ensure_utc_timestamp

_CITATION_REQUIRED_FIELDS = {
    "id",
    "title",
    "authors",
    "year",
    "venue",
    "type",
    "url",
    "why_it_matters",
    "retrieved_at_utc",
}

_CLAIM_SCOPE = {
    "objective": (
        "Assess whether configured SMA outfit events provide positive expected net realized R "
        "for the tested dataset and assumptions."
    ),
    "null_hypothesis": "mean(net_realized_r) <= 0",
    "alternative_hypothesis": "mean(net_realized_r) > 0",
    "supports_causal_inference": False,
    "causal_inference_statement": (
        "This validation does not establish causal claims about market manipulation "
        "or attribution to specific institutions."
    ),
}


@dataclass(frozen=True, slots=True)
class _AlignmentRule:
    id: str
    evidence_key: str
    weight: float
    description: str


def build_academic_validation_payload(
    *,
    closed_outcomes: list[dict[str, Any]],
    validation: ValidationConfig,
    citations: CitationsConfig,
    execution_realism_overlay: dict[str, Any],
    regime_proxy_monthly_vol: dict[str, float] | None = None,
) -> dict[str, Any]:
    citations_payload = _load_and_validate_citations(Path(citations.pack_path))
    alignment_rules = _load_alignment_rules(Path(validation.author_alignment_rules_path))

    scope_symbols = set(validation.scope_symbols)
    scoped_outcomes = [
        row
        for row in closed_outcomes
        if str(row.get("symbol", "")).upper() in scope_symbols
    ]
    scoped_outcomes.sort(
        key=lambda row: ensure_utc_timestamp(str(row.get("close_ts")))
        if row.get("close_ts") is not None
        else pd.Timestamp("1970-01-01T00:00:00Z")
    )
    gate_signal_values = execution_realism_overlay.get("gate_scenario_signal_r", {})
    if not isinstance(gate_signal_values, dict):
        raise RuntimeError(
            "Execution realism contract violation: gate_scenario_signal_r must be a dict"
        )
    net_scoped_outcomes = _apply_net_realized_r(
        scoped_outcomes=scoped_outcomes,
        gate_signal_values=gate_signal_values,
    )

    wfo_feasibility = _wfo_feasibility_summary(
        net_scoped_outcomes=net_scoped_outcomes,
        validation=validation,
    )
    wfo_folds = _build_wfo_folds(net_scoped_outcomes=net_scoped_outcomes, validation=validation)
    wfo_aggregate = _aggregate_wfo(folds=wfo_folds, validation=validation)
    oos_values = [float(row["net_realized_r"]) for row in net_scoped_outcomes]
    bootstrap = _bootstrap_summary(
        values=oos_values,
        method=validation.bootstrap.method,
        samples=validation.bootstrap.samples,
        alpha=validation.bootstrap.alpha,
        seed=validation.seed,
    )
    pvalues = _pvalue_summary(
        net_scoped_outcomes=net_scoped_outcomes,
        qvalue_threshold=validation.thresholds.fdr_qvalue_max,
    )
    regime_stability = _regime_stability_summary(
        net_scoped_outcomes=net_scoped_outcomes,
        proxy_symbol=validation.regime.proxy_symbol,
        require_positive_mean_in_each=validation.regime.require_positive_mean_in_each,
        regime_proxy_monthly_vol=regime_proxy_monthly_vol,
    )
    random_strategy_mc = _random_strategy_mc_summary(
        values=oos_values,
        samples=validation.random_strategy_mc_samples,
        seed=validation.seed + 17,
    )

    bootstrap_p_value = bootstrap.get("one_sided_p_value_mean_gt_zero")
    if bootstrap_p_value is None:
        bootstrap_gate_pass = False
    else:
        bootstrap_gate_pass = bool(bootstrap_p_value < validation.thresholds.bootstrap_pvalue_max)

    pvalues_rows = pvalues.get("rows", [])
    fdr_gate_pass = bool(pvalues_rows) and bool(pvalues.get("all_pass", False))
    regime_gate_pass = bool(regime_stability.get("passes_requirement", False))
    fold_count = int(wfo_aggregate["fold_count"])
    min_fold_trade_count = int(wfo_aggregate["min_fold_trade_count"])
    sharpe_gate_pass = bool(
        float(wfo_aggregate["oos_sharpe_annualized"]) >= validation.thresholds.oos_sharpe_min
    )
    calmar_gate_pass = bool(
        float(wfo_aggregate["oos_calmar_annualized"]) > validation.thresholds.oos_calmar_min
    )
    execution_gate_pass = bool(
        float(execution_realism_overlay.get("gate_scenario_metrics", {}).get("avg_realized_r", 0.0))
        >= 0.0
    )
    random_mc_gate_pass = bool(
        random_strategy_mc.get("observed_mean", 0.0) > random_strategy_mc.get("null_mean", 0.0)
    )

    evidence = {
        "wfo_min_folds": fold_count >= validation.wfo.min_folds,
        "wfo_min_closed_trades_per_fold": (
            fold_count > 0
            and min_fold_trade_count >= validation.wfo.min_closed_trades_per_fold
            and bool(wfo_aggregate["all_folds_min_trade_pass"])
        ),
        "oos_sharpe_threshold": sharpe_gate_pass,
        "oos_calmar_threshold": calmar_gate_pass,
        "bootstrap_significance": bootstrap_gate_pass,
        "fdr_gate": fdr_gate_pass,
        "regime_positive_means": regime_gate_pass,
        "random_mc_outperformance": random_mc_gate_pass,
        "execution_realism_non_negative": execution_gate_pass,
        "citation_pack_present": True,
    }
    replication = _replication_summary(rules=alignment_rules, evidence=evidence)

    blocking_reasons: list[str] = []
    if fold_count < validation.wfo.min_folds:
        blocking_reasons.append(
            f"wfo_fold_count_below_minimum:{fold_count}<{validation.wfo.min_folds}"
        )
    if not bool(wfo_feasibility.get("is_feasible", False)):
        blocking_reasons.append("wfo_window_infeasible_for_config")
    if min_fold_trade_count < validation.wfo.min_closed_trades_per_fold:
        blocking_reasons.append(
            "wfo_min_closed_trades_per_fold_violation:"
            f"{min_fold_trade_count}<{validation.wfo.min_closed_trades_per_fold}"
        )
    if not sharpe_gate_pass:
        blocking_reasons.append(
            "oos_sharpe_below_threshold:"
            f"{float(wfo_aggregate['oos_sharpe_annualized']):.6f}"
            f"<{validation.thresholds.oos_sharpe_min:.6f}"
        )
    if not calmar_gate_pass:
        blocking_reasons.append(
            "oos_calmar_not_above_threshold:"
            f"{float(wfo_aggregate['oos_calmar_annualized']):.6f}"
            f"<={validation.thresholds.oos_calmar_min:.6f}"
        )
    if not bootstrap_gate_pass:
        blocking_reasons.append(
            "bootstrap_pvalue_gate_failed:"
            f"p={bootstrap_p_value!r},threshold={validation.thresholds.bootstrap_pvalue_max}"
        )
    if not fdr_gate_pass:
        blocking_reasons.append("fdr_qvalue_gate_failed")
    if not regime_gate_pass:
        blocking_reasons.append("regime_stability_gate_failed")
    if float(replication["score"]) < validation.thresholds.replication_score_min:
        blocking_reasons.append(
            "replication_score_below_threshold:"
            f"{float(replication['score']):.6f}"
            f"<{validation.thresholds.replication_score_min:.6f}"
        )

    ready = len(blocking_reasons) == 0
    return {
        "ready": ready,
        "blocking_reasons": blocking_reasons,
        "claim_scope": dict(_CLAIM_SCOPE),
        "scope_symbols": list(validation.scope_symbols),
        "gate_scenario_id": str(execution_realism_overlay.get("gate_scenario_id", "")),
        "gate_scenario_metrics": dict(execution_realism_overlay.get("gate_scenario_metrics", {})),
        "fold_count": fold_count,
        "min_fold_trade_count": min_fold_trade_count,
        "bootstrap_p_value": bootstrap_p_value,
        "fdr_summary": {
            "method": pvalues.get("method"),
            "qvalue_threshold": pvalues.get("qvalue_threshold"),
            "all_pass": pvalues.get("all_pass"),
            "max_q_value": pvalues.get("max_q_value"),
        },
        "wfo_folds": wfo_folds,
        "wfo_feasibility": wfo_feasibility,
        "wfo_aggregate": wfo_aggregate,
        "bootstrap": bootstrap,
        "pvalues": pvalues,
        "regime_stability": regime_stability,
        "random_strategy_mc": random_strategy_mc,
        "replication": replication,
        "citation_pack": citations_payload,
    }


def write_bootstrap_histogram_png(
    *,
    histogram_bins: list[dict[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width = 960
    height = 540
    left = 64
    right = 24
    top = 28
    bottom = 52
    plot_width = max(1, width - left - right)
    plot_height = max(1, height - top - bottom)

    rgb = bytearray([255] * (width * height * 3))

    def _set_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if x < 0 or y < 0 or x >= width or y >= height:
            return
        offset = (y * width + x) * 3
        rgb[offset] = color[0]
        rgb[offset + 1] = color[1]
        rgb[offset + 2] = color[2]

    def _fill_rect(
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
    ) -> None:
        start_x = max(0, min(x0, x1))
        end_x = min(width - 1, max(x0, x1))
        start_y = max(0, min(y0, y1))
        end_y = min(height - 1, max(y0, y1))
        for y in range(start_y, end_y + 1):
            row_start = (y * width + start_x) * 3
            for x in range(start_x, end_x + 1):
                index = row_start + (x - start_x) * 3
                rgb[index] = color[0]
                rgb[index + 1] = color[1]
                rgb[index + 2] = color[2]

    for x in range(left, left + plot_width + 1):
        _set_pixel(x, top + plot_height, (40, 40, 40))
    for y in range(top, top + plot_height + 1):
        _set_pixel(left, y, (40, 40, 40))

    if histogram_bins:
        counts = [int(row.get("count", 0)) for row in histogram_bins]
        max_count = max(counts) if counts else 0
        max_count = max(max_count, 1)
        bar_count = len(histogram_bins)
        bar_width = max(1, plot_width // max(1, bar_count))
        for index, row in enumerate(histogram_bins):
            count = int(row.get("count", 0))
            bar_height = int(round((count / max_count) * (plot_height - 2)))
            x0 = left + index * bar_width + 1
            x1 = min(left + (index + 1) * bar_width - 1, left + plot_width - 1)
            y0 = top + plot_height - bar_height
            y1 = top + plot_height - 1
            _fill_rect(x0, y0, x1, y1, (47, 111, 237))

    _write_png_rgb(path=output_path, width=width, height=height, rgb=bytes(rgb))


def _apply_net_realized_r(
    *,
    scoped_outcomes: list[dict[str, Any]],
    gate_signal_values: dict[str, Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in scoped_outcomes:
        signal_id = str(row.get("signal_id"))
        if signal_id not in gate_signal_values:
            raise RuntimeError(
                "Execution realism contract violation: missing signal_id in gate scenario "
                f"payload: {signal_id}"
            )
        output.append(
            {
                **row,
                "net_realized_r": float(gate_signal_values[signal_id]),
            }
        )
    return output


def _wfo_feasibility_summary(
    *,
    net_scoped_outcomes: list[dict[str, Any]],
    validation: ValidationConfig,
) -> dict[str, Any]:
    close_ts = [
        ensure_utc_timestamp(str(row["close_ts"]))
        for row in net_scoped_outcomes
        if row.get("close_ts") is not None
    ]
    if not close_ts:
        available_months = 0
    else:
        first = min(close_ts)
        last = max(close_ts)
        available_months = ((last.year - first.year) * 12) + (last.month - first.month) + 1

    min_window_months = validation.wfo.train_months + validation.wfo.test_months
    required_months_for_min_folds = (
        min_window_months + (validation.wfo.min_folds - 1) * validation.wfo.step_months
    )
    max_feasible_folds = 0
    if available_months >= min_window_months:
        max_feasible_folds = (
            (available_months - min_window_months) // validation.wfo.step_months
        ) + 1

    return {
        "available_months": available_months,
        "required_months_for_min_folds": required_months_for_min_folds,
        "max_feasible_folds": max_feasible_folds,
        "is_feasible": max_feasible_folds >= validation.wfo.min_folds,
    }


def _build_wfo_folds(
    *,
    net_scoped_outcomes: list[dict[str, Any]],
    validation: ValidationConfig,
) -> list[dict[str, Any]]:
    if not net_scoped_outcomes:
        return []
    close_ts = [
        ensure_utc_timestamp(str(row["close_ts"]))
        for row in net_scoped_outcomes
        if row.get("close_ts") is not None
    ]
    if not close_ts:
        return []

    sorted_ts = sorted(close_ts)
    first_ts = sorted_ts[0]
    last_ts = sorted_ts[-1]
    anchor = pd.Timestamp(
        year=first_ts.year,
        month=first_ts.month,
        day=1,
        tz="UTC",
    )
    folds: list[dict[str, Any]] = []
    fold_index = 0
    while anchor <= last_ts:
        train_start = anchor
        train_end = train_start + pd.DateOffset(months=validation.wfo.train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=validation.wfo.test_months)
        if test_start > last_ts:
            break
        test_values = [
            float(row["net_realized_r"])
            for row in net_scoped_outcomes
            if row.get("close_ts") is not None
            and test_start <= ensure_utc_timestamp(str(row["close_ts"])) < test_end
        ]
        metrics = _series_metrics(test_values)
        fold_index += 1
        folds.append(
            {
                "fold_id": fold_index,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "closed_trades": int(metrics["closed_trades"]),
                "mean_r": float(metrics["mean_r"]),
                "total_r": float(metrics["total_r"]),
                "sharpe_annualized": float(metrics["sharpe_annualized"]),
                "calmar_annualized": float(metrics["calmar_annualized"]),
                "max_drawdown_r": float(metrics["max_drawdown_r"]),
                "min_trade_gate_pass": (
                    int(metrics["closed_trades"]) >= validation.wfo.min_closed_trades_per_fold
                ),
            }
        )
        anchor = anchor + pd.DateOffset(months=validation.wfo.step_months)
    return folds


def _aggregate_wfo(
    *,
    folds: list[dict[str, Any]],
    validation: ValidationConfig,
) -> dict[str, Any]:
    if not folds:
        return {
            "fold_count": 0,
            "min_required_folds": validation.wfo.min_folds,
            "min_fold_trade_count": 0,
            "min_required_trades_per_fold": validation.wfo.min_closed_trades_per_fold,
            "all_folds_min_trade_pass": False,
            "oos_sharpe_annualized": 0.0,
            "oos_calmar_annualized": 0.0,
            "oos_mean_r": 0.0,
            "oos_total_r": 0.0,
        }

    min_fold_trade_count = min(int(row["closed_trades"]) for row in folds)
    all_folds_min_trade_pass = all(bool(row["min_trade_gate_pass"]) for row in folds)
    weighted_sum = sum(float(row["mean_r"]) * int(row["closed_trades"]) for row in folds)
    total_trades = sum(int(row["closed_trades"]) for row in folds)
    oos_mean = (weighted_sum / total_trades) if total_trades > 0 else 0.0
    oos_total = sum(float(row["total_r"]) for row in folds)
    weighted_sharpe = (
        sum(float(row["sharpe_annualized"]) * int(row["closed_trades"]) for row in folds)
        / total_trades
        if total_trades > 0
        else 0.0
    )
    weighted_calmar = (
        sum(float(row["calmar_annualized"]) * int(row["closed_trades"]) for row in folds)
        / total_trades
        if total_trades > 0
        else 0.0
    )
    return {
        "fold_count": len(folds),
        "min_required_folds": validation.wfo.min_folds,
        "min_fold_trade_count": min_fold_trade_count,
        "min_required_trades_per_fold": validation.wfo.min_closed_trades_per_fold,
        "all_folds_min_trade_pass": all_folds_min_trade_pass,
        "oos_sharpe_annualized": weighted_sharpe,
        "oos_calmar_annualized": weighted_calmar,
        "oos_mean_r": oos_mean,
        "oos_total_r": oos_total,
    }


def _bootstrap_summary(
    *,
    values: list[float],
    method: str,
    samples: int,
    alpha: float,
    seed: int,
) -> dict[str, Any]:
    if method != "stationary_block":
        raise RuntimeError(f"Unsupported bootstrap method '{method}'")
    if not values:
        return {
            "method": method,
            "samples": samples,
            "alpha": alpha,
            "mean": 0.0,
            "std": 0.0,
            "ci": None,
            "one_sided_p_value_mean_gt_zero": None,
            "histogram_bins": [],
        }
    rng = np.random.default_rng(seed)
    series = np.array(values, dtype=float)
    block_length = max(2, int(round(np.sqrt(series.size))))
    bootstrap_means = np.empty(samples, dtype=float)
    for index in range(samples):
        draw = _stationary_bootstrap_draw(
            series=series,
            size=series.size,
            block_length=block_length,
            rng=rng,
        )
        bootstrap_means[index] = float(np.mean(draw))

    lower_q = alpha / 2.0
    upper_q = 1.0 - alpha / 2.0
    ci = {
        "lower": float(np.quantile(bootstrap_means, lower_q)),
        "upper": float(np.quantile(bootstrap_means, upper_q)),
    }
    p_value = float(np.mean(bootstrap_means <= 0.0))
    histogram_bins = _histogram_bins(values=bootstrap_means.tolist())
    return {
        "method": method,
        "samples": samples,
        "alpha": alpha,
        "block_length": block_length,
        "mean": float(np.mean(bootstrap_means)),
        "std": float(np.std(bootstrap_means, ddof=1)) if bootstrap_means.size > 1 else 0.0,
        "ci": ci,
        "one_sided_p_value_mean_gt_zero": p_value,
        "histogram_bins": histogram_bins,
    }


def _pvalue_summary(
    *,
    net_scoped_outcomes: list[dict[str, Any]],
    qvalue_threshold: float,
) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in net_scoped_outcomes:
        label = str(row.get("signal_type", "unknown"))
        grouped[label].append(float(row["net_realized_r"]))

    raw_rows: list[tuple[str, float]] = []
    for label, values in grouped.items():
        p_value = _one_sided_mean_pvalue(values)
        if p_value is not None:
            raw_rows.append((label, p_value))
    qvalues = _fdr_bh(raw_rows)
    rows: list[dict[str, Any]] = []
    for label, raw_p in sorted(raw_rows, key=lambda item: item[0]):
        q_value = qvalues.get(label)
        pass_gate = (q_value is not None) and (q_value <= qvalue_threshold)
        rows.append(
            {
                "label": label,
                "raw_p_value": raw_p,
                "fdr_q_value": q_value,
                "pass_gate": pass_gate,
            }
        )
    max_q = max((float(row["fdr_q_value"]) for row in rows if row["fdr_q_value"] is not None), default=None)
    return {
        "method": "fdr_bh",
        "qvalue_threshold": qvalue_threshold,
        "rows": rows,
        "all_pass": bool(rows) and all(bool(row["pass_gate"]) for row in rows),
        "max_q_value": max_q,
    }


def _regime_stability_summary(
    *,
    net_scoped_outcomes: list[dict[str, Any]],
    proxy_symbol: str,
    require_positive_mean_in_each: bool,
    regime_proxy_monthly_vol: dict[str, float] | None,
) -> dict[str, Any]:
    trade_rows: list[tuple[str, float]] = []
    for row in net_scoped_outcomes:
        close_ts = row.get("close_ts")
        if close_ts is None:
            continue
        month_key = ensure_utc_timestamp(str(close_ts)).strftime("%Y-%m")
        trade_rows.append((month_key, float(row["net_realized_r"])))
    trade_months = {month for month, _value in trade_rows}

    if not net_scoped_outcomes:
        return {
            "proxy_symbol": proxy_symbol,
            "proxy_month_count": 0,
            "mapped_trade_month_count": 0,
            "missing_proxy_month_count": 0,
            "high_vol_count": 0,
            "low_vol_count": 0,
            "high_vol_mean_r": 0.0,
            "low_vol_mean_r": 0.0,
            "passes_requirement": False,
            "blocking_reasons": ["no_scoped_outcomes"],
        }

    if regime_proxy_monthly_vol is None or len(regime_proxy_monthly_vol) == 0:
        return {
            "proxy_symbol": proxy_symbol,
            "proxy_month_count": 0,
            "mapped_trade_month_count": 0,
            "missing_proxy_month_count": len(trade_months),
            "high_vol_count": 0,
            "low_vol_count": 0,
            "high_vol_mean_r": 0.0,
            "low_vol_mean_r": 0.0,
            "passes_requirement": False,
            "blocking_reasons": ["regime_proxy_monthly_vol_missing"],
        }

    proxy_scores: dict[str, float] = {}
    for month, raw_value in regime_proxy_monthly_vol.items():
        candidate = float(raw_value)
        if not math.isfinite(candidate):
            raise RuntimeError(
                "Regime stability contract violation: proxy month volatility must be finite, "
                f"got {raw_value!r} for month '{month}'"
            )
        proxy_scores[str(month)] = candidate

    if not proxy_scores:
        return {
            "proxy_symbol": proxy_symbol,
            "proxy_month_count": 0,
            "mapped_trade_month_count": 0,
            "missing_proxy_month_count": len(trade_months),
            "high_vol_count": 0,
            "low_vol_count": 0,
            "high_vol_mean_r": 0.0,
            "low_vol_mean_r": 0.0,
            "passes_requirement": False,
            "blocking_reasons": ["regime_proxy_monthly_vol_missing"],
        }

    threshold = float(np.median(np.array(list(proxy_scores.values()), dtype=float)))
    high_months = {month for month, value in proxy_scores.items() if value >= threshold}
    low_months = {month for month, value in proxy_scores.items() if value < threshold}

    high_values: list[float] = []
    low_values: list[float] = []
    missing_proxy_months: set[str] = set()
    for month, value in trade_rows:
        if month in high_months:
            high_values.append(value)
        elif month in low_months:
            low_values.append(value)
        else:
            missing_proxy_months.add(month)

    high_mean = float(np.mean(high_values)) if high_values else 0.0
    low_mean = float(np.mean(low_values)) if low_values else 0.0
    positive_pass = (
        (high_mean > 0.0 and low_mean > 0.0)
        if require_positive_mean_in_each
        else True
    )
    blocking_reasons: list[str] = []
    if missing_proxy_months:
        blocking_reasons.append("regime_proxy_month_mapping_missing")
    if not high_values:
        blocking_reasons.append("regime_high_vol_partition_empty")
    if not low_values:
        blocking_reasons.append("regime_low_vol_partition_empty")
    if require_positive_mean_in_each and not positive_pass:
        blocking_reasons.append("regime_positive_mean_requirement_failed")

    return {
        "proxy_symbol": proxy_symbol,
        "proxy_month_count": len(proxy_scores),
        "mapped_trade_month_count": len(trade_months) - len(missing_proxy_months),
        "proxy_high_vol_threshold": threshold,
        "high_vol_count": len(high_values),
        "low_vol_count": len(low_values),
        "high_vol_mean_r": high_mean,
        "low_vol_mean_r": low_mean,
        "missing_proxy_month_count": len(missing_proxy_months),
        "passes_requirement": len(blocking_reasons) == 0,
        "blocking_reasons": blocking_reasons,
    }


def _random_strategy_mc_summary(
    *,
    values: list[float],
    samples: int,
    seed: int,
) -> dict[str, Any]:
    if not values:
        return {
            "samples": samples,
            "observed_mean": 0.0,
            "null_mean": 0.0,
            "null_std": 0.0,
            "one_sided_p_value_observed_gt_null": None,
        }
    observed = np.array(values, dtype=float)
    centered = observed - float(np.mean(observed))
    rng = np.random.default_rng(seed)
    block_length = max(2, int(round(np.sqrt(centered.size))))
    null_means = np.empty(samples, dtype=float)
    for index in range(samples):
        draw = _stationary_bootstrap_draw(
            series=centered,
            size=centered.size,
            block_length=block_length,
            rng=rng,
        )
        null_means[index] = float(np.mean(draw))

    observed_mean = float(np.mean(observed))
    p_value = float(np.mean(null_means >= observed_mean))
    return {
        "samples": samples,
        "block_length": block_length,
        "observed_mean": observed_mean,
        "null_mean": float(np.mean(null_means)),
        "null_std": float(np.std(null_means, ddof=1)) if null_means.size > 1 else 0.0,
        "one_sided_p_value_observed_gt_null": p_value,
    }


def _replication_summary(
    *,
    rules: list[_AlignmentRule],
    evidence: dict[str, bool],
) -> dict[str, Any]:
    total_weight = float(sum(rule.weight for rule in rules))
    passed_weight = 0.0
    checks: list[dict[str, Any]] = []
    for rule in rules:
        passed = bool(evidence.get(rule.evidence_key, False))
        if passed:
            passed_weight += rule.weight
        checks.append(
            {
                "id": rule.id,
                "description": rule.description,
                "evidence_key": rule.evidence_key,
                "weight": rule.weight,
                "passed": passed,
            }
        )
    score = (passed_weight / total_weight) if total_weight > 0 else 0.0
    return {
        "score": score,
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "checks": checks,
    }


def _load_and_validate_citations(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Citation pack not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Citation pack must be a map: {path}")
    citations = payload.get("citations")
    if not isinstance(citations, list) or not citations:
        raise RuntimeError(f"Citation pack citations must be a non-empty list: {path}")
    validated_rows: list[dict[str, Any]] = []
    for index, row in enumerate(citations):
        if not isinstance(row, dict):
            raise RuntimeError(
                f"Citation row[{index}] must be a map in citation pack: {path}"
            )
        missing = sorted(field for field in _CITATION_REQUIRED_FIELDS if field not in row)
        if missing:
            raise RuntimeError(
                "Citation row[{0}] missing required fields: {1}".format(
                    index, ", ".join(missing)
                )
            )
        for field in _CITATION_REQUIRED_FIELDS:
            value = row[field]
            if isinstance(value, str):
                if not value.strip():
                    raise RuntimeError(
                        f"Citation row[{index}] field '{field}' must be non-empty"
                    )
            elif field == "authors":
                if not isinstance(value, list) or not value:
                    raise RuntimeError(
                        f"Citation row[{index}] field 'authors' must be a non-empty list"
                    )
            else:
                if value is None:
                    raise RuntimeError(
                        f"Citation row[{index}] field '{field}' must not be null"
                    )
        validated_rows.append(
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "authors": [str(author) for author in list(row["authors"])],
                "year": int(row["year"]),
                "venue": str(row["venue"]),
                "type": str(row["type"]),
                "url": str(row["url"]),
                "why_it_matters": str(row["why_it_matters"]),
                "retrieved_at_utc": str(row["retrieved_at_utc"]),
            }
        )
    return {
        "pack_path": str(path),
        "count": len(validated_rows),
        "entries": validated_rows,
    }


def _load_alignment_rules(path: Path) -> list[_AlignmentRule]:
    if not path.exists():
        raise FileNotFoundError(f"Author alignment rules not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Author alignment rules must be a map: {path}")
    rows = payload.get("rules")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Author alignment rules must include non-empty 'rules': {path}")

    rules: list[_AlignmentRule] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RuntimeError(f"Alignment rule row[{index}] must be a map: {path}")
        rule_id = str(row.get("id", "")).strip()
        evidence_key = str(row.get("evidence_key", "")).strip()
        description = str(row.get("description", "")).strip()
        weight_raw = row.get("weight", 1.0)
        try:
            weight = float(weight_raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Alignment rule row[{index}] has invalid weight: {weight_raw!r}"
            ) from exc
        if not rule_id:
            raise RuntimeError(f"Alignment rule row[{index}] id must be non-empty")
        if rule_id in seen_ids:
            raise RuntimeError(f"Duplicate alignment rule id '{rule_id}' in {path}")
        if not evidence_key:
            raise RuntimeError(
                f"Alignment rule row[{index}] evidence_key must be non-empty"
            )
        if not description:
            raise RuntimeError(
                f"Alignment rule row[{index}] description must be non-empty"
            )
        if weight <= 0:
            raise RuntimeError(
                f"Alignment rule row[{index}] weight must be > 0, got {weight_raw!r}"
            )
        seen_ids.add(rule_id)
        rules.append(
            _AlignmentRule(
                id=rule_id,
                evidence_key=evidence_key,
                weight=weight,
                description=description,
            )
        )
    return rules


def _stationary_bootstrap_draw(
    *,
    series: np.ndarray,
    size: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if series.size == 0:
        return np.array([], dtype=float)
    if series.size == 1:
        return np.repeat(series[0], size)
    p_new = 1.0 / max(float(block_length), 1.0)
    out = np.empty(size, dtype=float)
    index = int(rng.integers(0, series.size))
    for pos in range(size):
        if pos == 0 or rng.random() < p_new:
            index = int(rng.integers(0, series.size))
        out[pos] = float(series[index])
        index = (index + 1) % series.size
    return out


def _histogram_bins(*, values: list[float]) -> list[dict[str, Any]]:
    if not values:
        return []
    samples = np.array(values, dtype=float)
    bin_count = max(10, min(40, int(round(np.sqrt(samples.size)))))
    counts, edges = np.histogram(samples, bins=bin_count)
    output: list[dict[str, Any]] = []
    for index in range(bin_count):
        output.append(
            {
                "bin_left": float(edges[index]),
                "bin_right": float(edges[index + 1]),
                "count": int(counts[index]),
            }
        )
    return output


def _one_sided_mean_pvalue(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    series = np.array(values, dtype=float)
    std = float(np.std(series, ddof=1))
    mean = float(np.mean(series))
    if std <= 0:
        return 0.0 if mean > 0 else 1.0
    statistic = mean / (std / float(np.sqrt(series.size)))
    return float(1.0 - _normal_cdf(statistic))


def _normal_cdf(value: float) -> float:
    return float(0.5 * (1.0 + math.erf(value / math.sqrt(2.0))))


def _fdr_bh(rows: list[tuple[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    ordered = sorted(rows, key=lambda item: item[1])
    m = len(ordered)
    raw_q: list[float] = []
    for rank, (_, p_value) in enumerate(ordered, start=1):
        raw_q.append(min(1.0, p_value * m / rank))
    adjusted = raw_q[:]
    for index in range(m - 2, -1, -1):
        adjusted[index] = min(adjusted[index], adjusted[index + 1])
    return {ordered[index][0]: float(adjusted[index]) for index in range(m)}


def _series_metrics(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {
            "closed_trades": 0,
            "mean_r": 0.0,
            "total_r": 0.0,
            "sharpe_annualized": 0.0,
            "calmar_annualized": 0.0,
            "max_drawdown_r": 0.0,
        }
    series = np.array(values, dtype=float)
    mean_r = float(np.mean(series))
    total_r = float(np.sum(series))
    std = float(np.std(series, ddof=1)) if series.size > 1 else 0.0
    sharpe = (mean_r / std) * float(np.sqrt(252.0)) if std > 0 else 0.0
    max_drawdown = _max_drawdown(values)
    annualized_return = mean_r * 252.0
    if max_drawdown < 0:
        calmar = annualized_return / abs(max_drawdown)
    else:
        calmar = annualized_return if annualized_return > 0 else 0.0
    return {
        "closed_trades": int(series.size),
        "mean_r": mean_r,
        "total_r": total_r,
        "sharpe_annualized": sharpe,
        "calmar_annualized": calmar,
        "max_drawdown_r": max_drawdown,
    }


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    equity = np.cumsum(np.array(values, dtype=float))
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity - peaks
    return float(np.min(drawdowns)) if drawdowns.size else 0.0


def _write_png_rgb(*, path: Path, width: int, height: int, rgb: bytes) -> None:
    if len(rgb) != width * height * 3:
        raise RuntimeError("PNG writer contract violation: invalid RGB payload size")

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = binascii.crc32(chunk_type)
        crc = binascii.crc32(data, crc) & 0xFFFFFFFF
        return (
            struct.pack("!I", len(data))
            + chunk_type
            + data
            + struct.pack("!I", crc)
        )

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)

    raw = bytearray()
    row_bytes = width * 3
    for row_index in range(height):
        raw.append(0)
        start = row_index * row_bytes
        raw.extend(rgb[start : start + row_bytes])
    compressed = zlib.compress(bytes(raw), level=9)
    payload = (
        header
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(payload)
