from __future__ import annotations

from pathlib import Path


def test_makefile_has_replication_lane_plumbing() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "lane: install ## Run validation lane workflow (LANE=strict|replication)." in makefile
    assert "_lane-strict:" not in makefile
    assert "_lane-replication:" not in makefile
    assert "LANE_REPLICATION_CONFIG ?=" in makefile
    assert "LANE_REPLICATION_SYMBOLS ?= QQQ,SPY,TQQQ,SQQQ,SVIX,VIXY,XLF,SMH,SOXL" in makefile
    assert "LANE_REPLICATION_TIMEFRAMES ?=" in makefile
    assert "LANE_REPLICATION_DISCOVER_OUTPUT ?=" in makefile
    assert "LANE_REPLICATION_END ?=" in makefile
    assert "LANE_REPLICATION_END_RESOLVED" not in makefile
    assert "LANE_REPLICATION_END must be set for lane replication" in makefile
    assert "$(PYTHON) -m sma_outfits.cli discover-range --config $(LANE_REPLICATION_CONFIG)" in makefile
    assert "$(MAKE) e2e CONFIG=$(LANE_STRICT_CONFIG)" not in makefile
    assert "$(MAKE) e2e CONFIG=$(LANE_REPLICATION_CONFIG) PROFILE=custom" not in makefile
    assert "$(eval PIPE_CONFIG := $(LANE_STRICT_CONFIG))" in makefile
    assert "$(eval PIPE_CONFIG := $(LANE_REPLICATION_CONFIG))" in makefile
    assert "$(call run_pipeline)" in makefile
    assert "$(PYTHON) -m sma_outfits.cli verify-readiness --config $(LANE_REPLICATION_CONFIG)" in makefile
    assert "$(PYTHON) -m sma_outfits.cli verify-readiness --config $(LANE_STRICT_CONFIG)" in makefile
