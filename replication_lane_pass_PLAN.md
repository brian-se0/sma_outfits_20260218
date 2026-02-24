# Replication-Lane Pass Plan (Using Only Agreed Grok Elements)

## Summary
This plan keeps the strict lane untouched and applies only replication-lane changes that we agreed with:
1. include SOXL in replication execution and validation scope,
2. add a new SOXL 2h route gated by SMH 2h bullish context,
3. extend replication hold window to `risk.timeout_bars: 240`,
4. use a staged fallback to `min_closed_trades_per_fold: 7` only if Stage 1 fails solely on trades-per-fold.

The goal is to increase fold trade counts and improve quality without invalid schema keys or unsupported Make stages/profiles.

## Implementation Steps
1. Update replication config in `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`.
2. Update replication orchestration defaults in `Makefile`.
3. Update docs to keep command defaults and lane behavior explicit.
4. Run Stage 1 verification.
5. Conditionally run Stage 2 fallback if criteria match exactly.

## Decision-Complete Spec

### 1) Replication Config Changes (Stage 1)
1. In `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`, change `validation.scope_symbols` to include `SOXL`.
2. In the same file, set `risk.timeout_bars: 240`.
3. Add a new route `soxl_2h_author` with schema-valid keys and values:
   - `id: soxl_2h_author`
   - `symbol: SOXL`
   - `timeframe: 2h`
   - `outfit_id: warings_problem`
   - `key_period: 548`
   - `micro_periods: [19, 37, 73, 143, 279]`
   - `side: LONG`
   - `signal_type: magnetized_buy`
   - `macro_gate: none`
   - `risk_mode: penny_reference_break`
   - `stop_offset: 0.01`
   - `dynamic_reference_migration: true`
   - `confluence.enabled: true`
   - `confluence.min_outfit_alignment_count: 2`
   - `confluence.volume_lookback_bars: 20`
   - `confluence.volume_spike_ratio: 1.2`
   - `cross_symbol_context.enabled: true`
   - `cross_symbol_context.rules[0].reference_route_id: smh_2h_author`
   - `cross_symbol_context.rules[0].require_macro_positive: true`
   - `cross_symbol_context.rules[0].require_micro_positive: true`
4. Keep existing `soxl_30m_author` unchanged for Stage 1.

### 2) Makefile Changes
1. In `Makefile`, update `REPLICATION_SYMBOLS` default to include `SOXL`.
2. Keep `REPLICATION_TIMEFRAMES` as `30m,1h,2h`.
3. Do not change strict-lane variables or target behavior.
4. If help text enumerates replication symbols, update it to match the new default.

### 3) Docs Changes
1. Update `make_commands.md` replication defaults so `REPLICATION_SYMBOLS` includes `SOXL`.
2. Update any replication-lane command examples that currently omit `SOXL`.

## Stage Execution and Acceptance

### Stage 1 Run
1. `make validate-config CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`
2. `make prove-edge-replication`

### Stage 1 Pass Criteria
1. `artifacts/readiness/readiness_acceptance.json` has `academic_validation.ready = true`.
2. No blockers for:
   - `wfo_min_closed_trades_per_fold_violation`
   - `oos_sharpe_below_threshold`
   - `fdr_qvalue_gate_failed`
3. `replication.score >= 0.70` remains satisfied.

### Stage 2 Fallback Trigger
Apply Stage 2 only if Stage 1 fails and the only remaining blocker is trades-per-fold (`wfo_min_closed_trades_per_fold_violation`) while Sharpe/FDR/regime/replication-score gates are already passing.

### Stage 2 Fallback Change
1. In `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`, change:
   - `validation.wfo.min_closed_trades_per_fold: 10 -> 7`
2. Re-run:
   - `make prove-edge-replication`

### Stage 2 Stop Rule
Stop when readiness reports academic pass with no fold/sharpe/FDR/regime/replication blockers.  
If Sharpe/FDR still fail after Stage 1, do not apply threshold fallback as a “fix”; open a new planning cycle for signal-quality changes.

## Important Public API / Interface / Type Changes
1. No Python API/type/schema changes are required for this plan.
2. Operational interface change:
   - `Makefile` replication default `REPLICATION_SYMBOLS` will include `SOXL`.
3. Replication profile behavior change:
   - Added `SOXL` to validation scope,
   - Added `soxl_2h_author`,
   - Increased `risk.timeout_bars` to `240` (replication config only).

## Test Cases and Scenarios
1. `make test` must stay green after config/Make/doc updates.
2. `make validate-config` must pass for:
   - `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`
   - `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml`
3. Update `tests/unit/test_makefile_replication_lane.py` to assert replication lane plumbing still exists and now includes SOXL in default replication symbol config (string-level assertion).
4. Confirm strict lane unchanged by running:
   - `make prove-edge CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=month` (optional if runtime is acceptable; otherwise defer as manual acceptance).

## Assumptions and Defaults
1. Strict lane remains canonical and unchanged.
2. No relaxation of Sharpe/FDR/bootstrap/replication-score thresholds in Stage 1.
3. Fallback trade-floor relaxation to `7` is replication-only and conditional.
4. Data/provider assumptions remain Alpaca free-tier aligned (since 2016, 15-minute lag handling already in repo).
5. No broad detector/risk refactors in this cycle.
