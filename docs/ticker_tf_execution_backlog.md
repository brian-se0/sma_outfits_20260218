# Ticker/Timeframe Execution Backlog

Last updated: 2026-03-07

This document converts the current `pending_eval` inventory in `ticker_tf_sig_list.md` into an execution backlog that matches the current repository contract.

## Repo constraints that control the backlog

1. Pair significance must be evaluated one symbol and one timeframe at a time.
   The academic-validation pipeline filters by `validation.scope_symbols`, and it aggregates all closed outcomes for the selected symbols. For pair-level scope decisions, each evaluation config must therefore isolate one symbol, and each run must isolate one timeframe.

2. Backfill/readiness and replay have different blockers.
   - `backfill`, `discover-range`, and data-only `verify-readiness` can run for any Alpaca-supported symbol/timeframe pair.
   - `replay` and `e2e` require an exact configured strategy route for the symbol/timeframe pair because strict routing is enabled.

3. No pair has passed significance yet.
   `QQQ 1h`, `SPY 30m`, `QQQ 20m`, `QQQ 30m`, `DIA 15m`, `DIA 1h`, `QQQ 1m`, `SOXL 2h`, `SQQQ 15m`, `SQQQ 30m`, `SVXY 1h`, `IWM 1D`, `NVDA 30m`, `SPY 5m`, `SVIX 1D`, `TSLA 2h`, and `TQQQ 10m` have now completed pair-specific execution cycles, and all seventeen failed the statistical gate. `ERX 30m` completed pair-specific config, `discover-range`, and `e2e` on 2026-03-07, and fresh reruns on 2026-03-07 still stopped at the same gap-quality blocker before academic validation. The remaining candidate work is now blocked by source data quality rather than missing pair configs.

4. Makefile-only execution remains mandatory.
   Pair-specific configs must be run through Make by overriding `CONTEXT_CONFIG_PATH` or `STRICT_CONFIG_PATH`; do not call the Python CLI directly.

## State transition contract for `ticker_tf_sig_list.md`

Move a pair from `pending_eval` to `passed_significance` only when all of the following are true for a pair-specific run:

- A dedicated config exists for exactly one symbol and one timeframe.
- `make run ACTION=e2e ...` succeeds with that pair config and produces replay/report artifacts.
- `make run ACTION=verify-readiness ... VERIFY_READINESS_ARGS='--require-academic-validation'` succeeds for that same pair and window.
- The readiness manifest reports:
  - `status = ok`
  - `boundary_failures_count = 0`
  - `gap_quality_failures_count = 0`
  - `academic_validation.ready = true`
  - `academic_validation.blocking_reasons = []`

Under the current context config thresholds, `academic_validation.ready = true` means the run cleared all of these gates:

- walk-forward fold count `>= 3`
- minimum closed trades per fold `>= 14`
- aggregate OOS Sharpe `>= 1.5`
- aggregate OOS Calmar `> 2.0`
- one-sided bootstrap p-value `< 0.06`
- FDR-adjusted q-values `<= 0.05`
- positive regime means gate passes
- author-alignment score `>= 0.7`

Move a pair from `pending_eval` to `failed_significance` only when:

- the pair-specific route/config exists,
- the pair-specific `e2e` run completes,
- and the pair-specific readiness/academic validation fails because the statistical gate itself failed.

Do not move a pair to `failed_significance` for missing routes, missing configs, blocked symbols, blocked timeframes, insufficient historical coverage, boundary coverage failures, gap-quality failures, or missing artifacts. Those remain implementation blockers, not significance failures.

## Pair config contract

Each pair needs its own config file, using the context profile as the base unless there is a specific reason to test strict.

Minimum requirements for every pair config:

- `validation.scope_symbols: [<SYMBOL>]`
- `strategy.routes`: only the route or route-pair needed for that symbol/timeframe evaluation
- isolated output roots so reports and readiness manifests do not mix pairs
- unchanged fail-fast behavior

Recommended naming:

- config path: `configs/pairs/context/<symbol>_<timeframe>.yaml`
- archive root: `artifacts/pairs/<symbol>_<timeframe>/context`
- readiness root: `artifacts/readiness/pairs/<symbol>_<timeframe>`

## Execution template per pair

Use this sequence for every pair after its config exists.

1. Discover the pair-specific common start:

```powershell
make run ACTION=discover-range `
  CONFIG_PROFILE=context `
  CONTEXT_CONFIG_PATH=configs/pairs/context/<symbol>_<timeframe>.yaml `
  SYMBOLS=<SYMBOL> `
  TIMEFRAMES=<TIMEFRAME> `
  READINESS_ROOT=artifacts/readiness/pairs/<symbol>_<timeframe>
```

2. Run the full pair-specific pipeline:

```powershell
make run ACTION=e2e `
  CONFIG_PROFILE=context `
  CONTEXT_CONFIG_PATH=configs/pairs/context/<symbol>_<timeframe>.yaml `
  PROFILE=max_common `
  SYMBOLS=<SYMBOL> `
  TIMEFRAMES=<TIMEFRAME> `
  READINESS_ROOT=artifacts/readiness/pairs/<symbol>_<timeframe>
```

3. Verify pair-specific readiness and academic validation over the analysis window from that run:

```powershell
make run ACTION=verify-readiness `
  CONFIG_PROFILE=context `
  CONTEXT_CONFIG_PATH=configs/pairs/context/<symbol>_<timeframe>.yaml `
  SYMBOLS=<SYMBOL> `
  TIMEFRAMES=<TIMEFRAME> `
  START=<ANALYSIS_START_FROM_PAIR_RUN> `
  END=<ANALYSIS_END_FROM_PAIR_RUN> `
  READINESS_ROOT=artifacts/readiness/pairs/<symbol>_<timeframe> `
  VERIFY_READINESS_ARGS='--require-academic-validation'
```

## Backlog matrix

Legend:

- `catalog_exact`: the required outfit already exists in `src/sma_outfits/config/outfits.yaml`
- `catalog_gap`: a new outfit entry or explicit author clarification is still required
- `catalog_ambiguous`: a closely matching outfit exists but is currently marked ambiguous
- `route_exact`: an exact symbol/timeframe/outfit route already exists
- `route_pair_mismatch`: the symbol/timeframe exists in config, but with the wrong outfit context
- `route_missing`: no route exists for that pair today

| Runtime pair | Evidence | Intended outfit / key | Catalog status | Route status | Next action |
| --- | --- | --- | --- | --- | --- |
| `SPY` + `30m` | README | `spx_system` (`10/50/200`) | `catalog_exact` | `route_pair_mismatch` | Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:2<14`, `oos_sharpe_below_threshold`, `bootstrap_pvalue_gate_failed`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold`. No further rescue work is queued. |
| `QQQ` + `20m` | README | `nas_system` (`20/100/250`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:4<14` and `regime_stability_gate_failed`. No further rescue work is queued. |
| `QQQ` + `30m` | README | `nas_system` (`20/100/250`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:2<14`, `oos_sharpe_below_threshold`, `bootstrap_pvalue_gate_failed`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold`. No further rescue work is queued. |
| `DIA` + `15m` | README | `dji_system` (`30/60/90/300/600/900`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:1<14`, `bootstrap_pvalue_gate_failed`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold`. No further rescue work is queued. |
| `DIA` + `1h` | README | `dji_system` (`30/60/90/300/600/900`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:0<14`, `oos_sharpe_below_threshold`, `oos_calmar_not_above_threshold`, `bootstrap_pvalue_gate_failed`, `fdr_qvalue_gate_failed`, and `author_alignment_score_below_threshold`. No further rescue work is queued. |
| `ERX` + `30m` | Grok | `an_22` (`22/55/77/222/555/777`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and pair-specific `discover-range` / `e2e` ran successfully. A fresh rerun on 2026-03-07 still failed `verify-readiness --require-academic-validation` on gap quality (`unexpected_gap_count=1`, `max_gap_minutes=7170.0`). The gap localizes to missing ERX storage partitions from `2024-05-09` through `2024-05-10`, and a focused pair-specific `make run ACTION=backfill` over `2024-05-09T14:30:00Z` -> `2024-05-10T21:00:00Z` fails with `No Alpaca bars returned for ERX (1Min)` on both the default `data_feed: iex` path and a fresh isolated `data_feed: sip` probe. Keep the pair in `pending_eval` until the Alpaca source-data hole is resolved. |
| `IWM` + `1D` | Grok | `10/50` | `catalog_exact` | `route_missing` | Grok decision on 2026-03-07 resolved this as a dedicated exact `10/50` outfit, not a constrained `spx_system` variant. Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:1<14` and `regime_stability_gate_failed`. No further rescue work is queued. |
| `NVDA` + `30m` | Grok | `MA50` | `catalog_exact` | `route_missing` | Grok decision on 2026-03-07 resolved this as a dedicated standalone `MA50` route, not `base2_nvda` or another larger outfit. Pair config completed on 2026-03-07 and failed significance with `regime_stability_gate_failed`. No further rescue work is queued. |
| `QQQ` + `1m` | Grok | `an_11` (`11/44/88/111/444/888`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `oos_sharpe_below_threshold:-11.323303<1.500000`, `oos_calmar_not_above_threshold:-2.192186<=2.000000`, `bootstrap_pvalue_gate_failed`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold`. No further rescue work is queued. |
| `QQQ` + `1h` | Grok | `base2_nvda` (`MA512`) | `catalog_exact` | `route_exact` | Two pair-specific hypotheses now exist and both failed significance on 2026-03-07. The original symmetric proxy failed with `wfo_min_closed_trades_per_fold_violation:3<14` and `fdr_qvalue_gate_failed`; the evidence-long close-based proxy failed with `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:1<14`, `bootstrap_pvalue_gate_failed`, and `fdr_qvalue_gate_failed`. User-provided Grok review on 2026-03-07 further indicates the author's documented setup depends on millisecond entry ranking and `5s/15s/30s` microterm confirmation with no published `1m+` proxy. Treat the pair as permanently out-of-scope for this Alpaca Basic subset unless new author evidence contradicts that. |
| `SOXL` + `2h` | Grok | `us_president_46` (`23/46/92/184/368/736`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_fold_count_below_minimum:2<3`, `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:2<14`, and `regime_stability_gate_failed`. No further rescue work is queued. |
| `SQQQ` + `3m` | Grok | `MA254` | `catalog_gap` | `route_missing` | Exclude from the Alpaca Basic subset. User-provided Grok follow-up on 2026-03-07 confirms the blocker is explicit time-series ranking / outfit-duration sequencing for this setup (`https://x.com/UnfairMarket/status/1925572403167695222`), not the `3m` label itself. |
| `SQQQ` + `15m` | Grok | `russia_president_2000` (`MA31`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `regime_stability_gate_failed`. No further rescue work is queued. |
| `SQQQ` + `30m` | Grok | `an_33` (`MA33`) | `catalog_exact` | `route_pair_mismatch` | Pair config completed on 2026-03-07 and failed significance with `regime_stability_gate_failed`. No further rescue work is queued. |
| `SPY` + `5m` | Grok | `29/58/116/232/464/928` | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:6<14`, `oos_sharpe_below_threshold`, `oos_calmar_not_above_threshold`, `bootstrap_pvalue_gate_failed`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold`. No further rescue work is queued. |
| `SVIX` + `1D` | Grok | `17/33/66/132/264/528` | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07. Pair-specific `discover-range`, `e2e`, and `verify-readiness --require-academic-validation` all ran, but the strategy produced zero closed trades and failed significance with `wfo_fold_count_below_minimum:0<3`, `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:0<14`, `oos_sharpe_below_threshold:0.000000<1.500000`, `oos_calmar_not_above_threshold:0.000000<=2.000000`, `bootstrap_pvalue_gate_failed:p=None,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold:0.200000<0.700000`. No further rescue work is queued. |
| `SVXY` + `1h` | Grok | `turkiye_president_12` (`24/48/96/192/384/768`) | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07 and failed significance with `wfo_min_closed_trades_per_fold_violation:1<14` and `regime_stability_gate_failed`. No further rescue work is queued. |
| `TSLA` + `2h` | Grok | `33/66/131/262/626/919` | `catalog_exact` | `route_missing` | Pair config completed on 2026-03-07. Pair-specific `discover-range`, `e2e`, and `verify-readiness --require-academic-validation` all ran, producing 1 closed long trade. The pair failed significance with `wfo_fold_count_below_minimum:0<3`, `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:0<14`, `oos_sharpe_below_threshold:0.000000<1.500000`, `oos_calmar_not_above_threshold:0.000000<=2.000000`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, and `author_alignment_score_below_threshold:0.400000<0.700000`. No further rescue work is queued. |
| `TQQQ` + `10m` | Grok | `warings_problem` (`19/37/73/143/279/548`) | `catalog_exact` | `route_missing` | User-provided Grok follow-up on 2026-03-07 resolved this as a true `10m` bar setup with no sub-minute or sequencing dependency. Pair config completed on 2026-03-07. Pair-specific `discover-range`, `e2e`, and `verify-readiness --require-academic-validation` all ran, producing `115` closed positions. The pair failed significance with `wfo_min_closed_trades_per_fold_violation:11<14` and `regime_stability_gate_failed`. No further rescue work is queued. |
| `TSLT` + `15m` | Grok | `18/36/72/144/288` | `catalog_gap` | `route_missing` | Exclude from the Alpaca Basic subset. User-provided Grok follow-up on 2026-03-07 confirms the blocker is both explicit decisecond-level timing and explicit time-series / InfluxDB sequencing for this setup (`https://x.com/UnfairMarket/status/1937878569902072218`), not the `15m` label itself. |
| `UPRO` + `2m` | Grok | `Xi` / key `MA224` | `catalog_ambiguous` | `route_missing` | Exclude from the Alpaca Basic subset. User-provided Grok follow-up on 2026-03-07 confirms the blocker is explicit time-series outfit-confirmation / sequencing for this setup (`https://x.com/UnfairMarket/status/1932836201998004252`), not the `2m` label itself. |

## Implementation order

### Batch A: catalog-decision pairs

Resolve these outfit-definition questions before route work:

- _none remaining_

### Batch B: author-dependency review / exclusion

Do not implement these in the Alpaca Basic subset unless new author evidence changes the scope decision:

- `SQQQ 3m`
- `TSLT 15m`
- `UPRO 2m`

These exclusions are not caused by the `2m` / `3m` / `15m` labels themselves. `2m` and `3m` are derivable from `1m`, and `15m` is native here. The blocker is explicit author dependency on sequencing logic and, for `TSLT 15m`, explicit sub-minute decisecond data.

There are currently no remaining `manual_review_required` pairs in the admitted implementation backlog.

### Batch C: significance execution

After each pair config exists, run the three-step pair workflow above and immediately update `ticker_tf_sig_list.md`:

- move the pair to `passed_significance` if the pair-specific readiness manifest is clean and `academic_validation.ready = true`
- move the pair to `failed_significance` if the pair-specific statistical gate fails after a completed `e2e` run
- otherwise leave it in `pending_eval` and record the implementation blocker

## Immediate next implementation target

There is no remaining actionable pair-config implementation target.

Reason:

- `SVIX 1D` and `TSLA 2h`, the last in-scope catalog-definition pairs, now both have dedicated pair configs and both failed the academic/statistical gate on 2026-03-07
- `ERX 30m` already has a dedicated pair config and completed pair-specific `discover-range` plus `e2e` on 2026-03-07, but it is still blocked by a confirmed Alpaca source-data hole on `2024-05-09` through `2024-05-10` (`unexpected_gap_count=1`, `max_gap_minutes=7170.0`), with the same missing-window repro on both `data_feed: iex` and an isolated `data_feed: sip` probe
- `QQQ 1h` has already exhausted both the symmetric proxy and the evidence-long close-based proxy, and Grok indicates the author's documented setup requires unavailable millisecond and `5s/15s/30s` data, so it should not consume the next implementation slot
- `SPY 30m`, `QQQ 20m`, `QQQ 30m`, `DIA 15m`, `DIA 1h`, `QQQ 1m`, `SOXL 2h`, `SQQQ 15m`, `SQQQ 30m`, `SVXY 1h`, `IWM 1D`, `NVDA 30m`, `SPY 5m`, `SVIX 1D`, `TSLA 2h`, and `TQQQ 10m` now all have dedicated pair configs and completed pair-specific `discover-range`, `e2e`, and `verify-readiness --require-academic-validation` runs on 2026-03-07, but all failed the academic/statistical gate
- The excluded pairs remain out of scope for confirmed reasons: `SQQQ 3m` and `UPRO 2m` require non-bar sequencing / time-series confirmation, while `TSLT 15m` requires both decisecond-level data and time-series / InfluxDB sequencing
