# Cross-Symbol Context v1 Plan and Full-Range Readiness Roadmap

## Summary
Implement **real cross-symbol context gating** as a replay feature (config + detector + replay + tests), roll it out as an A/B experiment config (not canonical by default), then harden the workflow to reach:  
**“ready to run all stock symbols across the full Alpaca date range”** (with data-only backfill for non-routed symbols, per your decision).

## Locked Decisions (from this planning session)
1. Scope: **Replay-only** for v1 cross-symbol context.
2. Activation: **Config-only** (no runtime `FEATURES=` switch required to enable behavior).
3. Reference binding: **By `route_id`**.
4. Gate condition: Require **both** `macro_positive` and `micro_positive` booleans.
5. Timing policy: Use latest reference context with `reference_ts <= bar_ts`.
6. Missing runtime reference context: **Block signal and continue** (no abort).
7. Final readiness universe: **All stock symbols only** (exclude crypto from readiness target).
8. Final readiness definition: **Data-only for non-routed symbols** is acceptable.
9. Initial rollout config: **New experiment config**, canonical config remains unchanged.
10. Initial gate coverage: **Inverse/defensive routes only**.
11. Reference benchmark for v1: **QQQ-only reference route**.

## Public API / Interface Changes
1. Extend `RouteRule` config schema with:
   - `cross_symbol_context.enabled: bool = false`
   - `cross_symbol_context.rules: list[CrossSymbolRule] = []`
2. Add `CrossSymbolRule` schema:
   - `reference_route_id: str` (required)
   - `require_macro_positive: bool` (required)
   - `require_micro_positive: bool` (required)
3. Extend detector API:
   - `StrikeDetector.detect(..., cross_context_lookup: Callable[[str, datetime], RouteBarContext | None] | None = None)`
4. Add replay preflight for cross-context route references.
5. Add run-live guard that rejects configs with `cross_symbol_context.enabled=true` (v1 replay-only contract).

## Phase 1: Config Model + Validation
1. Add new Pydantic models in `src/sma_outfits/config/models.py`:
   - `CrossSymbolRuleConfig`
   - `RouteCrossSymbolContextConfig`
2. Add `cross_symbol_context` field to `RouteRule`.
3. Validation rules:
   - If `cross_symbol_context.enabled=true`, `rules` must be non-empty.
   - Each `reference_route_id` must be non-empty.
   - A route cannot reference itself.
   - `reference_route_id` must exist in `strategy.routes`.
   - Duplicate `reference_route_id` within a route’s `rules` is rejected.
4. Keep strict fail-fast behavior for invalid configs.

## Phase 2: Detector Gating Logic
1. Add `_passes_cross_symbol_context(...)` in `src/sma_outfits/signals/detector.py`.
2. Gate semantics:
   - If route cross-symbol context disabled: pass.
   - If enabled and `cross_context_lookup` not supplied: raise runtime error.
   - For each rule:
     - lookup reference context by route id at `bar.ts` (latest `<= ts` provided by engine).
     - if `None`: fail gate (block signal).
     - enforce exact boolean match:
       - `reference.macro_positive == require_macro_positive`
       - `reference.micro_positive == require_micro_positive`
   - All rules are ANDed.
3. Keep current confluence + trigger + micro/macro route checks unchanged; cross-symbol gate is additive.

## Phase 3: Replay Engine Rework for Temporal Correctness
1. Refactor replay processing in `src/sma_outfits/replay/engine.py` from “pair-by-pair full pass” to **global chronological processing** across all selected pairs.
2. Process bars in timestamp batches with **two-pass logic per timestamp**:
   - Pass A: build history, SMA state, and per-route `RouteBarContext` for all bars at timestamp `t`; update reference context cache.
   - Pass B: run detect/risk/open/close using cache that already includes same-timestamp references.
3. Maintain per-pair persistent state maps:
   - history by `(symbol,timeframe)`
   - active positions by `(symbol,timeframe)`
4. Implement cross-context lookup store:
   - `latest_context_by_route_id: {route_id -> (ts, RouteBarContext)}`
   - lookup returns context only when cached `ts <= bar.ts`.
5. Add replay preflight:
   - if selected symbols/timeframes omit a required reference route pair, hard-fail before run (config/scope mismatch).
6. Runtime missing-context behavior remains “block signal and continue” only for data-state absence, not for misconfiguration.

## Phase 4: Live Contract (Explicit v1 Boundary)
1. In `src/sma_outfits/live/runner.py`, add guard similar to ATR replay-only guard:
   - if any selected route has `cross_symbol_context.enabled=true`, fail with clear message:
     - “cross_symbol_context is replay-only in v1.”
2. Do not implement live cross-symbol logic in this phase.

## Phase 5: Makefile / UX Contract
1. Keep activation config-driven.
2. Keep fail-fast behavior for misleading feature usage:
   - If `FEATURES=cross_symbol_context` is passed, fail with explicit “not implemented as runtime flag; use config.”
3. Update help text accordingly so no command implies runtime feature toggle for this behavior.
4. Keep `UNIVERSE=core_expanded` support intact.

## Phase 6: Test Plan (Must Pass Before Merge)
1. Config unit tests (`tests/unit/test_config.py`):
   - enabled + empty rules rejected.
   - unknown `reference_route_id` rejected.
   - self-reference rejected.
   - duplicate reference route in same rule set rejected.
2. Detector unit tests (`tests/unit/test_detector.py`):
   - pass when both reference booleans match.
   - fail on macro mismatch.
   - fail on micro mismatch.
   - fail when reference context missing.
   - fail-fast when enabled but no lookup callback supplied.
3. Replay integration tests (`tests/integration/test_replay_pipeline.py`):
   - same-timestamp cross-symbol pass (two routes, same ts).
   - same-timestamp cross-symbol block.
   - missing reference bars blocks signal without abort.
   - omitted reference route pair in selected scope hard-fails preflight.
4. Live integration/unit test:
   - run-live rejects any enabled cross-symbol route.
5. Regression expectation:
   - with all `cross_symbol_context.enabled=false`, existing replay results remain unchanged.

## Phase 7: Rollout Configs and A/B Experiment
1. Keep canonical config as:
   - `configs/settings.jan2025_confluence_atr_svix211_106.yaml`
2. Add experiment config:
   - `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml`
3. In experiment config, enable cross-symbol rules only for inverse/defensive routes present today:
   - `rwm_30m_author`
   - `sqqq_30m_author`
   - `vixy_30m_author`
4. Rule values for each gated route:
   - reference route: `qqq_1h_author`
   - `require_macro_positive: false`
   - `require_micro_positive: false`
5. Keep all non-inverse routes ungated in v1.

## Phase 8: Post-Implementation Natural Next Steps to Full-Range Readiness
1. Add all-stocks readiness universe alias (stocks only, exclude crypto):
   - `UNIVERSE=all_stocks`
2. Add date-range discovery capability (new CLI + Make target), config-agnostic and fail-fast:
   - CLI command: `discover-range`
   - Output manifest with earliest available timestamp per `(symbol,timeframe)` for stocks.
3. Use manifest to define readiness start boundary:
   - `FULL_RANGE_START = min(all discovered stock starts)` for backfill sweep.
4. Readiness run sequence (data-only for non-routed symbols):
   - Run A (all stocks, full range): `STAGES=validate-config,backfill`
   - Run B (routed subset, same range): `STAGES=replay,report`
5. Preserve strict routing for replay/report runs; do not loosen to implicit no-route mode.
6. Add readiness acceptance checks:
   - backfill completes for all stock symbols/timeframes in scope.
   - no ingest schema/session monotonicity failures.
   - replay/report complete on routed universe with deterministic outputs.
   - artifact manifests + hashes written for reproducibility.

## Operational Acceptance Criteria
1. Cross-symbol-enabled experiment config validates.
2. Replay succeeds with v1 gating and produces deterministic results on repeat.
3. Comparator run (canonical vs crossctx_v1) shows expected gated-route strike deltas.
4. Non-gated routes retain baseline parity.
5. All-stock backfill full-range run succeeds using discovered range.
6. Routed replay/report full-range run succeeds using same range boundary.

## Explicit Assumptions and Defaults
1. Canonical production/research route remains `_106`; `_116` remains comparator-only.
2. v1 cross-symbol context is replay-only.
3. Cross-symbol logic is config-defined per route; no runtime feature flag controls behavior.
4. Final readiness milestone does not require trading routes for every stock symbol.
5. Crypto is excluded from this readiness milestone.
