# Make Commands

This file documents the Make targets that remain in this repository and the flags (Make variables) each target can take.

## Targets

| Target | Purpose | Common flags |
|---|---|---|
| `make help` | Print available targets, variables, and examples. | None |
| `make venv` | Create/repair `.venv` and enforce Python `3.14.3`. | None |
| `make install` | Install package + dev dependencies into `.venv` (`-e .[dev]`). | None |
| `make validate-config` | Validate config schema and settings. | `CONFIG` |
| `make discover-range` | Discover earliest available bars and write readiness range manifest. | `CONFIG`, `SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `DISCOVER_START`, `READINESS_END`, `DISCOVER_RANGE_OUTPUT` |
| `make verify-readiness` | Verify readiness acceptance checks and write JSON summary. | `CONFIG`, `START`, `END`, `SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `READINESS_ACCEPTANCE_OUTPUT` |
| `make test` | Run the test suite. | None |
| `make dead-code-check` | Run dead-code gate via `vulture`. | None |
| `make backfill` | Backfill bars for selected symbols/timeframes/date range. | `CONFIG`, `START`, `END`, `SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `PROFILE` |
| `make replay` | Replay routes/signals for selected symbols/timeframes/date range. | `CONFIG`, `START`, `END`, `SYMBOLS`, `TIMEFRAMES`, `UNIVERSE`, `TIMEFRAME_SET`, `PROFILE` |
| `make run-live` | Run live execution path. | `CONFIG` |
| `make report` | Build report artifacts. | `CONFIG`, `REPORT_RANGE` |
| `make preflight-storage` | Check free disk space for large profiles before heavy runs. | `PROFILE`, `MIN_FREE_GB` |
| `make e2e` | End-to-end orchestrator for `validate-config`, `backfill`, `replay`, `report` by stage. | `CONFIG`, `PROFILE`, `STAGES`, `UNIVERSE`, `TIMEFRAME_SET`, `START`, `END`, `SYMBOLS`, `TIMEFRAMES`, `ANALYSIS_START`, `ANALYSIS_END`, `WARMUP_DAYS`, `BACKFILL_START`, `BACKFILL_END`, `REPLAY_START`, `REPLAY_END`, `REPORT_RANGE`, `MIN_FREE_GB` |
| `make clean` | Remove artifacts, caches, and build outputs (keeps `.venv`). | None |
| `make clean-all` | Run `clean` and also remove `.venv`. | None |

## Flag Reference

### Core config and selection

- `CONFIG`: Path to YAML config file. Default: `configs/settings.example.yaml`.
- `PROFILE`: Preset range profile for runs. Allowed: `smoke`, `day`, `week`, `month`, `max`, `custom`.
- `UNIVERSE`: Symbol set preset. Allowed: `core`, `core_expanded`, `all_stocks`, `all`.
  - `core` -> `QQQ,RWM`
  - `core_expanded` -> curated expanded list
  - `all_stocks` -> fixed 39-symbol stock list in `Makefile`
  - `all` -> do not pass symbol filter to CLI
- `TIMEFRAME_SET`: Timeframe preset. Allowed: `core` (`30m,1h`) or `all` (no timeframe filter).
- `SYMBOLS`: CSV override for symbols. If set, this overrides the profile/universe expansion.
- `TIMEFRAMES`: CSV override for timeframes. If set, this overrides `TIMEFRAME_SET` expansion.

### Date/range flags

- `START`: Start timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `END`: End timestamp (`YYYY-MM-DDTHH:MM:SSZ`).
- `MAX_START`: Default start for `PROFILE=max`. Default: `2016-01-01T00:00:00Z`.
- `MAX_END`: Default end for `PROFILE=max`. Default: current UTC at runtime.
- `ANALYSIS_START`: Analysis/report window start for `e2e`. Default: `START`.
- `ANALYSIS_END`: Analysis/report window end for `e2e`. Default: `END`.
- `WARMUP_DAYS`: Warmup days subtracted from `ANALYSIS_START` to derive warmup start. Default: `120`.
- `BACKFILL_START`: Backfill start for `e2e`. Default: computed warmup start.
- `BACKFILL_END`: Backfill end for `e2e`. Default: `ANALYSIS_END`.
- `REPLAY_START`: Replay start for `e2e`. Default: computed warmup start.
- `REPLAY_END`: Replay end for `e2e`. Default: `ANALYSIS_END`.

### E2E/report orchestration

- `STAGES`: CSV subset of `validate-config,backfill,replay,report`. Invalid values hard-fail.
- `REPORT_RANGE`: `start,end` window for `report`.
  - For standalone `make report`, passed directly.
  - For `make e2e`, defaults to `ANALYSIS_START,ANALYSIS_END` if unset.
- `FEATURES`: Explicitly validated feature flags. `cross_symbol_context` is intentionally rejected at runtime; use config key `route.cross_symbol_context`.

### Readiness-specific flags

- `DISCOVER_START`: Earliest probe start used by `discover-range`. Default: `2000-01-01T00:00:00Z`.
- `READINESS_END`: End timestamp used in readiness runs. Default: `MAX_END`.
- `DISCOVER_RANGE_OUTPUT`: Output JSON path for `discover-range`. Default: `artifacts/readiness/discovered_range_manifest.json`.
- `READINESS_ACCEPTANCE_OUTPUT`: Output JSON path for `verify-readiness`. Default: `artifacts/readiness/readiness_acceptance.json`.
- `FULL_RANGE_START`: Convenience variable auto-read from `DISCOVER_RANGE_OUTPUT.full_range_start` when present.

### Storage safety

- `MIN_FREE_GB`: Required free disk threshold used by `preflight-storage` (and therefore `e2e`). Default: `50`.

## Notes on precedence

- Explicit variables passed on the command line (for example `make e2e START=...`) take precedence over profile-derived defaults.
- `SYMBOLS` and `TIMEFRAMES` overrides take precedence over `UNIVERSE` and `TIMEFRAME_SET` presets.
- `PROFILE=custom` requires both `START` and `END`.
