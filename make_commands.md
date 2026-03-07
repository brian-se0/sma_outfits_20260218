# Make Commands

This file documents the current grouped `Makefile` interface.

The supported runtime profile contract is `strict` and `context` only. `context` is the default operational source-aligned lane. `strict` is the baseline research/comparator lane. `CONFIG_PROFILE=replication` is not supported and hard-fails.

## Public Targets Overview

| Public target | Purpose | Default |
|---|---|---|
| `make help` | Print the streamlined interface, dispatcher flags, and examples. | n/a |
| `make setup` | Create or repair `.venv`, enforce Python `3.14.3`, and optionally install dependencies. | `MODE=install` |
| `make run` | Execute the primary workflow selected by `ACTION`. | `ACTION=e2e` |
| `make qa` | Run the QA suite selected by `SUITE`. | `SUITE=full` |
| `make clean` | Remove artifacts, caches, and build outputs. | `SCOPE=default` |

## Dispatcher Flags

- `MODE`: Allowed values are `install`, `venv`. `install` creates or repairs `.venv`, enforces Python `3.14.3`, and installs dependencies. `venv` stops after the environment/bootstrap step.
- `ACTION`: Allowed values are `e2e`, `validate-config`, `discover-range`, `verify-readiness`, `backfill`, `replay`, `report`, `run-live`, `migrate-storage-layout`, `paper-hardening-init`, `phase2-preflight`, `preflight-storage`, `phase1-close`, `pair-batch`.
- `SUITE`: Allowed values are `full`, `part2`, `dead-code`, `all`.
- `SCOPE`: Allowed values are `default`, `all`.

## Run Action Matrix

| Action | Behavior |
|---|---|
| `e2e` | Run storage preflight, staged pipeline steps, and write the run manifest. |
| `validate-config` | Validate the active config file. |
| `discover-range` | Discover earliest available stock-bar coverage and write the manifest. |
| `verify-readiness` | Run readiness acceptance checks and write the JSON summary. |
| `backfill` | Backfill selected symbols and timeframes over `START..END`. |
| `replay` | Replay selected symbols and timeframes over `START..END`. |
| `report` | Build report artifacts, optionally using `REPORT_RANGE`. |
| `run-live` | Run the live execution path. |
| `migrate-storage-layout` | Apply the non-dry-run storage layout migration. |
| `paper-hardening-init` | Generate the Part 2 hardening scaffold manifest. |
| `phase2-preflight` | Run `paper-hardening-init` and then `qa SUITE=part2`. |
| `preflight-storage` | Check free disk space for heavier profiles without installing dependencies. |
| `phase1-close` | Run the deterministic two-profile, two-pass closure harness; default profile is `max_common` with auto-discovered common history per profile. |
| `pair-batch` | Run a manifest-driven sequence of pair-specific `discover-range`, `e2e`, and `verify-readiness` workflows, continue past per-pair failures, and write a batch summary JSON. |

## Shared Domain Flags

- `CONFIG_PROFILE`: Allowed values are `strict`, `context`. Default: `context`.
- `STRICT_CONFIG_PATH`, `CONTEXT_CONFIG_PATH`: Canonical config paths selected by `CONFIG_PROFILE`.
- `PROFILE`: Allowed values are `smoke`, `day`, `week`, `month`, `max`, `max_common`, `custom`.
- `UNIVERSE`: Allowed values are `core`, `core_expanded`, `all_stocks`, `all`.
- `TIMEFRAME_SET`: Allowed values are `core`, `all`.
- `SYMBOLS`, `TIMEFRAMES`: CSV selection overrides.
- `BACKFILL_SYMBOLS`, `BACKFILL_TIMEFRAMES`: Stage-specific backfill overrides.
- `REPLAY_SYMBOLS`, `REPLAY_TIMEFRAMES`: Stage-specific replay overrides.
- `STAGES`: CSV subset of `validate-config,backfill,replay,report` used by `ACTION=e2e`.
- `START`, `END`: Explicit UTC timestamps. Required when `PROFILE=custom`.
- `WARMUP_DAYS`, `ANALYSIS_START`, `ANALYSIS_END`, `WARMUP_START`, `BACKFILL_START`, `BACKFILL_END`, `REPLAY_START`, `REPLAY_END`, `REPORT_RANGE`: e2e window controls.
- `DISCOVER_START`, `READINESS_END`, `DISCOVER_RANGE_OUTPUT`, `READINESS_ACCEPTANCE_OUTPUT`, `VERIFY_READINESS_ARGS`: discovery and readiness controls.
- `PAPER_HARDENING_INIT_OUTPUT`, `PART2_TEST_PATHS`, `RUN_LIVE_ARGS`: Part 2 and live-run controls.
- `PHASE1_CLOSE_PROFILE`, `PHASE1_CLOSE_START`, `PHASE1_CLOSE_END`, `PHASE1_CLOSE_SYMBOLS`, `PHASE1_CLOSE_TIMEFRAMES`, `PHASE1_CLOSE_STAGES`, `PHASE1_CLOSE_OUTPUT`, `PHASE1_CLOSE_LABEL`, `PHASE1_CLOSE_ARCHIVE_ROOT`: Phase 1 closure controls. `PHASE1_CLOSE_PROFILE=max_common` is the default; `PHASE1_CLOSE_START/END` are only needed with `PHASE1_CLOSE_PROFILE=custom`.
- `PAIR_BATCH_MANIFEST_PATH`, `PAIR_BATCH_OUTPUT`, `PAIR_BATCH_FAIL_ON_ANY`: Pair-batch manifest and summary controls.
- `MIN_FREE_GB`: Free disk threshold enforced by `ACTION=preflight-storage` and the `e2e` workflow.

## Common Examples

```powershell
make help
make setup MODE=venv
make setup
make run
make run ACTION=e2e CONFIG_PROFILE=strict PROFILE=max_common UNIVERSE=all TIMEFRAME_SET=all
make run ACTION=verify-readiness CONFIG_PROFILE=context START=$env:FULL_RANGE_START END=$env:READINESS_END UNIVERSE=all_stocks TIMEFRAME_SET=all
make run ACTION=phase1-close
make run ACTION=pair-batch CONFIG_PROFILE=context
make run ACTION=phase1-close PHASE1_CLOSE_PROFILE=custom PHASE1_CLOSE_START=2022-03-31T15:30:00Z PHASE1_CLOSE_END=2026-02-28T23:16:28Z
make run ACTION=phase2-preflight CONFIG_PROFILE=context
make run ACTION=run-live CONFIG_PROFILE=context RUN_LIVE_ARGS='--runtime-minutes 30 --lookback-hours 8'
make qa
make qa SUITE=part2
make qa SUITE=dead-code
make clean SCOPE=all
```

## Legacy-to-New Command Mapping

| Legacy command | Current command |
|---|---|
| `make venv` | `make setup MODE=venv` |
| `make install` | `make setup` |
| `make validate-config` | `make run ACTION=validate-config` |
| `make discover-range` | `make run ACTION=discover-range` |
| `make verify-readiness` | `make run ACTION=verify-readiness` |
| `make paper-hardening-init` | `make run ACTION=paper-hardening-init` |
| `make phase2-preflight` | `make run ACTION=phase2-preflight` |
| `make test-part2-components` | `make qa SUITE=part2` |
| `make test` | `make qa` |
| `make dead-code-check` | `make qa SUITE=dead-code` |
| `make backfill` | `make run ACTION=backfill` |
| `make replay` | `make run ACTION=replay` |
| `make run-live` | `make run ACTION=run-live` |
| `make report` | `make run ACTION=report` |
| `make migrate-storage-layout` | `make run ACTION=migrate-storage-layout` |
| `make preflight-storage` | `make run ACTION=preflight-storage` |
| `make e2e` | `make run ACTION=e2e` |
| `make phase1-close` | `make run ACTION=phase1-close` |
| `make pair-batch` | `make run ACTION=pair-batch` |
| `make clean-all` | `make clean SCOPE=all` |

## Notes on Defaults and Hard-Fail Validation

- `make run` defaults to `ACTION=e2e`.
- `make setup` defaults to `MODE=install`.
- `make qa` defaults to `SUITE=full`.
- `make clean` defaults to `SCOPE=default`.
- Invalid `MODE`, `ACTION`, `SUITE`, and `SCOPE` values fail immediately with explicit allowed-value messages.
- All `run` actions except `preflight-storage` go through `make setup MODE=install` before dispatch.
- `qa SUITE=all` runs `full` and then `dead-code`; it does not include `part2`.
- `clean SCOPE=default` preserves `.venv`; `clean SCOPE=all` also removes `.venv`.
