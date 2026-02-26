from __future__ import annotations

import pytest

from sma_outfits.execution import resolve_execution_pairs


def test_resolve_execution_pairs_replay_ignores_out_of_scope_requested_values(
    settings,
) -> None:
    pairs = resolve_execution_pairs(
        settings=settings,
        symbols=["QQQ", "SMH"],
        timeframes=["1h", "1m"],
        command="replay",
    )

    assert pairs == [("QQQ", "1h")]


def test_resolve_execution_pairs_run_live_rejects_out_of_scope_requested_values(
    settings,
) -> None:
    with pytest.raises(RuntimeError, match="requested values outside configured strict routes"):
        resolve_execution_pairs(
            settings=settings,
            symbols=["QQQ", "SMH"],
            timeframes=["1h", "1m"],
            command="run-live",
        )


def test_resolve_execution_pairs_replay_fails_when_nothing_matches_routes(
    settings,
) -> None:
    with pytest.raises(RuntimeError, match="do not match any configured route"):
        resolve_execution_pairs(
            settings=settings,
            symbols=["SMH"],
            timeframes=["1m"],
            command="replay",
        )
