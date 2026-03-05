# Phase 1 Completion Plan (Post-Mixed Removal, All-3 Strict Gate)

## Summary
Current state after deleting `mixed_trigger` config:
1. Repo has one intentional tracked deletion: `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_mixed_trigger_v1.yaml`.
2. `make test` currently fails in 3 tests due stale mixed-config references.
3. `make verify-readiness` passes for `strict` and `context` on the current artifact set.
4. `make verify-readiness` fails for `replication` (`fdr_qvalue_gate_failed`).
5. You chose:
- All 3 profiles must pass Phase 1 gate.
- Full removal of mixed/mixed_trigger aliases.
- Replication thresholds must match strict.
- Replication strategy composition should converge to context.

## Important Public Interface Changes
1. `Makefile` profile interface:
- Remove `mixed` and `mixed_trigger` as accepted `CONFIG_PROFILE` values.
- Remove `MIXED_CONFIG_PATH` and `MIXED_TRIGGER_CONFIG_PATH` variables.
- `CONFIG_PROFILE` allowed values become only: `strict`, `context`, `replication`.

2. Documentation interface:
- Remove all user-facing commands/examples mentioning `CONFIG_PROFILE=mixed` or `mixed_trigger`.
- Update profile contract language to state full removal (not alias deprecation).

3. Config set contract:
- Canonical config files remain exactly three:
  - `settings..._v1.yaml` (strict)
  - `settings..._context_v1.yaml`
  - `settings..._replication_v1.yaml`
- Replication config is aligned to strict gating and route composition.

## Implementation Plan

### 1. Remove mixed/mixed_trigger support completely
1. Edit `Makefile`:
- Delete `MIXED_CONFIG_PATH` and `MIXED_TRIGGER_CONFIG_PATH`.
- Delete `else ifeq ($(CONFIG_PROFILE),mixed)` and `mixed_trigger` branches.
- Update unsupported-profile error text and help text to list only `strict|context|replication`.

2. Edit docs:
- `README.md`: remove alias statements and mixed example commands.
- `make_commands.md`: remove `MIXED_CONFIG_PATH` from target flag tables and notes.
- `ASSUMPTIONS.md`: replace alias language with final profile contract.
- `EofPh1.md`: update wording where mixed aliases are referenced as active compatibility.

3. Update tests:
- `tests/unit/test_config_inventory.py`: expected configs list must contain only 3 YAMLs.
- Remove `tests/unit/test_mixed_trigger_profile_config.py` entirely.
- `tests/unit/test_makefile_replication_lane.py`: remove mixed-branch assertions and update expected error/help strings.

4. Consistency sweep:
- Run `rg` check for stale file/path references to deleted mixed config and mixed profile aliases.

### 2. Converge replication strategy to context/strict and harmonize academic gates
1. Edit `configs/settings..._replication_v1.yaml`:
- Set `validation.wfo.min_closed_trades_per_fold` to `14`.
- Set `validation.significance.fdr_qvalue_max` to `0.05`.
- Keep `method: fdr_bh`.
- Converge route composition to match context (same route IDs, sides, signal families, and cross-symbol refs), per your selected approach.

2. Keep strict/context config thresholds unchanged:
- `min_closed_trades_per_fold: 14`
- `fdr_qvalue_max: 0.05`

3. Ensure profile identity remains by file name/profile only, not by divergent strategy behavior.

### 3. Run fixed-window, fixed-scope validation protocol (pre-registered)
Use identical scope/window for all three:
- `START=2022-03-31T15:30:00Z`
- `END=2026-02-28T23:16:28Z`
- `SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY`
- `TIMEFRAMES=30m,1h`
- `PROFILE=custom`

Commands:
```powershell
make clean

make e2e CONFIG_PROFILE=strict PROFILE=custom START=2022-03-31T15:30:00Z END=2026-02-28T23:16:28Z SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY TIMEFRAMES=30m,1h
make verify-readiness CONFIG_PROFILE=strict PROFILE=custom START=2022-03-31T15:30:00Z END=2026-02-28T23:16:28Z SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY TIMEFRAMES=30m,1h READINESS_ACCEPTANCE_OUTPUT=artifacts/readiness/readiness_acceptance_strict_phase1close.json

make e2e CONFIG_PROFILE=context PROFILE=custom START=2022-03-31T15:30:00Z END=2026-02-28T23:16:28Z SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY TIMEFRAMES=30m,1h
make verify-readiness CONFIG_PROFILE=context PROFILE=custom START=2022-03-31T15:30:00Z END=2026-02-28T23:16:28Z SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY TIMEFRAMES=30m,1h READINESS_ACCEPTANCE_OUTPUT=artifacts/readiness/readiness_acceptance_context_phase1close.json

make e2e CONFIG_PROFILE=replication PROFILE=custom START=2022-03-31T15:30:00Z END=2026-02-28T23:16:28Z SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY TIMEFRAMES=30m,1h
make verify-readiness CONFIG_PROFILE=replication PROFILE=custom START=2022-03-31T15:30:00Z END=2026-02-28T23:16:28Z SYMBOLS=QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY TIMEFRAMES=30m,1h READINESS_ACCEPTANCE_OUTPUT=artifacts/readiness/readiness_acceptance_replication_phase1close.json
```

### 4. Decide Phase 1 completion
Pass only if all three readiness manifests show:
1. `status = ok`
2. `academic_validation.ready = true`
3. `academic_validation.blocking_reasons = []`
4. `fdr_summary.max_q_value <= 0.05`
5. `min_fold_trade_count >= 14`
6. Boundary/gap checks clean (`boundary_failures_count=0`, `gap_quality_failures_count=0`)

If any profile fails:
1. Do not change statistical thresholds.
2. Do not reintroduce mixed profiles.
3. Apply one pre-registered composition adjustment set and repeat the 3-profile protocol once.

## Test Cases and Scenarios
1. Unit/contract:
- `make test` must pass after mixed-removal refactor.
- `make validate-config CONFIG_PROFILE=strict`
- `make validate-config CONFIG_PROFILE=context`
- `make validate-config CONFIG_PROFILE=replication`

2. Profile-selection contract:
- Invalid profile (e.g., `CONFIG_PROFILE=mixed`) hard-fails with updated error text.
- `CONFIG_PROFILE=context|strict|replication` resolves correctly.

3. Statistical gate scenario:
- Verify each profile independently with its own e2e+readiness outputs (no cross-profile artifact reuse assumptions).

## Assumptions and Defaults
1. Phase 2 remains blocked until all three profiles pass strict gates.
2. Statistical standards are fixed and not negotiable in this cycle (`fdr_qvalue_max=0.05`, `min_closed_trades_per_fold=14`).
3. Scope/window are fixed to the values above for comparability and anti-p-hacking discipline.
4. Mixed/mixed_trigger are fully removed from supported interfaces in this cycle.
5. Replication lane is retained as a profile identity for reproducibility checks, but strategy composition is converged to context per your decision.
