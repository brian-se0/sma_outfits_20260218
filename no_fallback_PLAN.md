# Strict Fail-Fast Contract Enforcement Plan (No Fallbacks, No Backward-Compat Paths)

## Summary
Implement a strict contract policy across runtime data ingestion and processing so the system accepts only documented/canonical formats and hard-fails on any deviation.  
Chosen policy decisions:
1. Scope: `Runtime Contracts` only (keep existing explicit config defaults).
2. Ambiguous outfits: `Keep But Strict` (allow `source_ambiguous: true`, but require complete schema).
3. Reporting: `Hard Fail` on inconsistent links (remove `UNKNOWN` placeholders).

## In Scope
1. Remove fallback/compat logic from Alpaca REST + websocket payload parsing.
2. Remove runtime path fallback for outfits catalog location.
3. Remove implicit/default fallback behavior in contract-critical parsing and reporting paths.
4. Add/adjust tests to enforce strict failure behavior.
5. Keep deterministic + fail-fast behavior and Makefile-only workflow intact.

## Out of Scope
1. Removing all non-secret config defaults from `Settings` models.
2. Any strategy logic change, archive format redesign, or chart stack changes (already done).
3. New feature flags for compatibility mode.

## Public API / Interface Changes
1. `sma-outfits backfill`, `sma-outfits replay`, `sma-outfits run-live` behavior:
   - Will now fail immediately on non-canonical Alpaca payload shape/fields.
2. `sma-outfits report` behavior:
   - Will now raise hard errors when signal/strike relationship data is inconsistent.
3. Internal interfaces:
   - `RiskManager.evaluate_bar(...)` and `RiskManager.__init__(...)` will stop accepting implicit `None` fallbacks for mappings (explicit dict required).
   - Outfit loader contract will require complete keys; no `.get(..., default)` for required outfit fields.

## Implementation Steps

### 1) Codify canonical Alpaca contracts in code
1. Add strict schema constants/validators in `src/sma_outfits/data/alpaca_clients.py` (or a new `src/sma_outfits/data/alpaca_contracts.py` module).
2. Define required payload structure per endpoint from Alpaca docs:
   - REST bars: `payload["bars"]` must be symbol-keyed map with list rows.
   - Row fields must use canonical keys expected by endpoint (no alternate key aliases).
   - Websocket messages must match documented bar message shape exactly.
3. Fail with actionable errors containing endpoint, symbol, and offending keys/type.

### 2) Remove backward-compatible parsing branches
1. In `src/sma_outfits/data/alpaca_clients.py`:
   - Remove `dict-or-list` bars branching.
   - Remove compact-vs-expanded key fallbacks (for example `t` vs `timestamp`, `S` vs `symbol`, `o` vs `open`).
   - Remove single-object websocket payload normalization; accept only documented message container.
2. Keep strict type and required-field validation before converting to DataFrame/events.

### 3) Remove runtime file-path fallback for outfits
1. In `src/sma_outfits/replay/engine.py` and `src/sma_outfits/live/runner.py`:
   - Replace `_resolve_outfits_path` fallback behavior with a single strict path check on `settings.outfits_path`.
   - Fail if missing/unreadable.

### 4) Tighten outfit catalog loading
1. In `src/sma_outfits/signals/detector.py`:
   - Require each outfit row to include all required keys (`id`, `periods`, `description`, `source_configuration`, `source_ambiguous`).
   - Remove default `.get(..., "")` / `.get(..., False)` for required fields.
   - Keep `source_ambiguous` allowed, but enforce strict schema completeness.

### 5) Remove report-time compatibility placeholders
1. In `src/sma_outfits/reporting/summary.py`:
   - Replace `UNKNOWN` placeholder logic with hard exceptions when referenced strike/signal links are missing.
   - Enforce required keys for breakdown labels instead of defaulting unknown labels.
2. Ensure failures identify offending record IDs for diagnosis.

### 6) Remove internal optional-mapping fallbacks
1. In `src/sma_outfits/risk/manager.py`:
   - Require explicit dicts for `migrations` and `proxy_prices`.
   - Remove `migrations or {}` and `proxy_prices or {}` fallback paths.
2. Update callers to always pass explicit dicts.

### 7) Remove environment-based timezone override fallback
1. In `src/sma_outfits/config/models.py`:
   - Remove implicit `APP_TIMEZONE` override when `sessions.timezone` omitted.
   - Keep explicit model defaults as currently allowed by selected scope.
2. Keep `.env.local` secret enforcement unchanged.

### 8) Tighten any newly introduced progress/status parsing fallbacks
1. In `src/sma_outfits/cli.py` live progress callback:
   - Replace defensive `.get(..., default)` parsing of runner progress payload with strict required key access.
2. Treat missing keys as internal contract violation.

## Test Plan

### Unit tests to add/update
1. `tests/unit/test_alpaca_clients_strict_contracts.py` (new):
   - Reject non-canonical REST bars shape.
   - Reject alternate key aliases.
   - Reject single-object websocket payload when array is required.
   - Reject malformed bar messages missing required fields.
2. `tests/unit/test_detector.py`:
   - Fail when required outfit row keys are missing.
   - Pass when `source_ambiguous: true` row is complete.
3. `tests/unit/test_reporting_summary.py`:
   - Fail on signal referencing missing strike.
   - Fail on missing breakdown key fields.
4. `tests/unit/test_risk_manager.py`:
   - Validate explicit mappings required; `None` no longer accepted.
5. `tests/unit/test_config.py`:
   - Verify no `APP_TIMEZONE` fallback injection behavior.

### Integration tests to add/update
1. `tests/integration/test_replay_pipeline.py`:
   - Add case where missing outfits path hard-fails.
2. `tests/integration/test_live_pipeline_mocked.py`:
   - Add malformed live payload case that hard-fails immediately.
3. Keep existing deterministic/idempotency checks.

## Acceptance Criteria
1. No runtime parsing path accepts alternate undocumented payload key names or alternate container shapes.
2. No runtime path fallback for outfits catalog exists.
3. Reporting no longer emits placeholder `UNKNOWN`; it fails on inconsistent relational records.
4. All strict contract tests pass; previous compatibility tests are removed/updated.
5. `make validate-config` and `make test` pass under Python `3.14.3`.
6. Failures are explicit and actionable (endpoint/component + reason).

## Assumptions and Defaults
1. “No fallback” applies to runtime contracts and processing integrity paths, not blanket removal of all config defaults.
2. `source_ambiguous` entries remain permitted but must be fully schema-valid.
3. Any contract mismatch is treated as a data/provider/schema issue and must terminate processing immediately.
