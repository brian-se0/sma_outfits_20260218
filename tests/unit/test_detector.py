from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from sma_outfits.events import BarEvent, SMAState
from sma_outfits.signals.classifier import SignalClassifier
from sma_outfits.signals.detector import OutfitDefinition, StrikeDetector, load_outfits


def _bar(close: float, low: float, high: float, minute: int) -> BarEvent:
    ts = datetime(2025, 1, 2, 15, minute, tzinfo=timezone.utc)
    return BarEvent(
        symbol="SPY",
        timeframe="1m",
        ts=ts,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1000,
        source="unit-test",
    )


def test_strike_detection_exact_near_and_miss() -> None:
    outfit = OutfitDefinition(
        outfit_id="test",
        periods=(10,),
        description="test",
        source_configuration="10",
    )
    detector = StrikeDetector(
        outfits=[outfit],
        tolerance=0.01,
        classifier=SignalClassifier(),
    )
    history = pd.DataFrame({"close": [100.0] * 30, "high": [100.1] * 30, "low": [99.9] * 30})

    exact_bar = _bar(close=100.0, low=99.95, high=100.05, minute=0)
    exact_state = {10: SMAState("SPY", "1m", 10, 100.0, exact_bar.ts)}
    strikes, _ = detector.detect(exact_bar, exact_state, history)
    assert len(strikes) == 1

    near_bar = _bar(close=100.0, low=99.95, high=100.0, minute=1)
    near_state = {10: SMAState("SPY", "1m", 10, 100.009, near_bar.ts)}
    strikes, _ = detector.detect(near_bar, near_state, history)
    assert len(strikes) == 1

    miss_bar = _bar(close=100.0, low=99.95, high=100.0, minute=2)
    miss_state = {10: SMAState("SPY", "1m", 10, 100.011, miss_bar.ts)}
    strikes, _ = detector.detect(miss_bar, miss_state, history)
    assert len(strikes) == 0


def test_side_assignment_long_and_short() -> None:
    outfit = OutfitDefinition(
        outfit_id="test",
        periods=(20,),
        description="test",
        source_configuration="20",
    )
    detector = StrikeDetector(outfits=[outfit], tolerance=0.01, classifier=SignalClassifier())
    history = pd.DataFrame({"close": [100.0] * 40, "high": [100.2] * 40, "low": [99.8] * 40})

    long_bar = _bar(close=101.0, low=99.9, high=101.1, minute=10)
    long_state = {20: SMAState("SPY", "1m", 20, 100.5, long_bar.ts)}
    _, signals = detector.detect(long_bar, long_state, history)
    assert signals[0].side == "LONG"

    short_bar = _bar(close=99.0, low=98.9, high=100.0, minute=11)
    short_state = {20: SMAState("SPY", "1m", 20, 99.5, short_bar.ts)}
    _, signals = detector.detect(short_bar, short_state, history)
    assert signals[0].side == "SHORT"


def test_load_outfits_rejects_missing_required_keys(tmp_path) -> None:
    path = tmp_path / "outfits.yaml"
    path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test",
                "    periods: [10, 20]",
                "    source_configuration: test",
                "    source_ambiguous: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required keys"):
        load_outfits(path)


def test_load_outfits_accepts_complete_ambiguous_row(tmp_path) -> None:
    path = tmp_path / "outfits.yaml"
    path.write_text(
        "\n".join(
            [
                "outfits:",
                "  - id: test",
                "    periods: [10, 20]",
                "    description: ambiguous but complete",
                "    source_configuration: test",
                "    source_ambiguous: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    outfits = load_outfits(path)
    assert len(outfits) == 1
    assert outfits[0].source_ambiguous is True
