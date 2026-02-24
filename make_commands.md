# Make Commands

This file documents the Make targets in this repository and the flags (Make variables) each target can take.

## Targets

| Target | Purpose | Common flags |
|---|---|---|
| `make help` | Print available targets, variables, and examples. | None |
| `make venv` | Create/repair `.venv` and enforce Python `3.14.3`. | None |
| `make install` | Install package + dev dependencies into `.venv` (`-e .[dev]`). | None |
| `make validate-config` | Validate config schema and settings. | `CONFIG` |
| `make discover-range` | Discover earliest available bars and write readiness range manifest. | `CONFIG`, `SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `DISCOVER_START`, `READINESS_END`, `DISCOVER_RANGE_OUTPUT` |
| `make verify-readiness` | Verify readiness acceptance checks and write JSON summary. | `CONFIG`, `START`, `END`, `SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `READINESS_ACCEPTANCE_OUTPUT`, `VERIFY_READINESS_ARGS` |
| `make lane` | Unified validation lane runner. `LANE=strict` runs canonical lane; `LANE=replication` runs replication lane. | `LANE`, `LANE_STRICT_*`, `LANE_REPLICATION_*` (including required `LANE_REPLICATION_END`), plus standard `PROFILE`/range flags |
| `make test` | Run the test suite. | None |
| `make dead-code-check` | Run dead-code gate via `vulture`. | None |
| `make backfill` | Backfill bars for selected symbols/timeframes/date range. | `CONFIG`, `START`, `END`, `BACKFILL_SYMBOLS`, `BACKFILL_TIMEFRAMES`, plus selection defaults (`SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `PROFILE`) |
| `make replay` | Replay routes/signals for selected symbols/timeframes/date range. | `CONFIG`, `START`, `END`, `REPLAY_SYMBOLS`, `REPLAY_TIMEFRAMES`, plus selection defaults (`SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `PROFILE`) |
| `make run-live` | Run live execution path. | `CONFIG` |
| `make report` | Build report artifacts. | `CONFIG`, `REPORT_RANGE` |
| `make migrate-storage-layout` | Migrate storage layout in non-dry-run mode. | `CONFIG` |
| `make preflight-storage` | Check free disk space for large profiles before heavy runs. | `PROFILE`, `MIN_FREE_GB` |
| `make e2e` | End-to-end orchestrator for `validate-config`, `backfill`, `replay`, `report` by stage, then writes run manifest. | `CONFIG`, `PROFILE`, `STAGES`, `UNIVERSE`, `TIMEFRAME_SET`, `START`, `END`, `SYMBOLS`, `TIMEFRAMES`, `BACKFILL_SYMBOLS`, `BACKFILL_TIMEFRAMES`, `REPLAY_SYMBOLS`, `REPLAY_TIMEFRAMES`, `ANALYSIS_START`, `ANALYSIS_END`, `WARMUP_DAYS`, `WARMUP_START`, `BACKFILL_START`, `BACKFILL_END`, `REPLAY_START`, `REPLAY_END`, `REPORT_RANGE`, `MIN_FREE_GB` |
| `make clean` | Remove artifacts, caches, and build outputs (keeps `.venv`). | None |
| `make clean-all` | Run `clean` and also remove `.venv`. | None |

## Flag Reference

### Core config and selection

- `CONFIG`: Path to YAML config file. Default: `configs/settings.example.yaml`.
- `PROFILE`: Preset range profile for runs. Allowed: `smoke`, `day`, `week`, `month`, `max`, `custom`.
- `UNIVERSE`: Symbol set preset. Allowed: `core`, `core_expanded`, `all_stocks`, `all`.
  - `core` -> `QQQ,RWM`
  - `core_expanded` -> curated expanded list
  - `all_stocks` -> fixed symbol list in `Makefile`
  - `all` -> do not pass symbol filter to CLI
- `TIMEFRAME_SET`: Timeframe preset. Allowed: `core` (`30m,1h`) or `all` (no timeframe filter).
- `SYMBOLS`: CSV override for symbols. If set, this overrides the profile/universe expansion.
- `TIMEFRAMES`: CSV override for timeframes. If set, this overrides `TIMEFRAME_SET` expansion.
- `BACKFILL_SYMBOLS`: CSV override used by `make backfill` and `make e2e` backfill stage. Default: `SYMBOLS`.
- `BACKFILL_TIMEFRAMES`: CSV override used by `make backfill` and `make e2e` backfill stage. Default: `TIMEFRAMES`.
- `REPLAY_SYMBOLS`: CSV override used by `make replay` and `make e2e` replay stage. Default: `SYMBOLS`.
- `REPLAY_TIMEFRAMES`: CSV override used by `make replay` and `make e2e` replay stage. Default: `TIMEFRAMES`.
- `STAGES`: CSV subset of `validate-config,backfill,replay,report` for `make e2e`. Invalid values hard-fail.
- `LANE`: Validation lane selector for `make lane`. Allowed: `strict`, `replication`.

### Date/range flags

- `START`: Start timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `END`: End timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `ALPACA_BASIC_HISTORICAL_START`: Free-tier historical start anchor. Default: `2016-01-01T00:00:00Z`.
- `ALPACA_BASIC_HISTORICAL_DELAY_MINUTES`: Free-tier historical delay offset. Default: `15`.
- `MAX_START`: Default start for `PROFILE=max`. Default: `ALPACA_BASIC_HISTORICAL_START`.
- `MAX_END`: Default end for `PROFILE=max`. Default: current UTC minus `ALPACA_BASIC_HISTORICAL_DELAY_MINUTES`.
- `ANALYSIS_START`: Analysis/report window start for `e2e`. Default: `START`.
- `ANALYSIS_END`: Analysis/report window end for `e2e`. Default: `END`.
- `WARMUP_DAYS`: Warmup days subtracted from `ANALYSIS_START` to derive warmup start. Default: `120`.
- `WARMUP_START`: Warmup start timestamp. Default: computed from `ANALYSIS_START - WARMUP_DAYS`.
- `BACKFILL_START`: Backfill start for `e2e`. Default: computed warmup start.
- `BACKFILL_END`: Backfill end for `e2e`. Default: `ANALYSIS_END`.
- `REPLAY_START`: Replay start for `e2e`. Default: computed warmup start.
- `REPLAY_END`: Replay end for `e2e`. Default: `ANALYSIS_END`.

### E2E/report orchestration

- `REPORT_RANGE`: `start,end` window for `report`.
  - For standalone `make report`, passed directly.
  - For `make e2e`, defaults to `ANALYSIS_START,ANALYSIS_END` if unset.

### Readiness-specific flags

- `DISCOVER_START`: Earliest probe start used by `discover-range`. Default: `ALPACA_BASIC_HISTORICAL_START`.
- `READINESS_END`: End timestamp used in readiness runs. Default: `MAX_END`.
- `DISCOVER_RANGE_OUTPUT`: Output JSON path for `discover-range`. Default: `artifacts/readiness/discovered_range_manifest.json`.
- `READINESS_ACCEPTANCE_OUTPUT`: Output JSON path for `verify-readiness`. Default: `artifacts/readiness/readiness_acceptance.json`.
- `FULL_RANGE_START`: Convenience variable auto-read from `DISCOVER_RANGE_OUTPUT.full_range_start` when present.
- `VERIFY_READINESS_ARGS`: Extra flags appended to `verify-readiness` CLI invocation (for example `--require-academic-validation`).
- `LANE_STRICT_SYMBOLS`: Strict-lane symbols for `make lane LANE=strict`. Default: `QQQ,SPY,TQQQ,SQQQ,SVIX,VIXY`.
- `LANE_STRICT_TIMEFRAMES`: Strict-lane timeframes for `make lane LANE=strict`. Default: `30m,1h`.
- `LANE_STRICT_CONFIG_OVERRIDE`: Optional strict-lane config override consumed by `LANE_STRICT_CONFIG`.
- `LANE_STRICT_CONFIG`: Effective strict-lane config (`LANE_STRICT_CONFIG_OVERRIDE` when set, otherwise `CONFIG`).
- `LANE_REPLICATION_CONFIG`: Replication-lane config for `make lane LANE=replication`. Default: `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`.
- `LANE_REPLICATION_SYMBOLS`: Replication-lane symbols. Default: `QQQ,SPY,TQQQ,SQQQ,SVIX,VIXY,XLF,SMH,SOXL`.
- `LANE_REPLICATION_TIMEFRAMES`: Replication-lane timeframes. Default: `30m,1h,2h`.
- `LANE_REPLICATION_DISCOVER_OUTPUT`: Replication discover manifest path. Default: `artifacts/readiness/discovered_range_replication.json`.
- `LANE_STRICT_READINESS_OUTPUT`: Strict-lane readiness output path. Default: `artifacts/readiness/strict/readiness_acceptance.json`.
- `LANE_REPLICATION_END`: Replication-lane end timestamp. Required for `make lane LANE=replication`.
- `LANE_REPLICATION_FULL_RANGE_START`: Convenience variable auto-read from `LANE_REPLICATION_DISCOVER_OUTPUT.full_range_start` when present.
- `LANE_REPLICATION_READINESS_OUTPUT`: Replication-lane readiness output path. Default: `artifacts/readiness/replication/readiness_acceptance.json`.

### Storage safety

- `MIN_FREE_GB`: Required free disk threshold used by `preflight-storage` (and therefore `e2e`). Default: `50`.

## Notes on precedence

- Explicit variables passed on the command line (for example `make e2e START=...`) take precedence over profile-derived defaults.
- `SYMBOLS` and `TIMEFRAMES` overrides take precedence over `UNIVERSE` and `TIMEFRAME_SET` presets.
- `BACKFILL_SYMBOLS`/`BACKFILL_TIMEFRAMES` and `REPLAY_SYMBOLS`/`REPLAY_TIMEFRAMES` override stage-specific symbol/timeframe scope.
- `PROFILE=custom` requires both `START` and `END`.
