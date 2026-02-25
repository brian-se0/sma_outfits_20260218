from __future__ import annotations

from pathlib import Path


def test_config_directory_contains_only_canonical_profiles() -> None:
    config_dir = Path("configs")
    yaml_names = sorted(path.name for path in config_dir.glob("*.yaml"))

    assert yaml_names == [
        "settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml",
        "settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml",
    ]
