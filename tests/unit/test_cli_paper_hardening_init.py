from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sma_outfits import cli
from sma_outfits.config.models import load_settings


def _context_settings(env_file: Path):
    return load_settings(
        config_path=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"),
        env_path=env_file,
    )


def test_build_paper_hardening_init_payload_exposes_known_capabilities(env_file: Path) -> None:
    settings = _context_settings(env_file)
    payload = cli._build_paper_hardening_init_payload(
        settings=settings,
        config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"),
    )

    assert payload["status"] == "ok"
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["state_persistence_enabled"] is True
    assert capabilities["reconciliation_enabled"] is True
    assert capabilities["broker_order_submission_enabled"] is False
    assert capabilities["fill_callback_processing_enabled"] is False
    assert capabilities["drawdown_alerting_enabled"] is False

    blocking_gaps = payload["blocking_gaps"]
    assert isinstance(blocking_gaps, list)
    ids = {row["id"] for row in blocking_gaps}
    assert "reconciliation_disabled" not in ids
    assert "missing_broker_order_submission" in ids
    assert "missing_fill_callback_processing" in ids
    assert "missing_drawdown_alerting" in ids
    assert (
        payload["next_commands"][0]
        == "make run ACTION=phase2-preflight CONFIG_PROFILE=context"
    )


def test_paper_hardening_init_writes_manifest_and_hash(
    env_file: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = _context_settings(env_file)
    monkeypatch.setattr(cli, "assert_python_runtime", lambda: None)
    monkeypatch.setattr(cli, "_load_runtime_settings", lambda _config: settings)

    output_path = tmp_path / "paper_hardening_init.json"
    cli.paper_hardening_init(
        config=Path("configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml"),
        output=output_path,
    )

    assert output_path.exists()
    hash_path = output_path.with_suffix(output_path.suffix + ".sha256")
    assert hash_path.exists()
    digest = hash_path.read_text(encoding="utf-8").strip().split()[0]
    assert digest == hashlib.sha256(output_path.read_bytes()).hexdigest()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert "next_commands" in payload
    assert payload["next_commands"]
    assert payload["capabilities"]["reconciliation_enabled"] is True
    assert (
        "make run ACTION=verify-readiness CONFIG_PROFILE=context "
        "START=<full_range_start> END=<readiness_end> "
        "UNIVERSE=all TIMEFRAME_SET=all"
        in payload["next_commands"]
    )
    assert (
        "make run ACTION=phase2-preflight CONFIG_PROFILE=context"
        in payload["next_commands"]
    )
