from __future__ import annotations

from pathlib import Path

import pandas as pd

from sma_outfits.events import SignalEvent, StrikeEvent


def append_thread_markdown(
    root: Path,
    strike: StrikeEvent,
    signal: SignalEvent,
    chart_path: Path,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    date_key = pd.Timestamp(strike.bar_ts).tz_convert("America/New_York").strftime("%Y-%m-%d")
    markdown_path = root / f"{date_key}.md"
    block = (
        f"### {signal.signal_type} | {strike.symbol} | {strike.timeframe}\n"
        f"- signal_id: `{signal.id}`\n"
        f"- strike_id: `{strike.id}`\n"
        f"- side: `{signal.side}`\n"
        f"- entry: `{signal.entry:.2f}`\n"
        f"- stop: `{signal.stop:.2f}`\n"
        f"- outfit: `{strike.outfit_id}`\n"
        f"- sma_period: `{strike.period}`\n"
        f"- sma_value: `{strike.sma_value:.2f}`\n"
        f"- chart: `{chart_path.as_posix()}`\n\n"
    )
    with markdown_path.open("a", encoding="utf-8") as handle:
        handle.write(block)
    return markdown_path
