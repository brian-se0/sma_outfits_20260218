from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from sma_outfits.events import PositionEvent, SignalEvent, StrikeEvent


def build_summary(
    strikes: list[StrikeEvent],
    signals: list[SignalEvent],
    position_events: list[PositionEvent],
) -> dict[str, Any]:
    closes = [event for event in position_events if event.action == "close"]
    wins = [
        event
        for event in closes
        if event.reason in {"+3R_final_take", "risk_migration_cut"}
    ]

    symbol_counter: Counter[str] = Counter()
    outfit_counter: Counter[str] = Counter()
    strike_lookup = {strike.id: strike for strike in strikes}
    for signal in signals:
        strike = strike_lookup.get(signal.strike_id)
        if strike:
            symbol_counter[strike.symbol] += 1
            outfit_counter[strike.outfit_id] += 1

    summary = {
        "total_strikes": len(strikes),
        "total_signals": len(signals),
        "total_position_events": len(position_events),
        "closed_positions": len(closes),
        "win_rate": (len(wins) / len(closes)) if closes else 0.0,
        "top_symbols": symbol_counter.most_common(5),
        "top_outfits": outfit_counter.most_common(5),
    }
    return summary


def write_summary_report(
    summary: dict[str, Any],
    root: Path,
    label: str,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    markdown_path = root / f"{label}.md"
    csv_path = root / f"{label}.csv"

    markdown = [
        f"# Replay Summary: {label}",
        "",
        f"- total_strikes: `{summary['total_strikes']}`",
        f"- total_signals: `{summary['total_signals']}`",
        f"- total_position_events: `{summary['total_position_events']}`",
        f"- closed_positions: `{summary['closed_positions']}`",
        f"- win_rate: `{summary['win_rate']:.4f}`",
        "",
        "## Top Symbols",
    ]
    for symbol, count in summary["top_symbols"]:
        markdown.append(f"- `{symbol}`: `{count}`")
    markdown.append("")
    markdown.append("## Top Outfits")
    for outfit, count in summary["top_outfits"]:
        markdown.append(f"- `{outfit}`: `{count}`")
    markdown_path.write_text("\n".join(markdown) + "\n", encoding="utf-8")

    flattened = {
        key: value if not isinstance(value, list) else str(value)
        for key, value in summary.items()
    }
    pd.DataFrame([flattened]).to_csv(csv_path, index=False)
    return markdown_path, csv_path


def records_to_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [asdict(row) if hasattr(row, "__dict__") else row for row in rows]
