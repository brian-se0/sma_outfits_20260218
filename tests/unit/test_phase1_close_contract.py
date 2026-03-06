from __future__ import annotations

from pathlib import Path


def test_phase1_close_script_enumerates_only_strict_and_context() -> None:
    script = Path("scripts/phase1_close.ps1").read_text(encoding="utf-8")

    assert '$profiles = @("strict", "context")' in script
    assert '$passes = @("iso1", "iso2")' in script
    assert '"CONFIG_PROFILE=$profileName"' in script
    assert '"verify-readiness"' in script
    assert (
        '"artifacts/readiness/readiness_acceptance_${profileName}_${OutputLabel}_${pass}.json"'
        in script
    )
    assert '"replication"' not in script
