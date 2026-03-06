from __future__ import annotations

from pathlib import Path


def test_makefile_uses_two_profile_active_config_mapping() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "STRICT_CONFIG_PATH ?= "
        "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"
    ) in makefile
    assert (
        "CONTEXT_CONFIG_PATH ?= "
        "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"
    ) in makefile
    assert (
        "CONFIG_PROFILE ?= context## help: Config profile selector (strict|context)."
    ) in makefile
    assert "ifeq ($(CONFIG_PROFILE),strict)" in makefile
    assert "ACTIVE_CONFIG := $(STRICT_CONFIG_PATH)" in makefile
    assert "else ifeq ($(CONFIG_PROFILE),context)" in makefile
    assert "ACTIVE_CONFIG := $(CONTEXT_CONFIG_PATH)" in makefile
    assert "REPLICATION_CONFIG_PATH ?=" not in makefile
    assert "else ifeq ($(CONFIG_PROFILE),replication)" not in makefile
    assert (
        "$(error Unsupported CONFIG_PROFILE='$(CONFIG_PROFILE)'. Use: strict, context)"
    ) in makefile
    assert "CONFIG_PROFILE=replication" not in makefile
    assert "$(eval PIPE_CONFIG := $(ACTIVE_CONFIG))" in makefile
    assert "$(eval PIPE_COMMAND := make e2e CONFIG_PROFILE=$(CONFIG_PROFILE))" in makefile


def test_makefile_removes_lane_interface_artifacts() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "CONFIG ?=" not in makefile
    assert "lane:" not in makefile
    assert "make lane" not in makefile
    assert "LANE ?=" not in makefile
    assert "LANE_" not in makefile
    assert "--config $(ACTIVE_CONFIG)" in makefile


def test_makefile_supports_max_common_profile() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "PROFILE ?= smoke## help: Range profile "
        "(smoke|day|week|month|max|max_common|custom)."
    ) in makefile
    assert "else ifeq ($(PROFILE),max_common)" in makefile
    assert "PROFILE='max_common' requires DISCOVER_RANGE_OUTPUT with full_range_start." in makefile
    assert "PROFILE_START := $(COMMON_ANALYSIS_START)" in makefile
    assert "Use: smoke, day, week, month, max, max_common, custom" in makefile


def test_makefile_exposes_part2_hardening_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "PAPER_HARDENING_INIT_OUTPUT ?=" in makefile
    assert "PART2_TEST_PATHS ?=" in makefile
    assert "RUN_LIVE_ARGS ?=" in makefile
    assert "paper-hardening-init: install ##" in makefile
    assert "phase2-preflight: ## Generate Part-2 hardening manifest and run component gate." in makefile
    assert "test-part2-components: install ##" in makefile
    assert "-m sma_outfits.cli paper-hardening-init --config $(ACTIVE_CONFIG)" in makefile
    assert "$(MAKE) paper-hardening-init" in makefile
    assert "$(MAKE) test-part2-components" in makefile
    assert "-m sma_outfits.cli run-live --config $(ACTIVE_CONFIG) $(RUN_LIVE_ARGS)" in makefile


def test_makefile_exposes_phase1_close_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "PHASE1_CLOSE_PROFILE ?= custom" in makefile
    assert "PHASE1_CLOSE_START ?= 2022-03-31T15:30:00Z" in makefile
    assert "PHASE1_CLOSE_END ?= 2026-02-28T23:16:28Z" in makefile
    assert "PHASE1_CLOSE_SYMBOLS ?= QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY" in makefile
    assert "PHASE1_CLOSE_TIMEFRAMES ?= 30m,1h" in makefile
    assert "PHASE1_CLOSE_STAGES ?= validate-config,backfill,replay,report" in makefile
    assert "PHASE1_CLOSE_OUTPUT ?= artifacts/readiness/phase1_recheck_acceptance.json" in makefile
    assert "PHASE1_CLOSE_LABEL ?= phase1recheck" in makefile
    assert "PHASE1_CLOSE_ARCHIVE_ROOT ?= audit/phase1_rechecks" in makefile
    assert (
        "phase1-close: ## Run isolated 2-profile closure protocol twice and verify deterministic readiness."
    ) in makefile
    assert ".PHONY:" in makefile
    assert " phase1-close " in makefile
    assert "powershell -NoProfile -File scripts/phase1_close.ps1" in makefile
    assert "-MakeCommand \"$(MAKE)\"" in makefile
    assert "-ArchiveRoot \"$(PHASE1_CLOSE_ARCHIVE_ROOT)\"" in makefile


def test_makefile_help_examples_match_two_profile_contract() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "make verify-readiness CONFIG_PROFILE=context START=$$env:FULL_RANGE_START "
        "END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all"
    ) in makefile
    assert (
        "make run-live CONFIG_PROFILE=context "
        "RUN_LIVE_ARGS=''--runtime-minutes 30 --lookback-hours 8''"
    ) in makefile
    assert "CONFIG_PROFILE=replication" not in makefile


def test_makefile_registers_phase2_preflight_as_phony_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert ".PHONY:" in makefile
    assert " phase2-preflight " in makefile


def test_makefile_pytest_cache_preflight_is_enforced() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "define run_pytest_preflight" in makefile
    assert ".pytest_cache exists but is not a directory" in makefile
    assert "$$probe = '.pytest_cache\\\\.write_probe'" in makefile
    assert "test-part2-components: install ##" in makefile
    assert "test: install ## Run full test suite." in makefile
    assert "$(call run_pytest_preflight)" in makefile
