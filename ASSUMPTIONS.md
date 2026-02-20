# Assumptions and Ambiguities

## Runtime and Execution
1. Python `3.14.3` is mandatory and validated at CLI runtime and via `make check-python`.
2. Workflows are only exposed via `Makefile` targets.
3. Required Alpaca keys are loaded from `.env.local`; missing keys are hard errors.

## Data and Market Logic
1. Session filtering defaults to regular U.S. hours (`09:30-16:00 America/New_York`) for non-crypto symbols.
2. Crypto symbols are detected by `/` (for example, `BTC/USD`) and bypass regular-session filtering.
3. SMA input price is always `close`.
4. Strike trigger uses bar-touch logic with tolerance: `low - tolerance <= sma <= high + tolerance`.
5. Report attribution defaults to `both`; strike-time totals remain top-level in compatibility mode and close-time totals are additive under `close_attribution`.

## Signal and Risk Logic
1. Entry is anchored to struck SMA value (rounded to 2 decimals).
2. Side defaults to `LONG` when `close >= sma`, otherwise `SHORT`.
3. Long invalidation is `entry - 0.01`; short invalidation is `entry + 0.01`.
4. Partial handling is deterministic: `25%` at `+1R`, stop to breakeven, final at `+3R` or stop.
5. Timeout termination is deterministic: close after `120` bars without a new directional extreme.
6. Risk migration uses explicit `risk.migrations` rules in config.
7. Confluence filters are route-local in v1 (touch/cross + outfit alignment + volume spike) and disabled by default unless explicitly enabled per route.
8. Route tolerance applies uniformly across key, micro, and confluence SMA comparisons (LONG uses `close >= sma - tolerance`, SHORT uses `close <= sma + tolerance`).
9. `atr_dynamic_stop` is replay-only in v1 and blocked for live execution.
10. Canonical SVIX outfit for production/research runs is `26/52/106/211/422/844` (`svix_211_106`) per README; `svix_211_116` is retained only as an explicit comparator/profile variant for RWM-specific archival analysis.

## Source Catalog Ambiguity
1. README rows that are malformed or semantically incomplete are preserved in `src/sma_outfits/config/outfits.yaml` with `source_ambiguous: true`.
2. Ambiguous rows retain original integer sequences and raw source text.
