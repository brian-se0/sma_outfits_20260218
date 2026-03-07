from __future__ import annotations

import json
from pathlib import Path


def test_pair_batch_script_runs_sequential_make_steps_and_records_failures() -> None:
    script = Path("scripts/pair_batch.ps1").read_text(encoding="utf-8")

    assert '[string]$ManifestPath' in script
    assert '[string]$OutputPath' in script
    assert '[string]$FailOnAny = "false"' in script
    assert "ACTION=discover-range" in script
    assert "ACTION=e2e" in script
    assert "ACTION=verify-readiness" in script
    assert "Get-LatestRunManifestPath" in script
    assert "resolved_windows" in script
    assert "analysis_start" in script
    assert "analysis_end" in script
    assert 'pair-batch: start id=' in script
    assert 'pair-batch: failed id=' in script
    assert 'completed_with_failures' in script
    assert 'pair-batch acceptance failed:' in script


def test_default_pair_batch_manifest_tracks_qqq_1h_contract() -> None:
    payload = json.loads(
        Path("configs/pairs/context/batch_manifest.json").read_text(encoding="utf-8")
    )

    assert list(payload) == ["pairs"]
    assert len(payload["pairs"]) == 1

    entry = payload["pairs"][0]
    assert entry["id"] == "qqq_1h"
    assert entry["config_profile"] == "context"
    assert entry["config_path"] == "configs/pairs/context/qqq_1h.yaml"
    assert entry["archive_root"] == "artifacts/pairs/qqq_1h/context"
    assert entry["readiness_root"] == "artifacts/readiness/pairs/qqq_1h"
    assert entry["discover_symbols"] == "QQQ,VIXY"
    assert entry["backfill_symbols"] == "QQQ,VIXY"
    assert entry["replay_symbols"] == "QQQ"
    assert entry["verify_symbols"] == "QQQ"
    assert entry["verify_readiness_args"] == "--require-academic-validation"
