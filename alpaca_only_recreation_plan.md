# Alpaca-Only Python Recreation Plan for SMA-Outfits

## Brief Summary
Build a new Python codebase that reproduces the repository’s observable workflow: ingest market data, compute multi-timeframe SMA outfits, detect precision strikes, classify signal events, and generate structured archive logs plus threaded Markdown records. The implementation will use only free Alpaca data and will be configuration-first so undocumented behavior remains adjustable without code changes.

## Environment and Execution Requirements
1. Python runtime is fixed to **3.14.3**.
2. Development and runtime must use a local `venv`.
3. All project operations are invoked via `Makefile` targets only.
4. Runtime credentials are sourced from `.env.local` (no credential fallbacks).

## Scope and Success Criteria
1. Deliver a runnable Python package with CLI and config-driven live/replay workflows.
2. Support outfit detection across the README outfit catalog and required timeframes.
3. Persist raw/processed data and signal events locally.
4. Generate archival outputs as machine-friendly logs (JSONL event/archive records) plus threaded Markdown entries.
5. Provide deterministic backtest/replay and automated tests.
6. Do not place real broker orders in v1 (alerting/simulation only).

## Explicit Assumptions and Defaults
1. `@rauItrades` and `@UnfairMarket` are treated as the same account history.
2. Data source is strictly Alpaca Data API (free tier); no Lightspeed/Webull/Polygon/yfinance.
3. Index proxies are fixed as: `SPX->SPY`, `IXIC/NDX->QQQ`, `DJI->DIA`, `VIX->VIXY`.
4. SMA input price is `close` for all bars.
5. Strike tolerance is fixed at `0.01`.
6. Strike trigger is bar-touch: signal when `bar.low <= sma <= bar.high` (with `±0.01` tolerance).
7. Direction default is `LONG` if `bar.close >= sma`, else `SHORT`.
8. Long invalidation is `entry - 0.01`; short invalidation is `entry + 0.01`.
9. Session filter default is regular US hours only (`09:30–16:00 America/New_York`).
10. Extended-hours processing is disabled by default and enabled only via config flag.
11. Risk migration is supported only by explicit config mapping rules.
12. Partial profit default is deterministic: take `25%` at `+1R`, move stop to breakeven, close remainder at `+3R` or stop.
13. Program termination default is objective timeout: exit after `120` bars without new directional extreme.
14. Ambiguous outfit rows in README are preserved exactly as listed integers and marked `source_ambiguous=true`.

## Public APIs, Interfaces, and Types
### CLI Commands
| Command | Purpose | Key Inputs | Outputs |
|---|---|---|---|
| `sma-outfits validate-config` | Validate YAML config | `--config` | exit code + validation report |
| `sma-outfits backfill` | Pull Alpaca historical bars | `--symbols --start --end --timeframes` | parquet datasets + ingest log |
| `sma-outfits run-live` | Live stream + detect + archive | `--config` | live signal stream + JSONL archive/event logs + markdown artifacts |
| `sma-outfits replay` | Deterministic historical replay | `--config --start --end` | signal events + performance summary |
| `sma-outfits report` | Build summary docs | `--date` or `--range` | markdown and csv reports |

### Makefile Contract (Required)
| Target | Purpose |
|---|---|
| `make venv` | Create `.venv` with Python 3.14.3 |
| `make install` | Install dependencies into `.venv` |
| `make validate-config` | Validate runtime and YAML config |
| `make test` | Run full test suite |
| `make backfill` | Run historical data backfill |
| `make replay` | Run deterministic replay |
| `make run-live` | Run live signal pipeline |
| `make report` | Generate markdown/csv reports |

### Config Schema (`config/settings.yaml`)
| Key | Type | Default |
|---|---|---|
| `alpaca.api_key` | string | required |
| `alpaca.secret_key` | string | required |
| `alpaca.base_url` | string | `https://paper-api.alpaca.markets` |
| `alpaca.data_feed` | string | `iex` |
| `universe.symbols` | list[string] | curated default list |
| `universe.proxy_map` | map[string,string] | fixed mapping above |
| `sessions.regular_only` | bool | `true` |
| `sessions.extended_enabled` | bool | `false` |
| `timeframes.live` | list[string] | `1m,2m,3m,5m,10m,15m,20m,30m,1h,2h,4h,1D` |
| `timeframes.derived` | list[string] | `1W,1M,1Q` |
| `signal.tolerance` | float | `0.01` |
| `signal.trigger_mode` | string | `bar_touch` |
| `risk.long_break` | float | `0.01` |
| `risk.short_break` | float | `0.01` |
| `risk.partial_take_r` | float | `1.0` |
| `risk.final_take_r` | float | `3.0` |
| `risk.timeout_bars` | int | `120` |
| `archive.enabled` | bool | `true` |
| `archive.root` | string | `artifacts/` |

### Core Event Types
| Type | Required Fields |
|---|---|
| `BarEvent` | `symbol, timeframe, ts, open, high, low, close, volume, source` |
| `SMAState` | `symbol, timeframe, period, value, ts` |
| `StrikeEvent` | `id, symbol, timeframe, outfit_id, period, sma_value, bar_ts, tolerance, trigger_mode` |
| `SignalEvent` | `id, strike_id, side, signal_type, entry, stop, confidence, session_type` |
| `PositionEvent` | `id, signal_id, action, qty, price, reason, ts` |
| `ArchiveRecord` | `signal_id, markdown_path, artifact_type, caption, ts` |

## Repository Structure to Create
| Path | Responsibility |
|---|---|
| `pyproject.toml` | packaging, dependencies, scripts |
| `src/sma_outfits/cli.py` | Typer CLI entrypoint |
| `src/sma_outfits/config/models.py` | Pydantic config models |
| `src/sma_outfits/config/outfits.yaml` | canonical outfit catalog from README |
| `src/sma_outfits/data/alpaca_clients.py` | Alpaca REST + stream adapters |
| `src/sma_outfits/data/ingest.py` | backfill pipelines |
| `src/sma_outfits/data/resample.py` | timeframe aggregation |
| `src/sma_outfits/data/storage.py` | parquet + duckdb IO |
| `src/sma_outfits/indicators/sma_engine.py` | incremental SMA computations |
| `src/sma_outfits/signals/detector.py` | strike detection logic |
| `src/sma_outfits/signals/classifier.py` | signal-type classification |
| `src/sma_outfits/risk/manager.py` | stops, partials, timeout rules |
| `src/sma_outfits/archive/thread_writer.py` | markdown thread append/write |
| `src/sma_outfits/replay/engine.py` | historical replay loop |
| `src/sma_outfits/monitoring/logging.py` | structured logs/metrics |
| `tests/` | unit/integration/e2e tests |
| `configs/settings.example.yaml` | starter config |
| `.env.local` | local Alpaca credentials and runtime environment values |
| `Makefile` | single orchestration interface for all project tasks |

## Implementation Phases
1. Foundation and scaffolding.  
Create package, dependency lock, CLI shell, config validation, logging, and artifact directories.  
Acceptance: `validate-config` passes with sample config and CLI help exposes all commands.

2. Alpaca data layer.  
Implement historical backfill and live websocket ingestion for stocks/ETFs and crypto; normalize into `BarEvent`; enforce ET timezone and session tags.  
Acceptance: bars for configured symbols/timeframes are stored with no schema drift.

3. Storage and resampling.  
Store raw and processed bars in partitioned parquet (`symbol/date/timeframe`) and register in DuckDB; implement deterministic timeframe resampler for `2m,3m,10m,20m,1h,2h,4h,1W,1M,1Q`.  
Acceptance: resampled bars match expected OHLCV aggregation math.

4. Outfit and SMA engine.  
Load outfit catalog from YAML; compute SMA 1–999 support with incremental rolling sums; maintain per symbol/timeframe caches.  
Acceptance: SMA outputs match pandas reference within floating-point tolerance.

5. Strike and signal pipeline.  
Apply bar-touch detection with fixed tolerance, dedupe per bar/outfit/period, generate `SignalEvent`, assign side/type, and initialize risk state.  
Acceptance: synthetic fixtures produce expected signal count, side, and stop values.

6. Risk and simulation logic.  
Implement deterministic stop handling, partials at `+1R`, final at `+3R`, timeout termination at `120` bars, and config-based risk migration rules.  
Acceptance: replay fixtures produce deterministic position lifecycle events.

7. Archival output.  
Append threaded Markdown entries using fixed templates and persist machine-friendly archive records in JSONL.  
Acceptance: each signal yields one archive JSONL record and one markdown block with stable identifiers/filenames.

8. Replay and reporting.  
Implement `replay` over historical ranges and `report` for daily/period summaries (signal counts, hit rates, R outcomes, top outfits, top symbols).  
Acceptance: end-to-end replay completes and emits report artifacts.

9. Operational hardening.  
Add reconnect logic, stale-feed detection, heartbeat monitoring, idempotent event keys, and structured JSON logs for debugging.  
Acceptance: simulated disconnect tests recover without duplicate events.

## Signal Classification Rules (Deterministic v1)
| Condition | Signal Type |
|---|---|
| `side=LONG` and local drawdown flag true | `precision_buy` |
| `side=LONG` and volatility percentile >= configured threshold | `optimized_buy` |
| `side=SHORT` on strike | `automated_short` |
| active position stop breached by `0.01` | `singular_point_hard_stop` |

`local drawdown flag` is defined as close being below prior `N=20` bar median before strike then reclaiming strike bar close.  
`volatility percentile` uses rolling ATR percentile over `N=100` bars.

## Test Cases and Scenarios
1. Config validation rejects missing Alpaca keys and invalid timeframe strings.
2. SMA engine parity test against pandas for periods `10,50,200,548,840`.
3. Strike detection test for exact touch, near-touch (`0.009`), and miss (`0.011`).
4. Side assignment test for `close >= sma` and `close < sma`.
5. Stop logic tests for long and short singular-penny invalidation.
6. Partial/final/timeout lifecycle tests with deterministic replay fixtures.
7. Risk migration test using AMDL->SMH mapping in config.
8. Session filter test confirming regular-hours-only behavior.
9. Resampler correctness test across all supported derived timeframes.
10. Archive generation test verifies JSONL archive record schema and markdown required caption fields.
11. End-to-end integration test with mocked Alpaca stream.
12. Optional live integration test (gated by env vars) for one symbol, one timeframe, one hour runtime.

## Default Symbol Universe for v1
`SPY, QQQ, DIA, UPRO, TQQQ, SQQQ, UDOW, SDOW, SOXL, SOXS, SVIX, VIXY, XLF, JPM, NVDA, TSLA, AMD, GME, SMH, FAS, FAZ, BTC/USD, ETH/USD`

## Definition of Done
1. All CLI commands run successfully from a clean environment.
2. All workflows execute successfully through `Makefile` targets only.
3. Unit tests and integration tests pass in CI.
4. Live runner can ingest Alpaca data for the default universe for one full session without crash.
5. Replay produces deterministic, repeatable signal outputs on the same dataset.
6. Each detected signal has persisted bar context, archive/event log record, and markdown thread entry.
7. All unresolved author-specific behaviors are configurable and documented in `ASSUMPTIONS.md`.
