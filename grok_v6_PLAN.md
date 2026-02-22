# Implementation Plan: Full-History Validation (Stocks + Crypto) Before Live Paper Trading

## Goal
Run a max-date historical validation pass before live paper trading so readiness is based on multi-regime behavior, not only 2025.

## Decision
Crypto stays included in scope (`BTC/USD`, `ETH/USD`) alongside stocks. We will run both stock-only and all-asset passes because current readiness tooling is stock-focused.

## Constraints From Current Codebase
1. `discover-range` is stock-only and writes `full_range_start` for stocks.
2. `verify-readiness` is stock-only for coverage checks.
3. `make e2e` supports explicit `PROFILE=custom`, `START`, `END`, `WARMUP_DAYS`, `UNIVERSE`, and `TIMEFRAME_SET`.
4. Backfill fails fast if a symbol/timeframe has no usable bars after fetch/session filtering (`ingest.empty_source_policy=fail`).

## Phase 0: Required Full-History Readiness Run

### Step 0.1: Discover Full Stock Range
Run discovery first so stock start is data-driven, not guessed.

```powershell
make discover-range CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml UNIVERSE=all_stocks TIMEFRAME_SET=all READINESS_END=2026-02-21T23:59:59Z
```

Expected artifact:
- `artifacts/readiness/discovered_range_manifest.json` with `full_range_start`.

### Step 0.2: Full-History Stock E2E Baseline (Deterministic Gate)
Use discovered stock start for the strict baseline run.

```powershell
$env:FULL_RANGE_START = (Get-Content artifacts/readiness/discovered_range_manifest.json -Raw | ConvertFrom-Json).full_range_start
make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=$env:FULL_RANGE_START END=2026-02-21T23:59:59Z UNIVERSE=all_stocks TIMEFRAME_SET=all WARMUP_DAYS=365 STAGES=validate-config,backfill,replay,report
```

### Step 0.3: Full-History All-Asset E2E (Include Crypto)
Run combined stocks + crypto over long history for full system behavior.

```powershell
make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=2018-01-01T00:00:00Z END=2026-02-21T23:59:59Z UNIVERSE=all TIMEFRAME_SET=all WARMUP_DAYS=365 STAGES=validate-config,backfill,replay,report
```

### Step 0.4: Focused Comparison Reports From the Same Event Store
Generate targeted reports to compare full-history vs recent behavior.

```powershell
make report CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml REPORT_RANGE=2025-01-01T00:00:00Z,2025-12-31T23:59:59Z
make report CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml REPORT_RANGE=2026-01-01T00:00:00Z,2026-02-21T23:59:59Z
```

### Step 0.5: Run Readiness Acceptance (Stock Coverage Contract)
This is still required because it validates monotonicity, boundary coverage, and gap quality.

```powershell
make verify-readiness CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml START=$env:FULL_RANGE_START END=2026-02-21T23:59:59Z UNIVERSE=all_stocks TIMEFRAME_SET=all
```

## Artifacts To Review Before Live Stage
1. Run manifests under `artifacts/svix211_106/runs/.../run_manifest.json`.
2. Reports under `artifacts/svix211_106/reports/*.md` and `*.csv` for full-range and focused windows.
3. Event streams under `artifacts/svix211_106/events/` (`strikes.jsonl`, `signals.jsonl`, `positions.jsonl`, `archive.jsonl`).
4. Coverage outputs under `artifacts/readiness/_coverage_details.csv` and `artifacts/readiness/_coverage_quality.json`.
5. Readiness acceptance manifest under `artifacts/readiness/readiness_acceptance.json`.

## Exit Criteria To Proceed To Live Paper Trading
1. Full-history stock run succeeds end-to-end with no stage failure.
2. Full-history all-asset run succeeds with crypto included.
3. `verify-readiness` passes for stock coverage/gap quality checks.
4. Report metrics are directionally stable across:
- full-history window,
- 2025 window,
- 2026 YTD window.
5. No unresolved artifact-level anomalies (schema breaks, duplicate-event explosions, persistent missing partitions).

## Phase 1 After Phase 0 Passes
Implement outbound paper order submission and reconciliation-complete live execution path (the current known live gap), then run a 30-day unattended paper validation.

## Assumptions and Defaults
1. End date is fixed to `2026-02-21T23:59:59Z` for reproducibility of this plan.
2. `WARMUP_DAYS=365` is used for long-history replay stability.
3. If the all-asset run fails due data availability on specific pairs, rerun segmented windows but keep the same config and preserve all failure evidence.
