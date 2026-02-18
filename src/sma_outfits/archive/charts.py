from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd
import plotly.graph_objects as go

from sma_outfits.events import SignalEvent, StrikeEvent


def write_signal_chart(
    bars: pd.DataFrame,
    strike: StrikeEvent,
    signal: SignalEvent,
    outfit_periods: Sequence[int],
    output_path: Path,
) -> Path:
    if bars.empty:
        raise ValueError("Cannot render chart from empty bars")

    frame = bars.copy()
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    frame = frame.sort_values("ts")
    for period in outfit_periods:
        frame[f"ma_{period}"] = frame["close"].rolling(period, min_periods=period).mean()

    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=frame["ts"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="OHLC",
        )
    )

    colors = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02"]
    for index, period in enumerate(outfit_periods):
        column = f"ma_{period}"
        figure.add_trace(
            go.Scatter(
                x=frame["ts"],
                y=frame[column],
                mode="lines",
                line={"width": 1.5, "color": colors[index % len(colors)]},
                name=f"MA{period}",
            )
        )

    figure.add_hline(
        y=strike.sma_value,
        line_color="#ef4444",
        line_width=1.5,
        line_dash="dash",
    )
    figure.add_annotation(
        x=frame["ts"].iloc[-1],
        y=strike.sma_value,
        text=f"{signal.signal_type} @ {strike.sma_value:.2f}",
        showarrow=True,
        arrowhead=2,
        font={"size": 12},
    )
    figure.update_layout(
        title=f"{strike.symbol} {strike.timeframe} {signal.signal_type}",
        xaxis_title="Timestamp (UTC)",
        yaxis_title="Price",
        template="plotly_white",
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h"},
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_image(str(output_path), width=1400, height=800, scale=2)
    return output_path
