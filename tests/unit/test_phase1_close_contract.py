from __future__ import annotations

from pathlib import Path


def test_phase1_close_script_enumerates_only_strict_and_context() -> None:
    script = Path("scripts/phase1_close.ps1").read_text(encoding="utf-8")

    assert '$profiles = @("strict", "context")' in script
    assert '$passes = @("iso1", "iso2")' in script
    assert '"run"' in script
    assert '"ACTION=e2e"' in script
    assert '"CONFIG_PROFILE=$profileName"' in script
    assert '"ACTION=verify-readiness"' in script
    assert (
        '"artifacts/readiness/${profileName}/readiness_acceptance_${OutputLabel}_${pass}.json"'
        in script
    )
    assert 'command               = "make run ACTION=phase1-close"' in script
    assert '"replication"' not in script
