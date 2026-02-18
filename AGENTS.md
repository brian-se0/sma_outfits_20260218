# AGENTS.md

This file defines mandatory operating rules for human and AI contributors working in this repository.

## Canonical Repository

The definitive GitHub repository for this project is:
`https://github.com/brian-se0/sma_outfits_20260218`

## Runtime and Execution Contract

1. **Python runtime is fixed**
   - This project must run in a local virtual environment (`venv`) using **Python 3.14.3**.
   - Any detected Python version mismatch is a hard error.

2. **Makefile-only operations**
   - Project workflows must be executed through `Makefile` targets only.
   - Do not run project tasks via direct tool entrypoints (for example, direct `python`, `pytest`, or module execution) outside of Make targets.
   - Required targets should cover setup, lint, test, backfill, replay, live run, and reporting.

3. **Environment variable source**
   - Runtime secrets and Alpaca credentials must be read from `.env.local`.
   - Missing required keys in `.env.local` are a hard error (no fallback to alternate files or defaults for secrets).

## 1) Project Intent

Recreate the SMA-outfits analysis stack in Python using **Alpaca free data only**, with reproducible research-grade methods and strict integrity controls.

## 2) Core Engineering Principles

1. **Fail fast, no fallback logic**
   - Do not silently substitute missing data, alternate providers, proxy values, cached stale values, or inferred defaults.
   - If required inputs are missing, stale, malformed, or inconsistent: raise a hard error and stop.
   - If a dependency is unavailable, fail with actionable diagnostics.

2. **Determinism first**
   - Same inputs, config, and code must produce the same outputs.
   - Seed all randomized procedures.
   - Persist and log run metadata (code version, config hash, data snapshot boundaries, timezone).

3. **Config-driven behavior**
   - All research/trading assumptions must be explicit in config, never hidden in code paths.
   - No implicit behavior switching by environment.

4. **Separation of concerns**
   - Keep ingestion, transformation, signal generation, risk logic, and reporting decoupled.
   - Keep live logic and backtest logic behaviorally equivalent wherever possible.

## 3) Statistical Validation Requirements (Mandatory)

Every strategy or rule change must include rigorous statistical evaluation before acceptance.

### 3.1 Minimum performance diagnostics

- Return distribution summary (mean, median, std, skew, kurtosis)
- Win rate, payoff ratio, expectancy
- Max drawdown, ulcer index, time-under-water
- Sharpe and Sortino (annualized, explicit assumptions)
- Turnover and capacity proxy metrics (if applicable)

### 3.2 Uncertainty and significance

- Confidence intervals (bootstrap or robust parametric method)
- Hypothesis tests with clearly stated null/alternative
- Multiple-testing control when comparing variants (e.g., Bonferroni/FDR)
- Effect size reporting (not p-values alone)

### 3.3 Robustness checks

- Regime splits (bull/bear/high-vol/low-vol)
- Sensitivity analysis on key hyperparameters
- Stability of results across symbols and timeframes
- Outlier stress analysis (single-day and clustered shock events)

## 4) Bias and Leakage Guards (Mandatory)

1. **Look-ahead bias**
   - Signals may only use information available at decision timestamp.
   - Execution assumptions must reflect bar completion rules explicitly.
   - No future bars in feature computation.

2. **Data-snooping / overfitting**
   - Separate design, validation, and final holdout periods.
   - Prefer walk-forward validation over single split.
   - Track number of tried hypotheses/configs; adjust significance accordingly.

3. **Survivorship bias**
   - Define and document universe construction per test period.
   - Do not evaluate only currently listed winners unless explicitly labeled as such.

4. **Selection bias**
   - Predefine inclusion/exclusion criteria for symbols and events.
   - No cherry-picked case-study-only conclusions.

5. **Execution bias**
   - Model slippage/fees/latency assumptions explicitly (even if zero, it must be declared).
   - Do not assume perfect fills unless the experiment is explicitly "signal-only."

## 5) Data Integrity Rules

- Timezone standard: `America/New_York` for market-session logic; store UTC timestamps alongside.
- Validate monotonic timestamps, duplicate bars, missing bars, and price/volume sanity bounds.
- Reject and halt on schema drift or unexpected field/type changes.
- No forward-fill/backfill unless explicitly enabled for a specific experiment and documented.

## 6) Testing Policy

1. **Unit tests**
   - Indicators, signal triggers, risk rules, and data validators.

2. **Integration tests**
   - End-to-end data flow: ingest -> transform -> signal -> archive.

3. **Bias guard tests**
   - Dedicated tests that intentionally attempt leakage and must fail.
   - Tests verifying train/validation/test boundaries are enforced.

4. **Regression tests**
   - Golden datasets and expected event outputs for deterministic replay.

No change is complete without updated/added tests for impacted behavior.

## 7) Experiment and Reporting Standards

Each experiment/report must include:

- Objective and hypothesis
- Exact dataset boundaries and universe
- Full config snapshot
- Metrics + uncertainty
- Known limitations
- Reproducibility steps

Claims without reproducible evidence are not accepted.

## 8) Code Review Gate (Required for Merge)

A change is mergeable only if:

1. Fail-fast behavior is preserved (no hidden fallback paths).
2. Bias/leakage controls are intact and tested.
3. Statistical evidence is provided for strategy-impacting changes.
4. Reproducibility metadata is captured.
5. Tests pass in CI.

## 9) Explicit Non-Goals

- No opaque "auto-fix" behavior in production paths.
- No undocumented heuristics in signal/risk logic.
- No claiming predictive edge from anecdotal examples alone.
