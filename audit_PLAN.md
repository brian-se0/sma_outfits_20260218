# Implementation Plan: Auditability Fixes Without Strategy Drift

## Summary
This plan fixes the real code-level gaps from the latest run review while preserving current signal/exit behavior and reproducibility.  
Primary outcome: positions become lifecycle-auditable (`open` + `close` events), reports remain numerically stable for PnL metrics, and live-scope documentation is corrected to reflect existing capabilities.

## Scope
1. In scope: position event lifecycle auditability, reporting contract updates, config/validation clarity for inactive risk knobs, documentation corrections, and regression tests.
2. Out of scope: implementing Alpaca order submission/fill callbacks and changing strategy entry/exit logic.

## Public API / Interface Changes
1. `PositionEvent.action` contract in [events.py](d:/sma_outfits_20260218/src/sma_outfits/events.py) is formalized to include `open`, `partial_take`, `close` (currently only `close` emitted in practice).
2. `positions.jsonl` event stream in [artifacts/svix211_106/events/positions.jsonl](d:/sma_outfits_20260218/artifacts/svix211_106/events/positions.jsonl) will include one `open` row per signal at entry time.
3. Summary payload in [summary.py](d:/sma_outfits_20260218/src/sma_outfits/reporting/summary.py) adds explicit position-action breakdown (`open`, `partial_take`, `close`) so auditing tools do not infer from total count.
4. No CLI command changes; existing Make targets remain the execution surface.

## Detailed Implementation Steps
1. Add lifecycle event constructor in [manager.py](d:/sma_outfits_20260218/src/sma_outfits/risk/manager.py): introduce `open_event(position, ts)` that emits `PositionEvent(action="open", qty=position.remaining_qty, price=position.entry, reason="position_opened")`.
2. Wire replay emission in [engine.py](d:/sma_outfits_20260218/src/sma_outfits/replay/engine.py): immediately after each `open_position(...)`, append corresponding `open` event before bar evaluation; keep exit logic unchanged.
3. Wire live emission in [runner.py](d:/sma_outfits_20260218/src/sma_outfits/live/runner.py): emit and persist `open` events with existing dedupe flow so restart/idempotency behavior is preserved.
4. Keep realized-R math stable in [summary.py](d:/sma_outfits_20260218/src/sma_outfits/reporting/summary.py): continue using only `partial_take` and `close` for PnL; explicitly ignore `open` in outcome calculations.
5. Add action-breakdown reporting in [summary.py](d:/sma_outfits_20260218/src/sma_outfits/reporting/summary.py): expose counts by action and include in markdown/CSV payload to improve auditability.
6. Enforce no-op knob clarity in [models.py](d:/sma_outfits_20260218/src/sma_outfits/config/models.py): add validation that if all configured routes are close-only risk modes (`singular_penny_only`, `penny_reference_break`), non-default `partial_take_r`, `final_take_r`, or `timeout_bars` is rejected with a fail-fast message.
7. Update docs in [README.md](d:/sma_outfits_20260218/README.md): document that current live path supports signal generation, state persistence, duplicate/late-bar protection, and reconciliation, but not order submission/fill handling.
8. Add migration note: parsers that used `total_position_events == closed_positions` must switch to `action == "close"` filtering.

## Test Plan
1. Unit test in [test_risk_manager.py](d:/sma_outfits_20260218/tests/unit/test_risk_manager.py): verify `open_event` fields, qty/price/reason, deterministic id format.
2. Unit test in [test_reporting_summary.py](d:/sma_outfits_20260218/tests/unit/test_reporting_summary.py): add `open` events and assert hit rate, realized-R buckets, and close reason stats are unchanged.
3. Integration replay test: for a controlled fixture, assert `signals == opens == closes`, and `positions.jsonl` action distribution includes `open`.
4. Integration live test in [test_live_pipeline_mocked.py](d:/sma_outfits_20260218/tests/integration/test_live_pipeline_mocked.py): ensure restart does not duplicate `open`/`signal` rows and reconciliation metrics still compute.
5. Config validation test in [test_config.py](d:/sma_outfits_20260218/tests/unit/test_config.py): assert non-default partial/final/timeout values fail for close-only route sets.

## Acceptance Criteria
1. `make test` passes with new lifecycle and validation tests.
2. A replay/report run (`make e2e ... STAGES=replay,report`) keeps strike/signal counts and hit-rate statistics unchanged versus baseline, while position event totals increase by exactly `+signals` due to `open` rows.
3. Report explicitly shows position action breakdown and still computes close-based analytics correctly.
4. Documentation no longer claims missing state persistence/reconciliation/late-bar handling.

## Assumptions and Defaults
1. Default strategy behavior must remain unchanged; this is an observability and contract-clarity patch, not a trading-logic patch.
2. `partial_take` and timed exits remain unimplemented for close-only routes in this change; we fail fast on misleading non-default knobs.
3. Live order placement remains out of scope until a separate execution-mode design is approved.
4. All verification and execution continue through Makefile targets only.
