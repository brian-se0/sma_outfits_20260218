from __future__ import annotations

from pathlib import Path


def test_makefile_has_replication_lane_plumbing() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "prove-edge-replication:" in makefile
    assert "REPLICATION_CONFIG ?=" in makefile
    assert "REPLICATION_SYMBOLS ?= QQQ,SPY,TQQQ,SQQQ,SVIX,VIXY,XLF,SMH,SOXL" in makefile
    assert "REPLICATION_TIMEFRAMES ?=" in makefile
    assert "REPLICATION_DISCOVER_OUTPUT ?=" in makefile
    assert "$(MAKE) discover-range CONFIG=$(REPLICATION_CONFIG)" in makefile
    assert "$(MAKE) e2e CONFIG=$(REPLICATION_CONFIG) PROFILE=custom" in makefile
    assert "$(MAKE) verify-readiness CONFIG=$(REPLICATION_CONFIG)" in makefile
