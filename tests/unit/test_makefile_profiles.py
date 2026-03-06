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
    assert (
        "$(eval PIPE_COMMAND := make run ACTION=e2e CONFIG_PROFILE=$(CONFIG_PROFILE))"
        in makefile
    )


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
    assert (
        "PROFILE='max_common' requires DISCOVER_RANGE_OUTPUT with full_range_start. "
        "Run: make run ACTION=discover-range CONFIG_PROFILE=$(CONFIG_PROFILE) "
        "UNIVERSE=all TIMEFRAME_SET=all"
    ) in makefile
    assert "PROFILE_START := $(COMMON_ANALYSIS_START)" in makefile
    assert "Use: smoke, day, week, month, max, max_common, custom" in makefile


def test_makefile_exposes_only_streamlined_public_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert ".PHONY: help setup run qa clean" in makefile
    assert "MODE ?= install## help: Setup mode selector (install|venv)." in makefile
    assert "ACTION ?= e2e## help: Run action selector " in makefile
    assert "SUITE ?= full## help: QA suite selector (full|part2|dead-code|all)." in makefile
    assert "SCOPE ?= default## help: Clean scope selector (default|all)." in makefile
    assert "VALID_MODES := install venv" in makefile
    assert (
        "VALID_ACTIONS := e2e validate-config discover-range verify-readiness "
        "backfill replay report run-live migrate-storage-layout "
        "paper-hardening-init phase2-preflight preflight-storage phase1-close"
    ) in makefile
    assert "VALID_SUITES := full part2 dead-code all" in makefile
    assert "VALID_SCOPES := default all" in makefile
    assert "setup: ## Create/repair .venv, enforce Python 3.14.3, and optionally install deps." in makefile
    assert "run: ## Run the primary workflow selected by ACTION." in makefile
    assert "qa: ## Run the QA suite selected by SUITE." in makefile
    assert (
        "clean: ## Remove artifacts, caches, and build outputs; use SCOPE=all "
        "to also remove .venv."
    ) in makefile


def test_makefile_removes_legacy_public_target_definitions() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    legacy_public_targets = [
        "venv: ##",
        "install: ",
        "validate-config:",
        "discover-range:",
        "verify-readiness:",
        "paper-hardening-init:",
        "phase2-preflight:",
        "test-part2-components:",
        "test: ",
        "dead-code-check:",
        "backfill:",
        "replay:",
        "run-live:",
        "report:",
        "migrate-storage-layout:",
        "preflight-storage:",
        "e2e:",
        "phase1-close:",
        "clean-all:",
    ]

    for target in legacy_public_targets:
        assert f"\n{target}" not in makefile


def test_makefile_preserves_phase2_and_phase1_dispatch_paths() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "READINESS_ROOT ?= artifacts/readiness/$(CONFIG_PROFILE)" in makefile
    assert (
        "DISCOVER_RANGE_OUTPUT ?= $(READINESS_ROOT)/discovered_range_manifest.json"
        in makefile
    )
    assert (
        "READINESS_ACCEPTANCE_OUTPUT ?= $(READINESS_ROOT)/readiness_acceptance.json"
        in makefile
    )
    assert "PAPER_HARDENING_INIT_OUTPUT ?=" in makefile
    assert (
        "PAPER_HARDENING_INIT_OUTPUT ?= $(READINESS_ROOT)/paper_hardening_init.json"
        in makefile
    )
    assert "PART2_TEST_PATHS ?=" in makefile
    assert "tests/unit/test_cli_paper_hardening_init.py" in makefile
    assert "RUN_LIVE_ARGS ?=" in makefile
    assert "_run_paper-hardening-init:" in makefile
    assert "_qa_part2:" in makefile
    assert "_run_phase2-preflight:" in makefile
    assert "$(MAKE) _run_paper-hardening-init" in makefile
    assert "$(MAKE) _qa_part2" in makefile
    assert "-m sma_outfits.cli paper-hardening-init --config $(ACTIVE_CONFIG)" in makefile
    assert "-m sma_outfits.cli run-live --config $(ACTIVE_CONFIG) $(RUN_LIVE_ARGS)" in makefile
    assert "_run_phase1-close:" in makefile
    assert "powershell -NoProfile -File scripts/phase1_close.ps1" in makefile
    assert "-MakeCommand \"$(MAKE)\"" in makefile
    assert "-ArchiveRoot \"$(PHASE1_CLOSE_ARCHIVE_ROOT)\"" in makefile


def test_makefile_dispatch_rules_match_bootstrap_and_qa_contracts() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "$(if $(filter $(ACTION),preflight-storage),,$(MAKE) setup MODE=install)"
        in makefile
    )
    assert "$(MAKE) _run_$(ACTION)" in makefile
    assert "$(MAKE) setup MODE=install" in makefile
    assert "$(MAKE) _qa_$(SUITE)" in makefile
    assert "_qa_all:" in makefile
    assert "$(MAKE) _qa_full" in makefile
    assert "$(MAKE) _qa_dead-code" in makefile


def test_makefile_help_examples_match_grouped_interface() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "'make run'" in makefile
    assert "'make setup MODE=venv'" in makefile
    assert (
        "make run ACTION=verify-readiness CONFIG_PROFILE=context "
        "START=$$env:FULL_RANGE_START END=$(READINESS_END) "
        "UNIVERSE=all_stocks TIMEFRAME_SET=all"
    ) in makefile
    assert (
        "make run ACTION=run-live CONFIG_PROFILE=context "
        "RUN_LIVE_ARGS=''--runtime-minutes 30 --lookback-hours 8''"
    ) in makefile
    assert "'make qa SUITE=dead-code'" in makefile
    assert "'make clean SCOPE=all'" in makefile


def test_makefile_readiness_outputs_are_profile_isolated_by_default() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "READINESS_ROOT ?= artifacts/readiness/$(CONFIG_PROFILE)"
        "## help: Profile-isolated readiness artifact root."
    ) in makefile
    assert "$(DISCOVER_RANGE_OUTPUT)" in makefile
    assert "$(READINESS_ACCEPTANCE_OUTPUT)" in makefile
    assert "$(PAPER_HARDENING_INIT_OUTPUT)" in makefile


def test_makefile_pytest_cache_preflight_is_enforced() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "define run_pytest_preflight" in makefile
    assert ".pytest_cache exists but is not a directory" in makefile
    assert "$$probe = '.pytest_cache\\\\.write_probe'" in makefile
    assert "_qa_part2:" in makefile
    assert "_qa_full:" in makefile
    assert "$(call run_pytest_preflight)" in makefile
