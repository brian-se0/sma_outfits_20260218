from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from sma_outfits.events import PositionEvent, SignalEvent, StrikeEvent
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
        strike = strike_lookup.get(signal.strike_id)
        if strike is None:
            continue
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
                if outcome.get("close_reason")
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
    }
    return summary


def build_summary_from_records(
    strike_rows: list[dict[str, Any]],
    signal_rows: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> dict[str, Any]:
    strikes = [_record_to_strike(row) for row in strike_rows]
    signals = [_record_to_signal(row) for row in signal_rows]
    positions = [_record_to_position(row) for row in position_rows]

    if start is not None and end is not None:
        strikes = [strike for strike in strikes if _in_range(strike.bar_ts, start, end)]
        allowed_strikes = {strike.id for strike in strikes}
        signals = [signal for signal in signals if signal.strike_id in allowed_strikes]
        allowed_signals = {signal.id for signal in signals}
        positions = [
            position
            for position in positions
            if _in_range(position.ts, start, end)
            and position.signal_id in allowed_signals
        ]

    return build_summary(strikes=strikes, signals=signals, position_events=positions)


def write_summary_report(
    summary: dict[str, Any],
    root: Path,
    label: str,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    markdown_path = root / f"{label}.md"
    csv_path = root / f"{label}.csv"

    markdown: list[str] = [
        f"# Replay Summary: {label}",
        "",
        f"- total_strikes: `{summary['total_strikes']}`",
        f"- total_signals: `{summary['total_signals']}`",
        f"- total_position_events: `{summary['total_position_events']}`",
        f"- closed_positions: `{summary['closed_positions']}`",
        f"- hit_rate: `{summary['hit_rate']:.4f}`",
        "",
        "## R Outcomes",
        f"- total_realized_r: `{summary['r_outcome']['total_realized_r']:.4f}`",
        f"- avg_realized_r: `{summary['r_outcome']['avg_realized_r']:.4f}`",
        f"- median_realized_r: `{summary['r_outcome']['median_realized_r']:.4f}`",
        f"- min_realized_r: `{summary['r_outcome']['min_realized_r']:.4f}`",
        f"- max_realized_r: `{summary['r_outcome']['max_realized_r']:.4f}`",
        "",
        "### R Buckets",
    ]
    for bucket, count in summary["r_outcome"]["bucket_counts"].items():
        markdown.append(f"- `{bucket}`: `{count}`")

    markdown.append("")
    markdown.append("## Hit Rate By Signal Type")
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
    markdown.append("## Hit Rate By Side")
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
    markdown.append("## Top Symbols")
    for symbol, count in summary["top_symbols"]:
        markdown.append(f"- `{symbol}`: `{count}`")

    markdown.append("")
    markdown.append("## Top Outfits")
    for outfit, count in summary["top_outfits"]:
        markdown.append(f"- `{outfit}`: `{count}`")

    markdown.append("")
    markdown.append("## Daily Close Summary")
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

    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")

    flattened = {
        key: value if not isinstance(value, (list, dict)) else str(value)
        for key, value in summary.items()
    }
    pd.DataFrame([flattened]).to_csv(csv_path, index=False)
    return markdown_path, csv_path


def records_to_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [asdict(row) if hasattr(row, "__dict__") else row for row in rows]


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
        for event in events:
            if event.action in {"partial_take", "close"}:
                realized_r += (
                    float(event.qty)
                    * direction
                    * ((float(event.price) - signal.entry) / risk_unit)
                )
            if event.action == "close":
                closed = True
                close_reason = event.reason
                close_ts = event.ts

        strike = strike_lookup.get(signal.strike_id)
        outcomes.append(
            {
                "signal_id": signal.id,
                "signal_type": signal.signal_type,
                "side": signal.side,
                "symbol": strike.symbol if strike else "UNKNOWN",
                "outfit_id": strike.outfit_id if strike else "UNKNOWN",
                "timeframe": strike.timeframe if strike else "UNKNOWN",
                "realized_r": realized_r,
                "closed": closed,
                "close_reason": close_reason,
                "close_ts": close_ts,
            }
        )
    return outcomes


def _rate_breakdown(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key, "UNKNOWN"))].append(row)

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
    for row in rows:
        grouped[str(row.get(key, "UNKNOWN"))].append(float(row["realized_r"]))

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


def _period_summary(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        close_ts = row.get("close_ts")
        if close_ts is None:
            continue
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
