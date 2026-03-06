# Historical Note

This plan reflects a superseded three-profile model that treated `replication` as an active runtime lane. It is preserved for audit history only. As of 2026-03-06, the current runtime contract supports only `strict` and `context`; see `Phase2_PLAN.md` for the current forward plan.

# Implementation Plan: Freeze Production Candidate + Enforce Lane Immutability + Complete Live-Paper Ops Gate

## Summary
This plan completes items 1-4 in order, using the decisions you selected:

1. Freeze replication config first as an immutable production-candidate source.
2. Enforce strict/replication immutability with dedicated lane roots (no shared artifacts/events/storage).
3. Finish Part 2 by hardening the existing live pipeline (streaming/state/reconciliation already exist) with missing controls: risk caps + stronger operational telemetry.
4. Run a bounded 14-trading-day paper validation with explicit balanced pass/fail gates before live escalation.

Key decisions locked:
- Lane layout: dedicated roots.
- State backend: keep JSON state (hardened).
- Paper window: 14 trading days.
- Gate profile: balanced ops gate.
- Order scope this cycle: no Alpaca order submission yet (reconciliation/risk/ops first).

## Current Ground Truth (from repo)
1. `run-live` already exists with websocket streaming, reconnect logic, restart-safe JSON state, and reconciliation counters.
2. Strict and replication currently share the same roots (`archive.root`, `storage_root`, `events_root`) in both configs, so overwrite/collision is possible.
3. `readiness_acceptance.json` is shared by default and can be overwritten.
4. No explicit daily/live risk caps are implemented yet.
5. No bounded paper-window verifier exists yet.

## Phase 1: Freeze Replication Config as Immutable Production Candidate

### Objective
Create a cryptographically locked config artifact that is never edited in-place.

### Implementation
1. Add a new CLI command in [src/sma_outfits/cli.py](d:\sma_outfits_20260218\src\sma_outfits\cli.py): `freeze-config`.
2. `freeze-config` behavior:
   - input: `--source-config`, `--output-config`, optional `--label`.
   - fail if output exists.
   - copy source bytes exactly.
   - write `<output-config>.sha256`.
   - write lock metadata JSON (source path, source hash, output hash, UTC timestamp, git SHA).
3. Add Make target in [Makefile](d:\sma_outfits_20260218\Makefile): `freeze-replication-config`.
4. Write candidate to: `configs/settings.production_candidate_YYYYMMDD.yaml`.
5. Document command in [make_commands.md](d:\sma_outfits_20260218\make_commands.md).

### Acceptance Criteria
1. Candidate config exists and hash sidecar exists.
2. Lock metadata exists and includes git SHA + timestamp.
3. Re-running freeze to same output fails fast.

---

## Phase 2: Fix Artifact/Run Immutability (Strict vs Replication Cannot Overwrite Each Other)

### Objective
Guarantee physical separation of strict lane and replication lane outputs.

### Implementation
1. Create lane runtime configs (new files):
   - `configs/settings.strict_runtime_v1.yaml`
   - `configs/settings.replication_runtime_v1.yaml`
   - `configs/settings.production_runtime_YYYYMMDD.yaml`
2. Keep strategy/risk/validation logic unchanged from source lane configs; only change roots:
   - strict root base: `artifacts/lanes/strict/svix211_106`
   - replication root base: `artifacts/lanes/replication/svix211_106`
   - production root base: `artifacts/lanes/production/svix211_106`
3. In each runtime config set:
   - `archive.root`
   - `storage_root`
   - `events_root`
4. Update [Makefile](d:\sma_outfits_20260218\Makefile):
   - `LANE_STRICT_CONFIG` default -> strict runtime config.
   - `LANE_REPLICATION_CONFIG` default -> replication runtime config.
   - add `PRODUCTION_CONFIG` default -> production runtime config.
   - set strict readiness/discovery outputs under `artifacts/readiness/strict/...`.
   - set replication readiness/discovery outputs under `artifacts/readiness/replication/...`.
5. Keep existing baseline configs untouched for backward compatibility.
6. Update docs in [README.md](d:\sma_outfits_20260218\README.md) and [make_commands.md](d:\sma_outfits_20260218\make_commands.md) with lane-specific artifact paths.

### Acceptance Criteria
1. A strict run and replication run produce disjoint file trees under `artifacts/lanes/strict/...` and `artifacts/lanes/replication/...`.
2. No shared `events/*.jsonl`, `reports/*`, or `runs/*/run_manifest.json` between lanes.
3. `verify-readiness` for each lane points to its lane-specific run manifest and artifacts only.

---

## Phase 3: Implement Part 2 Live-Paper Infrastructure Gaps

### Objective
Harden existing live infrastructure with operational controls needed for reliable paper operation.

### Scope in this cycle
1. Keep existing signal/position live engine.
2. Do not add Alpaca order submission yet.
3. Add risk caps + stronger reconciliation control + stronger telemetry/manifesting.

### Implementation

#### 3.1 Config/API additions
1. Extend `LiveConfig` in [src/sma_outfits/config/models.py](d:\sma_outfits_20260218\src\sma_outfits\config\models.py) with:
   - `risk_caps_enabled: bool = true`
   - `max_open_positions: int | null = 10`
   - `max_new_entries_per_day: int | null = 100`
   - `max_daily_realized_loss_r: float | null = 10.0`
   - `halt_on_risk_cap_breach: bool = true`
   - `max_consecutive_reconciliation_mismatches: int | null = 3`
2. Add validators for positive/range constraints and null semantics.

#### 3.2 LiveRunner hardening
1. In [src/sma_outfits/live/runner.py](d:\sma_outfits_20260218\src\sma_outfits\live\runner.py):
   - track per-session-day counters:
     - new entries count,
     - open positions count,
     - realized PnL in R,
     - consecutive reconciliation mismatches.
2. Enforce caps before opening new positions.
3. On breach:
   - emit risk alert,
   - persist to `events/risk_alerts.jsonl`,
   - halt run when `halt_on_risk_cap_breach=true`.
4. Strengthen reconciliation:
   - persist each reconciliation snapshot to `events/reconciliation.jsonl`,
   - enforce `max_consecutive_reconciliation_mismatches` if configured.
5. Persist new counters into live state payload so restart resumes limits correctly.
6. Extend progress payload and final result summary with:
   - `risk_cap_breaches`,
   - `consecutive_reconciliation_mismatches_max`,
   - `risk_halt_triggered`.

#### 3.3 CLI and Make orchestration for paper ops
1. Extend `run-live` in [src/sma_outfits/cli.py](d:\sma_outfits_20260218\src\sma_outfits\cli.py):
   - add `--manifest-output` to persist run summary JSON (+ `.sha256`).
2. Add Make targets in [Makefile](d:\sma_outfits_20260218\Makefile):
   - `init-live-paper`: validate config + print effective live controls.
   - `run-paper-session`: run one session with manifest output.
   - `verify-paper-window`: evaluate bounded window.
3. Update [make_commands.md](d:\sma_outfits_20260218\make_commands.md) with target contract and required artifacts.

### Acceptance Criteria
1. Risk cap breach is observable, persisted, and halts as configured.
2. Restart retains counters and prevents duplicate signal replay.
3. Reconciliation snapshots and mismatch counts persist as artifacts.
4. `run-live --manifest-output` writes deterministic manifest + hash.

---

## Phase 4: Bounded 14-Trading-Day Paper Validation with Explicit Pass/Fail

### Objective
Create an auditable operational gate before any live escalation.

### Implementation
1. Add CLI command `verify-paper-window` in [src/sma_outfits/cli.py](d:\sma_outfits_20260218\src\sma_outfits\cli.py).
2. Inputs:
   - `--config`
   - `--window-trading-days` (default `14`)
   - `--manifest-glob` (session manifests)
   - optional thresholds (defaults = balanced gate)
   - `--output` path
3. Output:
   - `paper_window_validation.json`
   - `paper_window_validation.json.sha256`
4. Gate evaluation defaults (balanced):
   - zero crashed sessions,
   - aggregate uptime `>= 99.5%`,
   - reconciliation mismatch rate `<= 1%`,
   - no risk-cap breach,
   - zero state-recovery failures,
   - no unresolved blocker list.
5. Add Make target:
   - `paper-validate-window` (calls `verify-paper-window`).

### Pass/Fail Definition (Operational)
1. `PASS`: all balanced gate conditions true.
2. `FAIL`: any condition false; output must include explicit blocker IDs and evidence paths.

---

## Public Interfaces / Types / Commands Affected

### Config interface
1. `live.*` adds risk-cap and reconciliation-threshold fields.

### CLI interface
1. New command: `freeze-config`.
2. `run-live` adds `--manifest-output`.
3. New command: `verify-paper-window`.

### Make interface
1. New targets: `freeze-replication-config`, `init-live-paper`, `run-paper-session`, `paper-validate-window`.
2. `lane` strict/replication defaults updated to lane runtime configs and lane-specific readiness outputs.

### Artifact contract additions
1. `events/risk_alerts.jsonl`
2. `events/reconciliation.jsonl`
3. `live run manifest` JSON + hash
4. `paper window validation` JSON + hash

---

## Test Plan

### Unit tests
1. Extend config validation tests in [tests/unit/test_config.py](d:\sma_outfits_20260218\tests\unit\test_config.py) for new `live.*` fields.
2. Add CLI tests in [tests/unit/test_cli_readiness.py](d:\sma_outfits_20260218\tests\unit\test_cli_readiness.py) for:
   - `freeze-config` output/hash/metadata,
   - `run-live --manifest-output`,
   - `verify-paper-window` pass/fail logic.
3. Add Makefile assertions in [tests/unit/test_makefile_replication_lane.py](d:\sma_outfits_20260218\tests\unit\test_makefile_replication_lane.py) for new lane defaults/targets.

### Integration tests
1. Extend [tests/integration/test_live_pipeline_mocked.py](d:\sma_outfits_20260218\tests\integration\test_live_pipeline_mocked.py):
   - risk-cap breach halt,
   - reconciliation consecutive mismatch threshold halt,
   - restart preserves live-state counters,
   - manifest emission.
2. Add integration for lane separation:
   - strict runtime config writes only strict lane roots,
   - replication runtime config writes only replication lane roots.

### Acceptance scenario tests
1. Simulate 14-session manifest set and verify balanced gate pass/fail deterministically.
2. Ensure failing condition produces blocker list with artifact pointers.

---

## Rollout Order (Implementation Sequence)
1. Phase 1 (freeze) and tests.
2. Phase 2 (lane immutability) and tests.
3. Phase 3 (live hardening) and tests.
4. Phase 4 (window gate) and tests.
5. Documentation update.
6. Final dry validation commands:
   - `make validate-config` for strict/replication/production runtime configs.
   - `make test`.

---

## Assumptions and Defaults
1. No Alpaca paper order submission in this cycle.
2. Strategy logic remains unchanged; this cycle is operational hardening and artifact isolation.
3. JSON live state remains the persistence backend.
4. Bounded validation window is 14 trading days.
5. Balanced operational gate thresholds are the default release gate.
