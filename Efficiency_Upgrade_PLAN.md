# Implementation Plan: Legacy/Compat Removal + Performance + Library Leverage (Fallback Code Preserved)

## Summary
This plan removes legacy/backward-compatibility paths, keeps only the modern implementation, upgrades hot-path performance, maximizes use of reliable libraries to reduce manual code, and removes verified dead code.  
Fallback-related logic is explicitly preserved unchanged in this iteration and only documented.

## Locked Decisions
- API contract mode: **Strict modern-only** (breaking changes allowed).
- Library strategy: **Maximal library shift** (where it reduces custom code and remains reliable).
- Performance strategy: **Hot paths first**.
- Delivery: **Phased hardening with test gates**.
- Reporting contract target: **`both` only**.

## Scope
- In scope: remove legacy/v1/backward-compatibility branches, deduplicate duplicated logic, implement performance upgrades, add/replace libraries where they reduce manual logic, remove proven dead code.
- Out of scope: removing fallback logic. No fallback code deletion or behavior change.

## Public API / Interface Changes
- `report` CLI becomes canonical modern contract only.
- Remove `--attribution` branching; report output always uses `both`.
- Report JSON schema becomes explicit:
  - `attribution_mode: "both"`
  - `strike_attribution: {...}`
  - `close_attribution: {...}`
  - No compatibility-style duplicated top-level strike metrics.
- Remove `strategy.mode` field (`author_v1`) from config model and YAML configs.
- Remove “replay-only in v1” guards by implementing feature parity in live for:
  - `risk_mode=atr_dynamic_stop`
  - `cross_symbol_context.enabled=true`
- Internal shared interface additions:
  - `ExecutionScope` resolver shared by CLI/live/replay.
  - Shared timestamp/source-value helpers.
  - Shared outfit-path resolver.

## Fallback Code Inventory (Documented, No Change This Iteration)
The following fallback/resilience mechanisms are preserved as-is:
- `src/sma_outfits/live/runner.py` reconnect loop with exponential backoff.
- `src/sma_outfits/data/alpaca_clients.py` websocket stale-feed detection and heartbeat timeout handling.
- Existing duplicate-bar idempotency behavior in live ingestion/persistence paths.
- Any fallback-related semantics in current runtime error-recovery paths.
Plan rule: no logic change, no deletion, no simplification of these paths in this effort.

## Phase Plan

## Phase 0: Baseline and Safety Gates
- Add/refresh Make targets for non-mutating validation gates used during implementation: `validate-config`, `test`, and a new dead-code check target.
- Capture baseline runtime/perf metrics for replay and live mocked pipeline to compare after refactor.
- Freeze baseline artifacts/metrics in `artifacts/readiness/` for before/after comparison.

## Phase 1: Legacy/Backward-Compatibility Removal
- Remove config/model legacy marker `strategy.mode: Literal["author_v1"]` from `src/sma_outfits/config/models.py`.
- Remove v1/backward-compat language and compatibility assumptions from:
  - `ASSUMPTIONS.md`
  - relevant README sections that conflict with current Alpaca-only architecture.
- Convert reporting path to canonical `both` contract only:
  - `src/sma_outfits/reporting/summary.py`
  - `src/sma_outfits/cli.py`
  - `Makefile` report args (`REPORT_ATTRIBUTION*`) removal.
- Update tests that currently assert legacy/compat behavior for `strike` or `close` modes.

## Phase 2: Live/Replay Feature Parity (Remove v1 Guards)
- Remove live-time prohibitions for `atr_dynamic_stop` and `cross_symbol_context` in `src/sma_outfits/live/runner.py`.
- Implement cross-symbol context in live using same lookup semantics as replay:
  - maintain latest route context by route id and timestamp.
  - pass `cross_context_lookup` callback to detector in live path.
- Keep risk handling unified through existing `RiskManager` ATR methods; ensure live path supplies required `route_history`.
- Add parity tests so live mocked pipeline behavior matches replay for these features.

## Phase 3: Deduplicate Shared Logic
- Extract duplicated helpers currently in CLI/live/replay into shared module(s), including:
  - execution pair resolution
  - strict routing preflight checks
  - outfit path resolution
  - UTC conversion helpers
  - strategy source-value computation
- Refactor `src/sma_outfits/cli.py`, `src/sma_outfits/live/runner.py`, and `src/sma_outfits/replay/engine.py` to consume shared helpers.
- Remove duplicate implementations after tests pass.

## Phase 4: Hot-Path Performance Upgrades
- Replace row-by-row DataFrame growth (`loc[len(frame)]`) in live/replay history paths with bounded buffers (deque/list-backed), converting to DataFrame only at evaluation boundaries where necessary.
- Replace per-tick full-frame `resample_ohlcv` in live with incremental timeframe aggregators keyed by `(symbol, timeframe)`.
- Reduce write amplification in `StorageManager.write_bars` by moving from read-modify-rewrite on each write to append-oriented chunk persistence and query-time dedupe.
- Optimize `read_bars` with DuckDB query filtering/dedup over parquet glob instead of loading/concatenating all partitions eagerly.
- Keep deterministic ordering and dedupe guarantees intact.

## Phase 5: Maximal Library Leverage (Non-Fallback Areas)
- Replace manual `.env.local` parsing with `pydantic-settings` (strict required keys, `.env.local` only, hard error on missing keys).
- Use high-performance JSON serialization (`orjson`) for event append/load paths where contracts remain identical.
- Add `vulture` for dead-code detection as a CI/dev gate.
- Keep fallback logic untouched while reducing manual boilerplate in config/loading/storage/reporting paths.

## Phase 6: Dead Code Removal (Proof-Driven)
- Dead code removal criterion (all required):
  - zero references outside defining module via repo-wide search
  - not part of required public script/API contract
  - removal passes full test suite and integration checks
- Initial candidates to verify and remove if criteria pass:
  - `src/sma_outfits/signals/classifier.py` and corresponding exports in `src/sma_outfits/signals/__init__.py`
  - `StorageManager.open_duckdb` if still unused after storage refactor
  - `records_to_events` in `src/sma_outfits/reporting/summary.py` if unused
  - unused runtime constants in `src/sma_outfits/runtime.py`
- Add dead-code check in Make workflow and fail CI on newly introduced dead symbols.

## Phase 7: Documentation and Final Hardening
- Update `ASSUMPTIONS.md` to reflect modern-only contracts and removal of compatibility behaviors.
- Update README sections that are now incorrect for current Alpaca-only architecture.
- Add a short “Fallback Inventory (Preserved)” section to docs to explicitly state deferred investigation areas.
- Regenerate `make_commands.md` examples to match removed report attribution options and new canonical behavior.

## Test Cases and Scenarios
- Config loading:
  - `.env.local` missing required key must hard fail.
  - `.env.local` present with valid keys must pass.
- Reporting:
  - `report` command emits canonical `both`-only schema.
  - old attribution modes are rejected (or removed from interface entirely).
- Live/replay parity:
  - `atr_dynamic_stop` route runs in live mocked pipeline without “replay-only” error.
  - `cross_symbol_context` route runs in live mocked pipeline with valid cross-context gating.
- Strict routing:
  - shared resolver enforces identical behavior across CLI/live/replay.
- Performance:
  - replay and live mocked benchmarks show measurable throughput improvement versus baseline.
  - storage read/write path latency improves on representative backfill + replay ranges.
- Regression:
  - `make validate-config` with all checked-in configs.
  - full `make test` green.

## Assumptions and Defaults
- Breaking contract changes are acceptable for this refactor.
- `both` is the sole canonical reporting attribution mode.
- Fallback logic is intentionally unchanged and explicitly deferred.
- Makefile remains the only entrypoint for project workflows.
- Python runtime remains pinned to `3.14.3`.
- Dead code is removed only with proof criteria satisfied; no speculative deletions.
