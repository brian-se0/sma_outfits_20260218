### Dual-Lane Alignment Plan: Keep Strict Canonical, Add Replication Lane That Matches Desired Behavior

## Summary
This plan implements a **dual-lane validation architecture**:

1. **Strict lane (unchanged canonical):** existing `make prove-edge` remains the research-grade bar.
2. **Replication lane (new):** a new `make prove-edge-replication` flow uses a moderate validation override and targeted 2H route additions to align behavior with your intended sparse/high-conviction style.

It also includes a **regime-stability logic correction** (bar-based proxy months) so failures are not artifacts of proxy-trade sparsity.

Chosen decisions to lock:
- Primary goal: Hybrid path.
- Relaxation policy: Moderate preset, override profile only.
- Trading logic scope: targeted 2H + hold logic updates.
- Regime fix: bar-based regime logic.
- UX: new Make target for replication.
- Acceptance: dual-lane completion criteria.

---

## Scope
In scope:
- New replication config profile.
- New Makefile target for replication lane.
- Regime-stability refactor to bar-based month classification.
- WFO feasibility diagnostics.
- Targeted route additions in replication profile (2H focus).
- Tests + runbook updates.

Out of scope:
- Changing strict default thresholds.
- Changing data provider/data quality assumptions.
- Broad detector/risk framework rewrite.

---

## Implementation Workstreams

### 1) Add Replication Profile Config (override-only relaxation)
Create:
- `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`

Base it on:
- `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml`

Change only replication-lane values:
- `validation.wfo.min_folds: 3`
- `validation.wfo.min_closed_trades_per_fold: 10`
- `validation.thresholds.replication_score_min: 0.70`
- Keep `oos_sharpe_min`, `oos_calmar_min`, `bootstrap_pvalue_max`, `fdr_qvalue_max` unchanged.
- Keep `validation.bootstrap.samples`, `random_strategy_mc_samples`, `seed` unchanged initially (can reduce later for runtime if needed).
- `validation.scope_symbols` expanded for replication lane to include targeted 2H symbols:
  - `QQQ, SPY, TQQQ, SQQQ, SVIX, VIXY, XLF, SMH`

Hold-style config choices (replication lane only):
- `strategy.allow_same_bar_exit: true`
- Keep existing `dynamic_reference_migration: true` on current routes.
- Keep strict lane config untouched.

### 2) Add Targeted 2H Routes (replication profile only)
In replication config, add:
- `xlf_2h_author`
- `smh_2h_author`

Route specs:
- `symbol`: `XLF` / `SMH`
- `timeframe`: `2h`
- `outfit_id`: `warings_problem`
- `key_period`: `548`
- `micro_periods`: `[19, 37, 73, 143, 279]`
- `side`: `LONG`
- `signal_type`: `magnetized_buy`
- `risk_mode`: `penny_reference_break`
- `stop_offset`: `0.01`
- `dynamic_reference_migration`: `true`
- `confluence.enabled`: `true`
- `confluence.min_outfit_alignment_count`: `2`
- `confluence.volume_spike_ratio`: `1.2`
- `cross_symbol_context.enabled`: `true`
- `cross_symbol_context.rules`: reference `qqq_1h_author` with both requirements `false`

Rationale:
- Adds 2H pathway without rewriting core detector/risk engines.
- Keeps changes isolated to replication profile.

### 3) Regime Stability Refactor to Bar-Based Proxy Months
Current issue:
- Regime currently fails when proxy symbol has no trades in month (`regime_proxy_month_mapping_missing`), even with available bars.

Refactor:
- Build proxy month regime scores from **proxy symbol bars**, not proxy trades.
- Use existing `validation.regime.proxy_symbol`.
- Add `validation.regime.proxy_timeframe` (default `1h`) in config schema.

Code changes:
- `src/sma_outfits/config/models.py`
  - Extend `ValidationRegimeConfig` with `proxy_timeframe: str = "1h"` and validation against supported timeframes.
- `src/sma_outfits/cli.py`
  - In `report`, `replay`, `verify-readiness`, load proxy bars for `[start, end]`.
  - Compute monthly volatility map from proxy bars (`pct_change(close)`, monthly std).
  - Pass this map into summary/academic validation.
- `src/sma_outfits/reporting/summary.py`
  - Extend `build_summary_from_records(...)` with optional `regime_proxy_monthly_vol: dict[str, float] | None`.
- `src/sma_outfits/reporting/academic_validation.py`
  - Update `_regime_stability_summary(...)` to use passed month-vol map as the primary classifier.
  - Keep fail-fast if map missing/empty for selected window.

Output additions:
- Include regime coverage diagnostics in academic JSON:
  - `proxy_month_count`
  - `mapped_trade_month_count`
  - `missing_proxy_month_count`

### 4) Add WFO Feasibility Diagnostics (strict + replication lanes)
Purpose:
- Prevent opaque fold failures when the window cannot satisfy WFO requirements.

Code:
- `src/sma_outfits/reporting/academic_validation.py`
  - Add feasibility computation before fold build:
    - `available_months`
    - `required_months_for_min_folds`
    - `max_feasible_folds`
    - `is_feasible`
  - Add explicit blocker:
    - `wfo_window_infeasible_for_config`

Report:
- Surface feasibility block in:
  - `*_academic_validation.json`
  - markdown appendix (WFO section)
  - readiness blocker list

### 5) Add Replication Lane Make Target (new UX)
In `Makefile`:
- Keep `prove-edge` unchanged.
- Add `prove-edge-replication` target.

New vars:
- `REPLICATION_CONFIG ?= configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`
- `REPLICATION_SYMBOLS ?= QQQ,SPY,TQQQ,SQQQ,SVIX,VIXY,XLF,SMH`
- `REPLICATION_TIMEFRAMES ?= 30m,1h,2h`
- `REPLICATION_DISCOVER_OUTPUT ?= artifacts/readiness/discovered_range_replication.json`
- `REPLICATION_END ?= $(READINESS_END)`

Flow in `prove-edge-replication`:
1. `make discover-range` using replication symbols/timeframes, writing `REPLICATION_DISCOVER_OUTPUT`.
2. Resolve `full_range_start` from that manifest.
3. Run `make e2e ... STAGES=validate-config,backfill,replay,report` with resolved start.
4. Run `make verify-readiness ... VERIFY_READINESS_ARGS=--require-academic-validation`.

This avoids manual boundary-start mistakes.

### 6) Docs/Runbook
Update:
- `make_commands.md`
- `README.md` (validation workflow section)

Add:
- strict lane command examples.
- replication lane command examples.
- interpretation guidance:
  - strict lane failure = canonical gate miss
  - replication lane pass = intended behavior alignment under moderate sparse-style profile

---

## Important Public API / Interface / Type Changes
1. Config schema:
- `validation.regime.proxy_timeframe` (new).

2. Reporting API:
- `build_summary_from_records(...)` gains:
  - `regime_proxy_monthly_vol: dict[str, float] | None`.

3. Academic validation internals/output:
- `academic_validation` payload adds `wfo_feasibility` block.
- `regime_stability` now bar-based with explicit coverage stats.

4. Makefile interface:
- New target: `make prove-edge-replication`.
- New replication vars (config/symbol/timeframe/discovery output/end).

---

## Test Cases and Scenarios

### Unit Tests
1. `tests/unit/test_academic_validation.py`
- WFO feasibility math:
  - infeasible window emits `wfo_window_infeasible_for_config`.
- Regime classifier:
  - bar-based month map assigns high/low without proxy-trade dependence.
  - missing/empty proxy map hard-fails as designed.
- Existing bootstrap/FDR determinism tests remain green.

2. `tests/unit/test_config.py`
- `validation.regime.proxy_timeframe` validation:
  - accepts supported values, rejects unsupported.

3. `tests/unit/test_reporting_summary.py`
- Appendix includes new WFO feasibility + regime coverage fields.

### Integration Tests
1. `tests/integration/test_verify_readiness_academic_gate.py`
- strict profile can still fail with explicit blockers.
- replication profile fixture passes moderate gates.

2. New integration test for replication lane plumbing:
- `prove-edge-replication` equivalent sequence (discover-range -> e2e -> verify-readiness) succeeds with fixture data.

### Regression Safety
- Existing `make test` must pass.
- Existing strict `make prove-edge` behavior remains unchanged (no interface regression).

---

## Acceptance Criteria (Dual-Lane)
Phase 1 is complete when all are true:

1. Strict lane:
- `make prove-edge` remains unchanged and functional.
- If it fails, blockers include actionable WFO feasibility/regime diagnostics (no opaque artifact-only failures).

2. Replication lane:
- `make prove-edge-replication` completes end-to-end.
- `artifacts/readiness/readiness_acceptance.json` contains:
  - `academic_validation.ready = true`
  - no blockers for fold count/trades per fold/regime/replication score.
- Appendix artifacts are generated as expected.

3. Metrics integrity:
- Bootstrap/FDR logic and thresholds remain unchanged in both lanes.
- Relaxation applies only via replication profile config.

---

## Assumptions and Defaults
- Data provider and data quality remain unchanged (no paid-data uplift).
- Strict defaults remain the canonical research bar.
- Moderate relaxation is profile-only:
  - `min_folds=3`
  - `min_closed_trades_per_fold=10`
  - `replication_score_min=0.70`
- Regime proxy symbol remains `VIXY`; timeframe default `1h`.
- Targeted first-wave route additions are only `XLF/2h` and `SMH/2h`.
- No broad detector/risk engine refactor in this phase.
