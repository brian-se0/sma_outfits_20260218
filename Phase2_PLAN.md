# Phase 2 Plan

Date: 2026-03-06  
Project: `sma_outfits_20260218`

## Summary

Phase 2 is the live-paper hardening phase that follows the completed historical Phase 1 statistical closeout.

The current runtime contract is:

- `context`: default operational source-aligned lane
- `strict`: baseline research/comparator lane

`replication` is not part of the current runtime interface and must not be reintroduced through new Make targets, config paths, or workflow docs.

## Current Ground Truth

1. `make phase1-close` remains available as a reproducibility harness, now in a 2-profile recheck form.
2. `make phase2-preflight CONFIG_PROFILE=context` is the current entrypoint for Part 2 preflight work.
3. `paper-hardening-init` still reports three blocking implementation gaps:
   - `missing_broker_order_submission`
   - `missing_fill_callback_processing`
   - `missing_drawdown_alerting`
4. The live runner already has streaming, restart-safe state persistence, duplicate-bar protection, and optional reconciliation scaffolding.

## Objectives

1. Close the remaining Phase 2 implementation gaps in the live path.
2. Preserve fail-fast behavior and reproducibility metadata.
3. Keep live and non-live behavior aligned where the strategy semantics overlap.
4. Maintain the two-profile contract without adding compatibility aliases.

## Workstreams

### 1) Live Execution Completion

- Implement broker order submission with explicit failure handling and no silent fallback behavior.
- Add fill-callback processing so live state reflects broker acknowledgements and fills deterministically.
- Preserve `.env.local` as the only secret source.

### 2) Operational Risk Hardening

- Add explicit drawdown alerting and any related operator-facing telemetry required for live-paper supervision.
- Keep risk controls config-driven and auditable.
- Ensure new live controls fail fast when required state or config is missing.

### 3) Validation and Replay Parity

- Extend tests for broker submission, fill processing, and drawdown-alert paths.
- Keep `context` as the operational validation lane.
- Use `strict` as the comparator when a non-live baseline check is required.
- Do not add any Phase 2 workflow that depends on a `replication` runtime profile.

### 4) Paper Validation Evidence

- Run bounded paper validation only after the blocking live gaps are closed.
- Archive run metadata, config identity, and relevant live-paper evidence under non-overwriting paths.
- Document acceptance criteria and observed limitations alongside the generated artifacts.

## Acceptance Criteria

1. `make phase2-preflight CONFIG_PROFILE=context` passes.
2. Updated tests cover the new live hardening behavior.
3. Live-paper workflows remain deterministic where deterministic behavior is expected.
4. Current docs, Make targets, and examples continue to describe only `strict` and `context`.

## Historical References

- Historical Phase 1 closeout record: `End_of_Phase1_Report.md`
- Historical three-profile planning artifacts: `audit/history/`
