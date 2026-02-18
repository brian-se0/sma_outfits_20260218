from __future__ import annotations

import pandas as pd


def compute_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["high"]
    low = frame["low"]
    close = frame["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period, min_periods=period).mean()


def local_drawdown_flag(closes: pd.Series, lookback: int = 20) -> bool:
    if len(closes) < lookback + 1:
        return False
    prior_window = closes.iloc[-(lookback + 1) : -1]
    prior_close = closes.iloc[-2]
    current_close = closes.iloc[-1]
    return bool(prior_close < prior_window.median() and current_close >= prior_close)


def volatility_percentile(
    frame: pd.DataFrame,
    atr_window: int = 14,
    percentile_window: int = 100,
) -> float:
    atr = compute_atr(frame, period=atr_window).dropna()
    if len(atr) < percentile_window:
        return 0.0
    recent = atr.iloc[-percentile_window:]
    current = recent.iloc[-1]
    return float((recent <= current).mean() * 100.0)


class SignalClassifier:
    def __init__(
        self,
        volatility_threshold: float = 75.0,
        drawdown_window: int = 20,
        atr_window: int = 14,
        volatility_window: int = 100,
    ) -> None:
        self.volatility_threshold = volatility_threshold
        self.drawdown_window = drawdown_window
        self.atr_window = atr_window
        self.volatility_window = volatility_window

    def classify(
        self,
        side: str,
        history: pd.DataFrame,
        stop_breached: bool = False,
    ) -> str:
        if stop_breached:
            return "singular_point_hard_stop"
        if side == "SHORT":
            return "automated_short"
        closes = history["close"] if "close" in history.columns else pd.Series(dtype=float)
        if local_drawdown_flag(closes, lookback=self.drawdown_window):
            return "precision_buy"
        percentile = volatility_percentile(
            history,
            atr_window=self.atr_window,
            percentile_window=self.volatility_window,
        )
        if percentile >= self.volatility_threshold:
            return "optimized_buy"
        return "precision_buy"
