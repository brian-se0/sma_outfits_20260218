from __future__ import annotations

from pathlib import Path


def test_makefile_uses_profile_based_active_config_mapping() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert (
        "STRICT_CONFIG_PATH ?= "
        "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml"
    ) in makefile
    assert (
        "REPLICATION_CONFIG_PATH ?= "
        "configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml"
    ) in makefile
    assert "CONFIG_PROFILE ?= strict" in makefile
    assert "ifeq ($(CONFIG_PROFILE),strict)" in makefile
    assert "ACTIVE_CONFIG := $(STRICT_CONFIG_PATH)" in makefile
    assert "else ifeq ($(CONFIG_PROFILE),replication)" in makefile
    assert "ACTIVE_CONFIG := $(REPLICATION_CONFIG_PATH)" in makefile
    assert "$(error Unsupported CONFIG_PROFILE='$(CONFIG_PROFILE)'. Use: strict, replication)" in makefile
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
