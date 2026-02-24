from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from sma_outfits.config.models import CitationsConfig, ExecutionCostsConfig, ValidationConfig
from sma_outfits.events import PositionEvent, SignalEvent, StrikeEvent
from sma_outfits.reporting.academic_validation import (
    build_academic_validation_payload,
    write_bootstrap_histogram_png,
)
from sma_outfits.reporting.execution_realism import (
    build_execution_realism_overlay,
    public_execution_realism_payload,
)
from sma_outfits.utils import ensure_utc_timestamp

def build_summary(
    strikes: list[StrikeEvent],
    signals: list[SignalEvent],
    position_events: list[PositionEvent],
) -> dict[str, Any]:
    strike_lookup = {strike.id: strike for strike in strikes}

    symbol_counter: Counter[str] = Counter()
    outfit_counter: Counter[str] = Counter()
    for signal in signals:
        strike = _require_signal_strike(signal=signal, strike_lookup=strike_lookup)
        symbol_counter[strike.symbol] += 1
        outfit_counter[strike.outfit_id] += 1

    outcomes = _compute_signal_outcomes(signals, position_events, strike_lookup)
    closed_outcomes = [outcome for outcome in outcomes if outcome["closed"]]
    r_values = [float(outcome["realized_r"]) for outcome in closed_outcomes]
    hits = [outcome for outcome in closed_outcomes if float(outcome["realized_r"]) > 0.0]

    summary = {
        "total_strikes": len(strikes),
        "total_signals": len(signals),
        "total_position_events": len(position_events),
        "closed_positions": len(closed_outcomes),
        "win_rate": (len(hits) / len(closed_outcomes)) if closed_outcomes else 0.0,
        "hit_rate": (len(hits) / len(closed_outcomes)) if closed_outcomes else 0.0,
        "top_symbols": symbol_counter.most_common(5),
        "top_outfits": outfit_counter.most_common(5),
        "close_reason_breakdown": sorted(
            Counter(
                str(outcome["close_reason"])
                for outcome in closed_outcomes
                if outcome["close_reason"] is not None
            ).items(),
            key=lambda item: item[1],
            reverse=True,
        ),
        "hit_rate_by_signal_type": _rate_breakdown(closed_outcomes, "signal_type"),
        "hit_rate_by_side": _rate_breakdown(closed_outcomes, "side"),
        "r_by_signal_type": _r_breakdown(closed_outcomes, "signal_type"),
        "r_outcome": {
            "total_realized_r": sum(r_values),
            "avg_realized_r": (sum(r_values) / len(r_values)) if r_values else 0.0,
            "median_realized_r": median(r_values) if r_values else 0.0,
            "min_realized_r": min(r_values) if r_values else 0.0,
            "max_realized_r": max(r_values) if r_values else 0.0,
            "bucket_counts": _r_bucket_counts(r_values),
        },
        "period_summary_daily": _period_summary(closed_outcomes, period="daily"),
        "period_summary_monthly": _period_summary(closed_outcomes, period="monthly"),
        "statistical_validation": _build_statistical_validation(
            closed_outcomes=closed_outcomes,
            total_signals=len(signals),
        ),
    }
    return summary


def build_summary_from_records(
    strike_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    validation: ValidationConfig | None = None,
    execution_costs: ExecutionCostsConfig | None = None,
    citations: CitationsConfig | None = None,
    regime_proxy_monthly_vol: dict[str, float] | None = None,
) -> dict[str, Any]:
    strikes = [_record_to_strike(row) for row in strike_rows]
    signals = [_record_to_signal(row) for row in signal_rows]
    positions = [_record_to_position(row) for row in position_rows]

    strike_summary = _build_strike_attribution_summary(
        strikes=strikes,
        signals=signals,
        positions=positions,
        start=start,
        end=end,
    )
    close_summary = _build_close_attribution_summary(
        strikes=strikes,
        signals=signals,
        positions=positions,
        start=start,
        end=end,
    )

    close_outcomes = _closed_outcomes_for_close_attribution(
        strikes=strikes,
        signals=signals,
        positions=positions,
        start=start,
        end=end,
    )
    validation_config = validation or ValidationConfig()
    execution_costs_config = execution_costs or ExecutionCostsConfig()
    citations_config = citations or CitationsConfig()

    execution_realism_overlay = build_execution_realism_overlay(
        closed_outcomes=close_outcomes,
        execution_costs=execution_costs_config,
    )
    academic_validation = build_academic_validation_payload(
        closed_outcomes=close_outcomes,
        validation=validation_config,
        citations=citations_config,
        execution_realism_overlay=execution_realism_overlay,
        regime_proxy_monthly_vol=regime_proxy_monthly_vol,
    )
    execution_realism = public_execution_realism_payload(execution_realism_overlay)

    return {
        "attribution_mode": "both",
        "strike_attribution": dict(strike_summary),
        "close_attribution": dict(close_summary),
        "execution_realism": execution_realism,
        "academic_validation": academic_validation,
    }


def write_summary_report(
    summary: dict[str, Any],
    root: Path,
    label: str,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    markdown_path = root / f"{label}.md"
    csv_path = root / f"{label}.csv"
    academic_json_path = root / f"{label}_academic_validation.json"
    wfo_csv_path = root / f"{label}_wfo_table.csv"
    pvalues_csv_path = root / f"{label}_pvalues.csv"
    bootstrap_bins_csv_path = root / f"{label}_bootstrap_bins.csv"
    figures_root = root / "figures"
    bootstrap_png_path = figures_root / f"{label}_bootstrap_hist.png"

    attribution_mode = str(summary.get("attribution_mode", ""))
    if attribution_mode != "both":
        raise RuntimeError(
            "Summary contract violation: write_summary_report requires attribution_mode='both'"
        )
    strike_summary = _require_strike_attribution(summary)
    close_summary = _require_close_attribution(summary)
    execution_realism = _require_execution_realism(summary)
    academic_validation = _require_academic_validation(summary)
    markdown: list[str] = [
        f"# Replay Summary: {label}",
        "",
        "- attribution_mode: `both`",
        "",
    ]

    markdown.extend(
        _render_markdown_section(
            title="Strike-Time Attribution",
            summary=strike_summary,
        )
    )
    markdown.append("")
    markdown.extend(
        _render_markdown_section(
            title="Close-Time Attribution",
            summary=close_summary,
        )
    )
    markdown.append("")
    markdown.extend(
        _render_academic_validation_appendix(
            academic_validation=academic_validation,
            execution_realism=execution_realism,
        )
    )

    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")

    flattened = {"attribution_mode": "both"}
    flattened.update(_flatten_summary(strike_summary, prefix="strike_"))
    flattened.update(_flatten_summary(close_summary, prefix="close_"))
    flattened["academic_validation_ready"] = bool(academic_validation.get("ready", False))
    flattened["academic_validation_fold_count"] = int(academic_validation.get("fold_count", 0))
    flattened["academic_validation_min_fold_trade_count"] = int(
        academic_validation.get("min_fold_trade_count", 0)
    )
    flattened["academic_validation_bootstrap_p_value"] = academic_validation.get(
        "bootstrap_p_value"
    )
    flattened["academic_validation_gate_scenario_id"] = str(
        academic_validation.get("gate_scenario_id", "")
    )

    pd.DataFrame([flattened]).to_csv(csv_path, index=False)

    bootstrap_payload = academic_validation.get("bootstrap", {})
    if not isinstance(bootstrap_payload, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.bootstrap must be a dict"
        )
    histogram_bins = bootstrap_payload.get("histogram_bins", [])
    if not isinstance(histogram_bins, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.bootstrap.histogram_bins must be a list"
        )
    write_bootstrap_histogram_png(
        histogram_bins=histogram_bins,
        output_path=bootstrap_png_path,
    )

    wfo_rows = academic_validation.get("wfo_folds", [])
    if not isinstance(wfo_rows, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.wfo_folds must be a list"
        )
    pd.DataFrame(wfo_rows).to_csv(wfo_csv_path, index=False)

    pvalues_payload = academic_validation.get("pvalues", {})
    if not isinstance(pvalues_payload, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.pvalues must be a dict"
        )
    pvalue_rows = pvalues_payload.get("rows", [])
    if not isinstance(pvalue_rows, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.pvalues.rows must be a list"
        )
    pd.DataFrame(pvalue_rows).to_csv(pvalues_csv_path, index=False)
    pd.DataFrame(histogram_bins).to_csv(bootstrap_bins_csv_path, index=False)

    academic_json_payload = dict(academic_validation)
    bootstrap_with_path = dict(bootstrap_payload)
    bootstrap_with_path["histogram_png_path"] = str(bootstrap_png_path)
    academic_json_payload["bootstrap"] = bootstrap_with_path
    academic_json_path.write_text(
        json.dumps(academic_json_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return markdown_path, csv_path


def _compute_signal_outcomes(
    signals: list[SignalEvent],
    position_events: list[PositionEvent],
    strike_lookup: dict[str, StrikeEvent],
) -> list[dict[str, Any]]:
    grouped_positions: dict[str, list[PositionEvent]] = defaultdict(list)
    for event in position_events:
        grouped_positions[event.signal_id].append(event)

    outcomes: list[dict[str, Any]] = []
    for signal in signals:
        risk_unit = abs(signal.entry - signal.stop)
        if risk_unit <= 0:
            continue

        direction = 1.0 if signal.side == "LONG" else -1.0
        realized_r = 0.0
        close_reason: str | None = None
        close_ts: datetime | None = None
        closed = False

        events = sorted(grouped_positions.get(signal.id, []), key=lambda row: row.ts)
        fill_events = [event for event in events if event.action in {"partial_take", "close"}]
        realized_qty = sum(float(event.qty) for event in fill_events)
        if fill_events and realized_qty <= 0:
            raise RuntimeError(
                "Signal outcome contract violation: non-positive realized_qty "
                f"(signal_id={signal.id})"
            )
        avg_exit_price = signal.entry
        if fill_events and realized_qty > 0:
            avg_exit_price = (
                sum(float(event.price) * float(event.qty) for event in fill_events) / realized_qty
            )
        for event in events:
            if event.action in {"partial_take", "close"}:
                qty_weight = float(event.qty) / realized_qty if realized_qty > 0 else 0.0
                realized_r += (
                    qty_weight
                    * direction
                    * ((float(event.price) - signal.entry) / risk_unit)
                )
            if event.action == "close":
                closed = True
                close_reason = event.reason
                close_ts = event.ts

        strike = _require_signal_strike(signal=signal, strike_lookup=strike_lookup)
        outcomes.append(
            {
                "signal_id": signal.id,
                "route_id": signal.route_id,
                "signal_type": signal.signal_type,
                "side": signal.side,
                "symbol": strike.symbol,
                "outfit_id": strike.outfit_id,
                "timeframe": strike.timeframe,
                "realized_r": realized_r,
                "entry": signal.entry,
                "stop": signal.stop,
                "risk_unit": risk_unit,
                "avg_exit_price": avg_exit_price,
                "closed": closed,
                "close_reason": close_reason,
                "close_ts": close_ts,
            }
        )
    return outcomes


def _build_strike_attribution_summary(
    *,
    strikes: list[StrikeEvent],
    signals: list[SignalEvent],
    positions: list[PositionEvent],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> dict[str, Any]:
    selected_strikes = strikes
    selected_signals = signals
    selected_positions = positions
    if start is not None and end is not None:
        selected_strikes = [
            strike for strike in strikes if _in_range(strike.bar_ts, start, end)
        ]
        allowed_strikes = {strike.id for strike in selected_strikes}
        selected_signals = [
            signal for signal in signals if signal.strike_id in allowed_strikes
        ]
        allowed_signals = {signal.id for signal in selected_signals}
        selected_positions = [
            position
            for position in positions
            if _in_range(position.ts, start, end)
            and position.signal_id in allowed_signals
        ]

    return build_summary(
        strikes=selected_strikes,
        signals=selected_signals,
        position_events=selected_positions,
    )


def _build_close_attribution_summary(
    *,
    strikes: list[StrikeEvent],
    signals: list[SignalEvent],
    positions: list[PositionEvent],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> dict[str, Any]:
    if start is None or end is None:
        return build_summary(strikes=strikes, signals=signals, position_events=positions)

    strike_lookup = {strike.id: strike for strike in strikes}
    outcomes = _compute_signal_outcomes(
        signals=signals,
        position_events=positions,
        strike_lookup=strike_lookup,
    )
    selected_signal_ids = {
        str(outcome["signal_id"])
        for outcome in outcomes
        if bool(outcome["closed"])
        and outcome["close_ts"] is not None
        and _in_range(outcome["close_ts"], start, end)
    }
    selected_signals = [
        signal for signal in signals if signal.id in selected_signal_ids
    ]
    selected_strike_ids = {signal.strike_id for signal in selected_signals}
    selected_strikes = [
        strike for strike in strikes if strike.id in selected_strike_ids
    ]
    selected_positions = [
        position for position in positions if position.signal_id in selected_signal_ids
    ]
    return build_summary(
        strikes=selected_strikes,
        signals=selected_signals,
        position_events=selected_positions,
    )


def _closed_outcomes_for_close_attribution(
    *,
    strikes: list[StrikeEvent],
    signals: list[SignalEvent],
    positions: list[PositionEvent],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> list[dict[str, Any]]:
    strike_lookup = {strike.id: strike for strike in strikes}
    outcomes = _compute_signal_outcomes(
        signals=signals,
        position_events=positions,
        strike_lookup=strike_lookup,
    )
    closed_outcomes = [
        row
        for row in outcomes
        if bool(row["closed"]) and row.get("close_ts") is not None
    ]
    if start is None or end is None:
        return closed_outcomes
    return [
        row
        for row in closed_outcomes
        if _in_range(row["close_ts"], start, end)
    ]


def _render_markdown_section(
    *,
    title: str,
    summary: dict[str, Any],
) -> list[str]:
    statistical_validation = summary.get("statistical_validation", {})
    production_readiness = (
        statistical_validation.get("production_readiness", {})
        if isinstance(statistical_validation, dict)
        else {}
    )
    ready_for_production = bool(production_readiness.get("ready_for_production", False))
    blocking_reasons = production_readiness.get("blocking_reasons", [])
    if not isinstance(blocking_reasons, list):
        blocking_reasons = []
    markdown: list[str] = [
        f"## {title}",
        f"- total_strikes: `{summary['total_strikes']}`",
        f"- total_signals: `{summary['total_signals']}`",
        f"- total_position_events: `{summary['total_position_events']}`",
        f"- closed_positions: `{summary['closed_positions']}`",
        f"- hit_rate: `{summary['hit_rate']:.4f}`",
        f"- statistical_ready_for_production: `{str(ready_for_production).lower()}`",
        "- statistical_blockers: `{}`".format(", ".join(blocking_reasons) if blocking_reasons else "none"),
        "",
        "### R Outcomes",
        f"- total_realized_r: `{summary['r_outcome']['total_realized_r']:.4f}`",
        f"- avg_realized_r: `{summary['r_outcome']['avg_realized_r']:.4f}`",
        f"- median_realized_r: `{summary['r_outcome']['median_realized_r']:.4f}`",
        f"- min_realized_r: `{summary['r_outcome']['min_realized_r']:.4f}`",
        f"- max_realized_r: `{summary['r_outcome']['max_realized_r']:.4f}`",
        "",
        "#### R Buckets",
    ]
    for bucket, count in summary["r_outcome"]["bucket_counts"].items():
        markdown.append(f"- `{bucket}`: `{count}`")

    markdown.append("")
    markdown.append("### Hit Rate By Signal Type")
    for row in summary["hit_rate_by_signal_type"]:
        markdown.append(
            "- `{}`: count=`{}`, hits=`{}`, hit_rate=`{:.4f}`".format(
                row["label"],
                row["count"],
                row["hits"],
                row["hit_rate"],
            )
        )

    markdown.append("")
    markdown.append("### Hit Rate By Side")
    for row in summary["hit_rate_by_side"]:
        markdown.append(
            "- `{}`: count=`{}`, hits=`{}`, hit_rate=`{:.4f}`".format(
                row["label"],
                row["count"],
                row["hits"],
                row["hit_rate"],
            )
        )

    markdown.append("")
    markdown.append("### Top Symbols")
    for symbol, count in summary["top_symbols"]:
        markdown.append(f"- `{symbol}`: `{count}`")

    markdown.append("")
    markdown.append("### Top Outfits")
    for outfit, count in summary["top_outfits"]:
        markdown.append(f"- `{outfit}`: `{count}`")

    markdown.append("")
    markdown.append("### Daily Close Summary")
    for row in summary["period_summary_daily"][:10]:
        markdown.append(
            "- `{}`: closed=`{}`, hit_rate=`{:.4f}`, avg_r=`{:.4f}`, total_r=`{:.4f}`".format(
                row["period"],
                row["closed_positions"],
                row["hit_rate"],
                row["avg_r"],
                row["total_r"],
            )
        )
    return markdown


def _render_academic_validation_appendix(
    *,
    academic_validation: dict[str, Any],
    execution_realism: dict[str, Any],
) -> list[str]:
    ready = bool(academic_validation.get("ready", False))
    blocking_reasons = academic_validation.get("blocking_reasons", [])
    if not isinstance(blocking_reasons, list):
        blocking_reasons = []

    output: list[str] = [
        "## Academic Validation Appendix",
        f"- academically_ready: `{str(ready).lower()}`",
        "- academic_blockers: `{}`".format(
            ", ".join(str(reason) for reason in blocking_reasons)
            if blocking_reasons
            else "none"
        ),
        f"- gate_scenario_id: `{academic_validation.get('gate_scenario_id', '')}`",
        f"- fold_count: `{academic_validation.get('fold_count', 0)}`",
        f"- min_fold_trade_count: `{academic_validation.get('min_fold_trade_count', 0)}`",
        f"- bootstrap_p_value: `{academic_validation.get('bootstrap_p_value', None)}`",
        "",
        "### Claim Scope (Statistical)",
    ]
    claim_scope = academic_validation.get("claim_scope", {})
    if not isinstance(claim_scope, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.claim_scope must be a dict"
        )
    output.extend(
        [
            f"- objective: `{claim_scope.get('objective', '')}`",
            f"- null_hypothesis: `{claim_scope.get('null_hypothesis', '')}`",
            f"- alternative_hypothesis: `{claim_scope.get('alternative_hypothesis', '')}`",
            f"- supports_causal_inference: `{claim_scope.get('supports_causal_inference', False)}`",
            "- causal_inference_statement: `{}`".format(
                claim_scope.get("causal_inference_statement", "")
            ),
            "",
            "### Walk-Forward Optimization (WFO)",
        ]
    )
    wfo_feasibility = academic_validation.get("wfo_feasibility", {})
    if not isinstance(wfo_feasibility, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.wfo_feasibility must be a dict"
        )
    output.extend(
        [
            f"- available_months: `{wfo_feasibility.get('available_months', 0)}`",
            "- required_months_for_min_folds: `{}`".format(
                wfo_feasibility.get("required_months_for_min_folds", 0)
            ),
            f"- max_feasible_folds: `{wfo_feasibility.get('max_feasible_folds', 0)}`",
            f"- is_feasible: `{wfo_feasibility.get('is_feasible', False)}`",
            "",
            "#### WFO Fold Table",
        ]
    )
    wfo_rows = academic_validation.get("wfo_folds", [])
    if not isinstance(wfo_rows, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.wfo_folds must be a list"
        )
    output.extend(
        _markdown_table(
            rows=wfo_rows,
            columns=[
                "fold_id",
                "train_start",
                "train_end",
                "test_start",
                "test_end",
                "closed_trades",
                "mean_r",
                "sharpe_annualized",
                "calmar_annualized",
                "min_trade_gate_pass",
            ],
        )
    )

    bootstrap_payload = academic_validation.get("bootstrap", {})
    if not isinstance(bootstrap_payload, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.bootstrap must be a dict"
        )
    output.extend(
        [
            "",
            "### Bootstrap Distribution",
            f"- method: `{bootstrap_payload.get('method', '')}`",
            f"- samples: `{bootstrap_payload.get('samples', 0)}`",
            f"- alpha: `{bootstrap_payload.get('alpha', 0.0)}`",
            "- ci: `{}`".format(bootstrap_payload.get("ci", None)),
            "- one_sided_p_value_mean_gt_zero: `{}`".format(
                bootstrap_payload.get("one_sided_p_value_mean_gt_zero", None)
            ),
            "",
            "#### Bootstrap Histogram Bins",
        ]
    )
    histogram_bins = bootstrap_payload.get("histogram_bins", [])
    if not isinstance(histogram_bins, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.bootstrap.histogram_bins must be a list"
        )
    output.extend(
        _markdown_table(
            rows=histogram_bins,
            columns=["bin_left", "bin_right", "count"],
        )
    )

    pvalues_payload = academic_validation.get("pvalues", {})
    if not isinstance(pvalues_payload, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.pvalues must be a dict"
        )
    output.extend(
        [
            "",
            "### P-Value and Multiple-Testing Summary",
            f"- method: `{pvalues_payload.get('method', '')}`",
            f"- qvalue_threshold: `{pvalues_payload.get('qvalue_threshold', None)}`",
            f"- all_pass: `{pvalues_payload.get('all_pass', False)}`",
            "",
        ]
    )
    pvalue_rows = pvalues_payload.get("rows", [])
    if not isinstance(pvalue_rows, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.pvalues.rows must be a list"
        )
    output.extend(
        _markdown_table(
            rows=pvalue_rows,
            columns=["label", "raw_p_value", "fdr_q_value", "pass_gate"],
        )
    )

    output.extend(
        [
            "",
            "### Execution Realism Sensitivity",
        ]
    )
    scenario_rows = execution_realism.get("scenario_table", [])
    if not isinstance(scenario_rows, list):
        raise RuntimeError(
            "Summary contract violation: execution_realism.scenario_table must be a list"
        )
    output.extend(
        _markdown_table(
            rows=scenario_rows,
            columns=[
                "scenario_id",
                "slippage_bps",
                "commission_bps",
                "latency_bars",
                "closed_positions",
                "avg_realized_r",
                "sharpe_annualized",
                "calmar_annualized",
            ],
        )
    )

    regime_payload = academic_validation.get("regime_stability", {})
    if not isinstance(regime_payload, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.regime_stability must be a dict"
        )
    output.extend(
        [
            "",
            "### Regime Stability",
            f"- proxy_symbol: `{regime_payload.get('proxy_symbol', '')}`",
            f"- proxy_month_count: `{regime_payload.get('proxy_month_count', 0)}`",
            f"- mapped_trade_month_count: `{regime_payload.get('mapped_trade_month_count', 0)}`",
            f"- missing_proxy_month_count: `{regime_payload.get('missing_proxy_month_count', 0)}`",
            f"- high_vol_count: `{regime_payload.get('high_vol_count', 0)}`",
            f"- low_vol_count: `{regime_payload.get('low_vol_count', 0)}`",
            f"- high_vol_mean_r: `{regime_payload.get('high_vol_mean_r', 0.0)}`",
            f"- low_vol_mean_r: `{regime_payload.get('low_vol_mean_r', 0.0)}`",
            f"- passes_requirement: `{regime_payload.get('passes_requirement', False)}`",
            "- blocking_reasons: `{}`".format(
                ", ".join(str(value) for value in regime_payload.get("blocking_reasons", []))
                if regime_payload.get("blocking_reasons")
                else "none"
            ),
            "",
            "### Citation Pack",
        ]
    )

    citation_payload = academic_validation.get("citation_pack", {})
    if not isinstance(citation_payload, dict):
        raise RuntimeError(
            "Summary contract violation: academic_validation.citation_pack must be a dict"
        )
    citations = citation_payload.get("entries", [])
    if not isinstance(citations, list):
        raise RuntimeError(
            "Summary contract violation: academic_validation.citation_pack.entries must be a list"
        )
    for row in citations:
        if not isinstance(row, dict):
            continue
        output.append(
            "- `{}` ({}) {} [{}]".format(
                row.get("id", ""),
                row.get("year", ""),
                row.get("title", ""),
                row.get("url", ""),
            )
        )
    return output


def _markdown_table(
    *,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> list[str]:
    if not rows:
        return ["- none"]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            "| "
            + " | ".join(_format_markdown_cell(row.get(column)) for column in columns)
            + " |"
        )
    return lines


def _format_markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value).replace("|", "\\|")


def _flatten_summary(
    payload: dict[str, Any],
    *,
    prefix: str = "",
    skip_keys: set[str] | None = None,
) -> dict[str, Any]:
    skip = skip_keys or set()
    flattened: dict[str, Any] = {}
    for key, value in payload.items():
        if key in skip:
            continue
        output_key = f"{prefix}{key}"
        if isinstance(value, (list, dict)):
            flattened[output_key] = str(value)
        else:
            flattened[output_key] = value
    return flattened


def _require_close_attribution(summary: dict[str, Any]) -> dict[str, Any]:
    close_payload = summary.get("close_attribution")
    if not isinstance(close_payload, dict):
        raise RuntimeError(
            "Summary contract violation: attribution_mode='both' requires "
            "dict close_attribution payload"
        )
    return close_payload


def _require_execution_realism(summary: dict[str, Any]) -> dict[str, Any]:
    payload = summary.get("execution_realism")
    if not isinstance(payload, dict):
        raise RuntimeError(
            "Summary contract violation: attribution_mode='both' requires "
            "dict execution_realism payload"
        )
    return payload


def _require_academic_validation(summary: dict[str, Any]) -> dict[str, Any]:
    payload = summary.get("academic_validation")
    if not isinstance(payload, dict):
        raise RuntimeError(
            "Summary contract violation: attribution_mode='both' requires "
            "dict academic_validation payload"
        )
    return payload


def _require_strike_attribution(summary: dict[str, Any]) -> dict[str, Any]:
    strike_payload = summary.get("strike_attribution")
    if not isinstance(strike_payload, dict):
        raise RuntimeError(
            "Summary contract violation: attribution_mode='both' requires "
            "dict strike_attribution payload"
        )
    return strike_payload


def _rate_breakdown(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        label = _require_breakdown_label(row=row, key=key, index=index)
        grouped[label].append(row)

    output: list[dict[str, Any]] = []
    for label, items in grouped.items():
        hits = sum(1 for item in items if float(item["realized_r"]) > 0.0)
        output.append(
            {
                "label": label,
                "count": len(items),
                "hits": hits,
                "hit_rate": (hits / len(items)) if items else 0.0,
            }
        )
    output.sort(key=lambda row: row["count"], reverse=True)
    return output


def _r_breakdown(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for index, row in enumerate(rows):
        label = _require_breakdown_label(row=row, key=key, index=index)
        grouped[label].append(float(row["realized_r"]))

    output: list[dict[str, Any]] = []
    for label, values in grouped.items():
        output.append(
            {
                "label": label,
                "count": len(values),
                "avg_r": (sum(values) / len(values)) if values else 0.0,
                "total_r": sum(values),
            }
        )
    output.sort(key=lambda row: row["count"], reverse=True)
    return output


def _r_bucket_counts(values: list[float]) -> dict[str, int]:
    buckets = {
        "<=-1R": 0,
        "-1R_to_0R": 0,
        "0R_to_1R": 0,
        "1R_to_3R": 0,
        ">=3R": 0,
    }
    for value in values:
        if value <= -1.0:
            buckets["<=-1R"] += 1
        elif value <= 0.0:
            buckets["-1R_to_0R"] += 1
        elif value < 1.0:
            buckets["0R_to_1R"] += 1
        elif value < 3.0:
            buckets["1R_to_3R"] += 1
        else:
            buckets[">=3R"] += 1
    return buckets


def _build_statistical_validation(
    *,
    closed_outcomes: list[dict[str, Any]],
    total_signals: int,
) -> dict[str, Any]:
    realized_r = [float(row["realized_r"]) for row in closed_outcomes]
    distribution = _distribution_summary(realized_r)
    risk_diagnostics = _risk_diagnostics(realized_r)
    uncertainty = _uncertainty_summary(realized_r)
    multiple_testing = _multiple_testing_summary(closed_outcomes)
    robustness = _robustness_summary(closed_outcomes)

    minimum_closed_positions = 30
    blockers: list[str] = []
    if len(realized_r) < minimum_closed_positions:
        blockers.append(
            "closed_positions_below_minimum:{}<{}".format(
                len(realized_r),
                minimum_closed_positions,
            )
        )
    ci = uncertainty.get("bootstrap_mean_r_ci_95")
    if isinstance(ci, dict):
        lower = float(ci.get("lower", 0.0))
        if lower <= 0.0:
            blockers.append("bootstrap_ci_includes_non_positive_edge")
    else:
        blockers.append("bootstrap_ci_unavailable")

    p_value = uncertainty.get("one_sided_p_value_mean_gt_zero")
    if isinstance(p_value, float) and p_value > 0.05:
        blockers.append("mean_return_not_significant_at_0.05")
    if not isinstance(p_value, float):
        blockers.append("hypothesis_test_unavailable")

    effect_size = uncertainty.get("cohen_d")
    if isinstance(effect_size, float) and effect_size < 0.2:
        blockers.append("effect_size_below_small_threshold")
    if not isinstance(effect_size, float):
        blockers.append("effect_size_unavailable")

    return {
        "sample_size": {
            "closed_positions": len(realized_r),
            "total_signals": total_signals,
            "signal_to_close_ratio": (len(realized_r) / total_signals) if total_signals else 0.0,
        },
        "distribution": distribution,
        "risk_diagnostics": risk_diagnostics,
        "uncertainty": uncertainty,
        "multiple_testing_control": multiple_testing,
        "robustness_checks": robustness,
        "production_readiness": {
            "ready_for_production": not blockers,
            "minimum_closed_positions": minimum_closed_positions,
            "blocking_reasons": blockers,
        },
    }


def _distribution_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "median": 0.0,
            "std": 0.0,
            "skew": 0.0,
            "kurtosis": 0.0,
            "win_rate": 0.0,
            "payoff_ratio": 0.0,
            "expectancy": 0.0,
        }
    series = pd.Series(values, dtype="float64")
    gains = [value for value in values if value > 0]
    losses = [abs(value) for value in values if value < 0]
    payoff_ratio = (float(np.mean(gains)) / float(np.mean(losses))) if gains and losses else 0.0
    win_rate = len(gains) / len(values)
    return {
        "count": int(series.shape[0]),
        "mean": float(series.mean()),
        "median": float(series.median()),
        "std": float(series.std(ddof=1)) if len(values) > 1 else 0.0,
        "skew": float(series.skew()) if len(values) > 2 else 0.0,
        "kurtosis": float(series.kurt()) if len(values) > 3 else 0.0,
        "win_rate": win_rate,
        "payoff_ratio": payoff_ratio,
        "expectancy": float(series.mean()),
    }


def _risk_diagnostics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "max_drawdown_r": 0.0,
            "ulcer_index_r": 0.0,
            "max_time_under_water_bars": 0,
            "sharpe_annualized": 0.0,
            "sortino_annualized": 0.0,
            "annualization_assumption": "252 closed positions per year",
            "turnover_proxy_positions_per_month": 0.0,
        }
    samples = np.array(values, dtype=float)
    equity = np.cumsum(samples)
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity - peaks
    max_drawdown = float(drawdowns.min()) if drawdowns.size else 0.0
    ulcer_index = float(math.sqrt(float(np.mean(np.square(drawdowns))))) if drawdowns.size else 0.0
    max_tuw = _max_time_under_water(drawdowns.tolist())

    mean_value = float(np.mean(samples))
    std_value = float(np.std(samples, ddof=1)) if samples.size > 1 else 0.0
    downside = samples[samples < 0.0]
    downside_std = float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
    annual_factor = math.sqrt(252.0)
    sharpe = (mean_value / std_value) * annual_factor if std_value > 0 else 0.0
    sortino = (mean_value / downside_std) * annual_factor if downside_std > 0 else 0.0
    turnover_proxy = (len(values) / 12.0) if values else 0.0

    return {
        "max_drawdown_r": max_drawdown,
        "ulcer_index_r": ulcer_index,
        "max_time_under_water_bars": max_tuw,
        "sharpe_annualized": sharpe,
        "sortino_annualized": sortino,
        "annualization_assumption": "252 closed positions per year",
        "turnover_proxy_positions_per_month": turnover_proxy,
    }


def _max_time_under_water(drawdowns: list[float]) -> int:
    max_streak = 0
    streak = 0
    for value in drawdowns:
        if value < 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0
    return max_streak


def _uncertainty_summary(values: list[float]) -> dict[str, Any]:
    ci = _bootstrap_mean_ci(values)
    test = _one_sided_mean_test(values)
    return {
        "bootstrap_mean_r_ci_95": ci,
        "one_sided_p_value_mean_gt_zero": test["p_value"],
        "test_statistic": test["test_statistic"],
        "null_hypothesis": "mean(realized_r) <= 0",
        "alternative_hypothesis": "mean(realized_r) > 0",
        "cohen_d": test["cohen_d"],
    }


def _bootstrap_mean_ci(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    rng = np.random.default_rng(42)
    samples = np.array(values, dtype=float)
    n = samples.size
    if n == 1:
        mean_value = float(samples[0])
        return {"lower": mean_value, "upper": mean_value}
    boot_means = np.empty(2000, dtype=float)
    for index in range(boot_means.size):
        draw = rng.choice(samples, size=n, replace=True)
        boot_means[index] = float(np.mean(draw))
    return {
        "lower": float(np.quantile(boot_means, 0.025)),
        "upper": float(np.quantile(boot_means, 0.975)),
    }


def _one_sided_mean_test(values: list[float]) -> dict[str, float | None]:
    if len(values) < 2:
        return {"test_statistic": None, "p_value": None, "cohen_d": None}
    samples = np.array(values, dtype=float)
    mean_value = float(np.mean(samples))
    std_value = float(np.std(samples, ddof=1))
    if std_value <= 0:
        p_value = 0.0 if mean_value > 0 else 1.0
        return {"test_statistic": None, "p_value": p_value, "cohen_d": None}
    t_stat = mean_value / (std_value / math.sqrt(float(len(samples))))
    p_value = 1.0 - _normal_cdf(t_stat)
    effect_size = mean_value / std_value
    return {"test_statistic": float(t_stat), "p_value": float(p_value), "cohen_d": float(effect_size)}


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _multiple_testing_summary(closed_outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in closed_outcomes:
        grouped[str(row["signal_type"])].append(float(row["realized_r"]))
    raw: list[tuple[str, float]] = []
    for label, values in grouped.items():
        test = _one_sided_mean_test(values)
        p_value = test["p_value"]
        if isinstance(p_value, float):
            raw.append((label, p_value))
    adjusted = _fdr_bh(raw)
    details = [
        {
            "label": label,
            "raw_p_value": p_value,
            "fdr_q_value": adjusted.get(label),
        }
        for label, p_value in sorted(raw, key=lambda item: item[0])
    ]
    return {
        "method": "Benjamini-Hochberg FDR",
        "tests": details,
    }


def _fdr_bh(values: list[tuple[str, float]]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values, key=lambda item: item[1])
    m = len(ordered)
    raw_q: list[float] = []
    for rank, (_label, p_value) in enumerate(ordered, start=1):
        raw_q.append(min(1.0, p_value * m / rank))
    adjusted_q = raw_q[:]
    for index in range(m - 2, -1, -1):
        adjusted_q[index] = min(adjusted_q[index], adjusted_q[index + 1])
    return {
        ordered[index][0]: float(adjusted_q[index])
        for index in range(m)
    }


def _robustness_summary(closed_outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_rows: dict[str, list[float]] = defaultdict(list)
    timeframe_rows: dict[str, list[float]] = defaultdict(list)
    monthly_rows: dict[str, list[float]] = defaultdict(list)
    for row in closed_outcomes:
        value = float(row["realized_r"])
        symbol_rows[str(row["symbol"])].append(value)
        timeframe_rows[str(row["timeframe"])].append(value)
        close_ts = row.get("close_ts")
        if close_ts is not None:
            label = ensure_utc_timestamp(str(close_ts)).strftime("%Y-%m")
            monthly_rows[label].append(value)
    return {
        "symbol_stability": _group_stability(symbol_rows),
        "timeframe_stability": _group_stability(timeframe_rows),
        "monthly_regimes": _group_stability(monthly_rows),
        "outlier_stress": _outlier_stress([float(row["realized_r"]) for row in closed_outcomes]),
    }


def _group_stability(rows: dict[str, list[float]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for label in sorted(rows.keys()):
        values = rows[label]
        output.append(
            {
                "label": label,
                "count": len(values),
                "mean_r": float(np.mean(values)) if values else 0.0,
                "std_r": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "hit_rate": (sum(1 for value in values if value > 0) / len(values))
                if values
                else 0.0,
            }
        )
    return output


def _outlier_stress(values: list[float]) -> dict[str, Any]:
    if len(values) < 3:
        return {
            "base_mean_r": float(np.mean(values)) if values else 0.0,
            "trimmed_mean_r": None,
            "removed_values": [],
        }
    ordered = sorted(values)
    trimmed = ordered[1:-1]
    return {
        "base_mean_r": float(np.mean(values)),
        "trimmed_mean_r": float(np.mean(trimmed)),
        "removed_values": [ordered[0], ordered[-1]],
    }


def _period_summary(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for index, row in enumerate(rows):
        if "close_ts" not in row:
            raise RuntimeError(
                "Signal outcome contract violation: "
                f"row[{index}] missing required key 'close_ts'"
            )
        close_ts = row["close_ts"]
        if close_ts is None:
            raise RuntimeError(
                "Signal outcome contract violation: "
                f"row[{index}] has null close_ts for closed outcome "
                f"(signal_id={row.get('signal_id')})"
            )
        ts = ensure_utc_timestamp(str(close_ts))
        if period == "daily":
            label = ts.strftime("%Y-%m-%d")
        elif period == "monthly":
            label = ts.strftime("%Y-%m")
        else:
            raise ValueError(f"Unsupported period summary '{period}'")
        grouped[label].append(float(row["realized_r"]))

    output: list[dict[str, Any]] = []
    for label in sorted(grouped.keys()):
        values = grouped[label]
        hits = sum(1 for value in values if value > 0.0)
        output.append(
            {
                "period": label,
                "closed_positions": len(values),
                "hit_rate": (hits / len(values)) if values else 0.0,
                "avg_r": (sum(values) / len(values)) if values else 0.0,
                "total_r": sum(values),
            }
        )
    return output


def _record_to_strike(row: dict[str, Any]) -> StrikeEvent:
    return StrikeEvent(
        id=str(row["id"]),
        symbol=str(row["symbol"]),
        timeframe=str(row["timeframe"]),
        outfit_id=str(row["outfit_id"]),
        period=int(row["period"]),
        sma_value=float(row["sma_value"]),
        bar_ts=ensure_utc_timestamp(str(row["bar_ts"])).to_pydatetime(),
        tolerance=float(row["tolerance"]),
        trigger_mode=str(row["trigger_mode"]),
    )


def _record_to_signal(row: dict[str, Any]) -> SignalEvent:
    return SignalEvent(
        id=str(row["id"]),
        strike_id=str(row["strike_id"]),
        route_id=str(row["route_id"]),
        side=str(row["side"]),  # type: ignore[arg-type]
        signal_type=str(row["signal_type"]),  # type: ignore[arg-type]
        entry=float(row["entry"]),
        stop=float(row["stop"]),
        confidence=str(row["confidence"]),
        session_type=str(row["session_type"]),  # type: ignore[arg-type]
    )


def _record_to_position(row: dict[str, Any]) -> PositionEvent:
    return PositionEvent(
        id=str(row["id"]),
        signal_id=str(row["signal_id"]),
        action=str(row["action"]),
        qty=float(row["qty"]),
        price=float(row["price"]),
        reason=str(row["reason"]),
        ts=ensure_utc_timestamp(str(row["ts"])).to_pydatetime(),
    )


def _in_range(value: Any, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    ts = ensure_utc_timestamp(value if isinstance(value, pd.Timestamp) else str(value))
    return bool(start <= ts <= end)


def _require_signal_strike(
    signal: SignalEvent,
    strike_lookup: dict[str, StrikeEvent],
) -> StrikeEvent:
    strike = strike_lookup.get(signal.strike_id)
    if strike is None:
        raise RuntimeError(
            "Signal-to-strike link violation: "
            f"signal_id={signal.id} references missing strike_id={signal.strike_id}"
        )
    return strike


def _require_breakdown_label(
    row: dict[str, Any],
    key: str,
    index: int,
) -> str:
    if key not in row:
        raise RuntimeError(
            "Summary breakdown contract violation: "
            f"row[{index}] missing required key '{key}'"
        )
    value = row[key]
    if not isinstance(value, str) or not value:
        raise RuntimeError(
            "Summary breakdown contract violation: "
            f"row[{index}] key '{key}' must be non-empty string, got {value!r}"
        )
    return value
