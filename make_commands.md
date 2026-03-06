# Make Commands

This file documents the current `Makefile` interface. The supported runtime profile contract is `strict` and `context` only.

`context` is the default operational source-aligned lane. `strict` is the baseline research/comparator lane. `CONFIG_PROFILE=replication` is no longer supported and hard-fails.

## Targets

| Target | Purpose | Common flags |
|---|---|---|
| `make help` | Print targets, variables, and examples derived from the `Makefile`. | None |
| `make venv` | Create or repair `.venv` and enforce Python `3.14.3`. | None |
| `make install` | Install the package and dev dependencies into `.venv`. | None |
| `make validate-config` | Validate the active config file. | `CONFIG_PROFILE`, config path overrides |
| `make discover-range` | Discover earliest available bars and write a manifest. | `CONFIG_PROFILE`, selection flags, `DISCOVER_START`, `READINESS_END`, `DISCOVER_RANGE_OUTPUT` |
| `make verify-readiness` | Run readiness acceptance checks and write a JSON summary. | `CONFIG_PROFILE`, selection flags, `START`, `END`, `READINESS_ACCEPTANCE_OUTPUT`, `VERIFY_READINESS_ARGS` |
| `make paper-hardening-init` | Generate the Part 2 hardening scaffold manifest. | `CONFIG_PROFILE`, `PAPER_HARDENING_INIT_OUTPUT` |
| `make phase2-preflight` | Run `paper-hardening-init` and `test-part2-components` in sequence. | `CONFIG_PROFILE`, `PAPER_HARDENING_INIT_OUTPUT`, `PART2_TEST_PATHS` |
| `make test-part2-components` | Run the Part 2 component gate tests. | `PART2_TEST_PATHS` |
| `make test` | Run the full test suite. | None |
| `make dead-code-check` | Run the dead-code gate via `vulture`. | None |
| `make backfill` | Backfill selected symbols and timeframes over `START..END`. | `CONFIG_PROFILE`, selection flags, `START`, `END` |
| `make replay` | Replay selected symbols and timeframes over `START..END`. | `CONFIG_PROFILE`, selection flags, `START`, `END` |
| `make run-live` | Run the live execution path. | `CONFIG_PROFILE`, `RUN_LIVE_ARGS` |
| `make report` | Build report artifacts. | `CONFIG_PROFILE`, `REPORT_RANGE` |
| `make migrate-storage-layout` | Migrate storage layout in non-dry-run mode. | `CONFIG_PROFILE` |
| `make preflight-storage` | Check free disk space before heavy profiles. | `PROFILE`, `MIN_FREE_GB` |
| `make e2e` | Orchestrate `validate-config`, `backfill`, `replay`, and `report`, then write a run manifest. | `CONFIG_PROFILE`, range flags, selection flags, stage flags, warmup/report flags |
| `make phase1-close` | Run the 2-profile x 2-pass deterministic Phase 1 recheck protocol and archive manifests. | `PHASE1_CLOSE_*`, `VERIFY_READINESS_ARGS` |
| `make clean` | Remove artifacts, caches, and build outputs while keeping `.venv`. | None |
| `make clean-all` | Run `clean` and also remove `.venv`. | None |

## Core Flags

- `CONFIG_PROFILE`: Allowed values are `strict`, `context`. Default: `context`.
- `STRICT_CONFIG_PATH`: Default strict config path.
- `CONTEXT_CONFIG_PATH`: Default context config path.
- `ACTIVE_CONFIG`: Derived from `CONFIG_PROFILE`. Invalid profiles hard-fail.
- `PROFILE`: Range preset. Allowed values: `smoke`, `day`, `week`, `month`, `max`, `max_common`, `custom`.
- `UNIVERSE`: Symbol preset. Allowed values: `core`, `core_expanded`, `all_stocks`, `all`.
- `TIMEFRAME_SET`: Timeframe preset. Allowed values: `core`, `all`.
- `SYMBOLS`: CSV symbol override.
- `TIMEFRAMES`: CSV timeframe override.
- `BACKFILL_SYMBOLS`, `BACKFILL_TIMEFRAMES`: Stage-specific backfill overrides.
- `REPLAY_SYMBOLS`, `REPLAY_TIMEFRAMES`: Stage-specific replay overrides.
- `STAGES`: CSV subset of `validate-config,backfill,replay,report` used by `make e2e`.

## Range and Readiness Flags

- `START`, `END`: Explicit UTC timestamps. Required when `PROFILE=custom`.
- `ALPACA_BASIC_HISTORICAL_START`: Default free-tier historical anchor.
- `ALPACA_BASIC_HISTORICAL_DELAY_MINUTES`: Default historical lag offset.
- `MAX_START`, `MAX_END`: Derived bounds for `PROFILE=max`.
- `DISCOVER_START`: Lower bound probe start for `discover-range`.
- `READINESS_END`: Upper bound for readiness/discovery workflows.
- `DISCOVER_RANGE_OUTPUT`: Output path for `discover-range`.
- `READINESS_ACCEPTANCE_OUTPUT`: Output path for `verify-readiness`.
- `FULL_RANGE_START`: Auto-loaded from `DISCOVER_RANGE_OUTPUT.full_range_start` when present.
- `COMMON_ANALYSIS_START`: Auto-computed analysis start for `PROFILE=max_common`.
- `WARMUP_DAYS`: Warmup length used by `make e2e`.
- `ANALYSIS_START`, `ANALYSIS_END`: Analysis/report window used by `make e2e`.
- `WARMUP_START`: Computed warmup boundary.
- `BACKFILL_START`, `BACKFILL_END`: Backfill window used by `make e2e`.
- `REPLAY_START`, `REPLAY_END`: Replay window used by `make e2e`.
- `REPORT_RANGE`: Report window. For `make e2e`, defaults to `ANALYSIS_START,ANALYSIS_END`.
- `VERIFY_READINESS_ARGS`: Extra flags appended to `verify-readiness`.

## Phase 2 Flags

- `PAPER_HARDENING_INIT_OUTPUT`: Output path for `paper-hardening-init`.
- `PART2_TEST_PATHS`: Pytest paths used by `test-part2-components`.
- `RUN_LIVE_ARGS`: Extra flags forwarded to `run-live`.

## Phase 1 Closure Flags

- `PHASE1_CLOSE_PROFILE`: `e2e` profile used during closure. Default: `custom`.
- `PHASE1_CLOSE_START`, `PHASE1_CLOSE_END`: Fixed closure timestamps.
- `PHASE1_CLOSE_SYMBOLS`, `PHASE1_CLOSE_TIMEFRAMES`: Fixed closure selection scope.
- `PHASE1_CLOSE_STAGES`: `e2e` stage list used during closure.
- `PHASE1_CLOSE_OUTPUT`: Summary JSON path. Default: `artifacts/readiness/phase1_recheck_acceptance.json`.
- `PHASE1_CLOSE_LABEL`: Label suffix used in per-pass manifest names. Default: `phase1recheck`.
- `PHASE1_CLOSE_ARCHIVE_ROOT`: Root directory used for archived per-pass manifests. Default: `audit/phase1_rechecks`.

## Storage Safety

- `MIN_FREE_GB`: Free disk threshold enforced by `preflight-storage` and `make e2e` for heavier profiles.

## Precedence Notes

- Command-line variable overrides take precedence over profile-derived defaults.
- `SYMBOLS` and `TIMEFRAMES` override `UNIVERSE` and `TIMEFRAME_SET`.
- Stage-specific symbol/timeframe flags override the base `SYMBOLS` and `TIMEFRAMES`.
- `make phase2-preflight` reuses whatever `CONFIG_PROFILE` and output/test overrides you pass to the top-level command.

## Common Examples

```powershell
make e2e
make e2e CONFIG_PROFILE=strict PROFILE=max_common UNIVERSE=all TIMEFRAME_SET=all
make verify-readiness CONFIG_PROFILE=context START=$env:FULL_RANGE_START END=$env:READINESS_END UNIVERSE=all_stocks TIMEFRAME_SET=all
make phase1-close
make phase2-preflight CONFIG_PROFILE=context
make run-live CONFIG_PROFILE=context RUN_LIVE_ARGS='--runtime-minutes 30 --lookback-hours 8'
```
