# Assumptions and Ambiguities

## Runtime and Execution
1. Python `3.14.3` is mandatory and validated at CLI runtime and via `make setup MODE=venv`.
2. Workflows are only exposed via `Makefile` targets.
3. Required Alpaca keys are loaded from `.env.local`; missing keys are hard errors.

## Profile Operations
1. Default CLI/Make operational profile is `context`.
2. `context` is the official operational lane; only `strict` and `context` are supported runtime profiles.
3. `strict` remains the baseline comparison lane for research and robustness validation; `replication` is historical only.
4. Phase 1 closure runs through `make run ACTION=phase1-close`.
5. Part 2 preflight runs through `make run ACTION=phase2-preflight`, which sequences `make run ACTION=paper-hardening-init` and `make qa SUITE=part2`.

## Data and Market Logic
1. Session filtering defaults to regular U.S. hours (`09:30-16:00 America/New_York`) for non-crypto symbols.
2. Crypto symbols are detected by `/` (for example, `BTC/USD`) and bypass regular-session filtering.
3. SMA input price is `strategy.price_basis` (`ohlc4` default, `close` optional).
4. Active strike trigger is `strategy.trigger_mode=close_touch_or_cross`; `signal.trigger_mode` is metadata-only.
5. Reporting uses canonical `both` attribution only: `attribution_mode="both"` with explicit `strike_attribution` and `close_attribution` payloads.
6. Free Alpaca runs are bar-based approximations and cannot reproduce tick/second/millisecond source precision.

## Signal and Risk Logic
1. Entry is anchored to struck SMA value (rounded to 2 decimals).
2. Side is route-driven (`LONG`/`SHORT` from `strategy.routes[*].side`).
3. Long invalidation is `entry - 0.01`; short invalidation is `entry + 0.01`.
4. For close-only risk modes (`singular_penny_only`, `penny_reference_break`), `partial_take_r`, `final_take_r`, and `timeout_bars` are inactive defaults.
5. Close reasons in close-only profiles are expected to be rule-based stops/cuts (for example `penny_reference_break`, `cross_symbol_reference_break`).
6. Risk migration uses explicit `risk.migrations` rules in config.
7. Confluence filters are route-local (touch/cross + outfit alignment + volume spike) and disabled by default unless explicitly enabled per route.
8. Route tolerance applies uniformly across key, micro, and confluence SMA comparisons (LONG uses `close >= sma - tolerance`, SHORT uses `close <= sma + tolerance`).
9. `atr_dynamic_stop` and `cross_symbol_context` are supported in both replay and live paths when configured.
10. Canonical SVIX outfit notation is `26/52/106/211/422/844` (`svix_211_106`); operative strike level is route/context-specific by profile.

## Source Catalog Ambiguity
1. README rows that are malformed or semantically incomplete are preserved in `src/sma_outfits/config/outfits.yaml` with `source_ambiguous: true`.
2. Ambiguous rows retain original integer sequences and raw source text.

## Fallback Inventory (Preserved)
1. `src/sma_outfits/live/runner.py` reconnect loop with exponential backoff is preserved unchanged.
2. `src/sma_outfits/data/alpaca_clients.py` stale-feed detection and heartbeat timeout fallback handling are preserved unchanged.
3. Duplicate-bar idempotency semantics in live ingestion/persistence remain preserved.
