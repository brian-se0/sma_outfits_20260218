# Ticker/Timeframe Significance Tracker

Last updated: 2026-03-07

This file tracks scope decisions derived from:

- `docs/history/source/README_original_context.md`
- `docs/ticker_tf_execution_backlog.md`
- `src/sma_outfits/utils.py`
- `configs/settings.jan2025_confluence_atr_svix211_106_crossctx_context_v1.yaml`
- User-provided Grok summary of explicit `@UnfairMarket` / `@rauitrades` X evidence received on 2026-03-07
- Alpaca official docs for Market Data / Basic-plan constraints

## Status legend

- `blocked_alpaca_access`: the original symbol or timeframe is not available under this repo's Alpaca Basic, bar-based contract.
- `blocked_author_dependency`: explicit X/Grok evidence says the author's documented setup depends on millisecond, sub-minute, or sequencing context that this Alpaca Basic subset cannot reproduce.
- `manual_review_required`: explicit X/Grok evidence is mixed or incomplete; do not implement until the dependency question is resolved.
- `scope_candidate`: symbol is accessible, but the README does not bind it to a specific timeframe strongly enough to create a testable pair yet.
- `pending_eval`: symbol/timeframe pair is in scope and should go through detection -> trading -> statistical validation.
- `failed_significance`: pair was evaluated and did not pass the statistical acceptance gate.
- `passed_significance`: pair was evaluated and passed the statistical acceptance gate.

## Timeframe access filter

The archived README lists the following timeframe universe:

- Ultra short-term: `1T`, `1S`
- Sub-minute: `5s`, `15s`, `30s`
- Minute-to-hour: `1m`, `2m`, `3m`, `5m`, `10m`, `15m`, `20m`, `30m`, `1h`, `2h`, `4h`
- Longer periods: `1D`, `1W`, `1M`, `1Q`

For this repository, the actionable filter is:

| Timeframe | Status | Notes |
| --- | --- | --- |
| `1T` | `blocked_alpaca_access` | Current repo contract is bar-level `1m+`; source tick granularity is explicitly not reproducible here. |
| `1S` | `blocked_alpaca_access` | Current repo contract is bar-level `1m+`; source second granularity is explicitly not reproducible here. |
| `5s` | `blocked_alpaca_access` | Sub-minute bars are outside the current Alpaca Basic, bar-based runtime contract used by this repo. |
| `15s` | `blocked_alpaca_access` | Sub-minute bars are outside the current Alpaca Basic, bar-based runtime contract used by this repo. |
| `30s` | `blocked_alpaca_access` | Sub-minute bars are outside the current Alpaca Basic, bar-based runtime contract used by this repo. |
| `1m` | `pending_eval` | Native Alpaca bar timeframe. |
| `2m` | `pending_eval` | Derived in repo from `1m` bars. |
| `3m` | `pending_eval` | Derived in repo from `1m` bars. |
| `5m` | `pending_eval` | Native Alpaca bar timeframe. |
| `10m` | `pending_eval` | Derived in repo from `1m` bars. |
| `15m` | `pending_eval` | Native Alpaca bar timeframe. |
| `20m` | `pending_eval` | Derived in repo from `1m` bars. |
| `30m` | `pending_eval` | Native Alpaca bar timeframe. |
| `1h` | `pending_eval` | Native Alpaca bar timeframe. |
| `2h` | `pending_eval` | Derived in repo from `1h` bars. |
| `4h` | `pending_eval` | Derived in repo from `1h` bars. |
| `1D` | `pending_eval` | Native Alpaca bar timeframe. |
| `1W` | `pending_eval` | Derived in repo from `1D` bars. |
| `1M` | `pending_eval` | Derived in repo from `1D` bars. |
| `1Q` | `pending_eval` | Derived in repo from `1D` bars. |

## Symbol access filter

The archived README already includes an Alpaca native-support audit. Symbols below are classified against that audit plus the current repo symbol normalization/proxy map.

| README symbol | Status | Runtime symbol | Notes |
| --- | --- | --- | --- |
| `SPX` | `blocked_alpaca_access` | `SPY` proxy | No native Alpaca asset support; repo proxy exists. |
| `SPY` | `scope_candidate` | `SPY` | Native ETF. |
| `IXIC` | `blocked_alpaca_access` | `QQQ` proxy | No native Alpaca asset support; repo proxy exists. |
| `QQQ` | `scope_candidate` | `QQQ` | Native ETF. |
| `DJI` | `blocked_alpaca_access` | `DIA` proxy | No native Alpaca asset support; repo proxy exists. |
| `DIA` | `scope_candidate` | `DIA` | Native ETF. |
| `UPRO` | `scope_candidate` | `UPRO` | Native ETF. |
| `TQQQ` | `scope_candidate` | `TQQQ` | Native ETF. |
| `SQQQ` | `scope_candidate` | `SQQQ` | Native ETF. |
| `WEBS` | `scope_candidate` | `WEBS` | Native ETF. |
| `UDOW` | `scope_candidate` | `UDOW` | Native ETF. |
| `SDOW` | `scope_candidate` | `SDOW` | Native ETF. |
| `VIX` | `blocked_alpaca_access` | `VIXY` proxy | No native Alpaca asset support; repo proxy exists even though `VIXY` is not in the README table. |
| `VXX` | `scope_candidate` | `VXX` | Native ETN/ETF-style instrument in repo universe. |
| `SVIX` | `scope_candidate` | `SVIX` | Native ETF. |
| `UVXY` | `scope_candidate` | `UVXY` | Native ETF. |
| `SVXY` | `scope_candidate` | `SVXY` | Native ETF. |
| `SOXS` | `scope_candidate` | `SOXS` | Native ETF. |
| `SOXL` | `scope_candidate` | `SOXL` | Native ETF. |
| `UWM` | `scope_candidate` | `UWM` | Native ETF. |
| `IWM` | `scope_candidate` | `IWM` | Native ETF. |
| `AAPL` | `scope_candidate` | `AAPL` | Native stock. |
| `MSFT` | `scope_candidate` | `MSFT` | Native stock. |
| `AMZN` | `scope_candidate` | `AMZN` | Native stock. |
| `GOOG` | `scope_candidate` | `GOOG` | Native stock. |
| `NVDA` | `scope_candidate` | `NVDA` | Native stock. |
| `META` | `scope_candidate` | `META` | Native stock. |
| `TSLA` | `scope_candidate` | `TSLA` | Native stock. |
| `AMD` | `scope_candidate` | `AMD` | Native stock. |
| `NFLX` | `scope_candidate` | `NFLX` | Native stock. |
| `INTC` | `scope_candidate` | `INTC` | Native stock. |
| `COIN` | `scope_candidate` | `COIN` | Native stock. |
| `QCOM` | `scope_candidate` | `QCOM` | Native stock. |
| `PYPL` | `scope_candidate` | `PYPL` | Native stock. |
| `UPST` | `scope_candidate` | `UPST` | Native stock. |
| `RBLX` | `scope_candidate` | `RBLX` | Native stock. |
| `AI` | `scope_candidate` | `AI` | Native stock. |
| `ARM` | `scope_candidate` | `ARM` | Native stock. |
| `BRK-B` | `scope_candidate` | `BRK.B` | README notation normalizes to Alpaca native `BRK.B`. |
| `GM` | `scope_candidate` | `GM` | Native stock. |
| `JPM` | `scope_candidate` | `JPM` | Native stock. |
| `V` | `scope_candidate` | `V` | Native stock. |
| `UNH` | `scope_candidate` | `UNH` | Native stock. |
| `ENPH` | `scope_candidate` | `ENPH` | Native stock. |
| `BTCUSD` | `scope_candidate` | `BTC/USD` | README notation normalizes to repo crypto symbol. |
| `ETHUSD` | `scope_candidate` | `ETH/USD` | README notation normalizes to repo crypto symbol. |
| `BITO` | `scope_candidate` | `BITO` | Native ETF. |
| `HSI` | `blocked_alpaca_access` | none | No native Alpaca asset support. |
| `DAX` | `scope_candidate` | `DAX` | Present in repo universe as a stock/ETF symbol. |
| `BABA` | `scope_candidate` | `BABA` | Native stock. |
| `TSM` | `scope_candidate` | `TSM` | Native stock. |
| `AAPD` | `scope_candidate` | `AAPD` | Native ETF. |
| `AAPU` | `scope_candidate` | `AAPU` | Native ETF. |
| `TSLT` | `scope_candidate` | `TSLT` | Native ETF. |
| `TSLQ` | `scope_candidate` | `TSLQ` | Native ETF. |
| `ERX` | `scope_candidate` | `ERX` | Native ETF. |
| `LABU` | `scope_candidate` | `LABU` | Native ETF. |
| `GUSH` | `scope_candidate` | `GUSH` | Native ETF. |
| `DRIP` | `scope_candidate` | `DRIP` | Native ETF. |
| `BOIL` | `scope_candidate` | `BOIL` | Native ETF. |
| `DRN` | `scope_candidate` | `DRN` | Native ETF. |
| `REK` | `scope_candidate` | `REK` | Native ETF. |
| `GLD` | `scope_candidate` | `GLD` | Native ETF. |
| `XAUUSD` | `blocked_alpaca_access` | none | No native Alpaca asset support. |
| `DXY` | `blocked_alpaca_access` | none | No native Alpaca asset support. |
| `USO` | `scope_candidate` | `USO` | Native ETF. |
| `TLT` | `scope_candidate` | `TLT` | Native ETF. |
| `TBT` | `scope_candidate` | `TBT` | Native ETF. |
| `TNX` | `blocked_alpaca_access` | none | No native Alpaca asset support. |

## Explicit README combinations to evaluate first

These are the only symbol/timeframe pairs stated explicitly enough in the archived README to create immediate evaluation backlog items without guessing.

| Original pair | Runtime pair | Outfit context | Status | Notes |
| --- | --- | --- | --- | --- |
| `SPX` + `30m` | `SPY` + `30m` | `10/50/200` | `failed_significance` | Original symbol is blocked natively; pair-specific `spx_system` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `IXIC` + `20m` | `QQQ` + `20m` | `20/100/250` | `failed_significance` | Original symbol is blocked natively; pair-specific `nas_system` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `IXIC` + `30m` | `QQQ` + `30m` | `20/100/250` | `failed_significance` | Original symbol is blocked natively; pair-specific `nas_system` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `DJI` + `15m` | `DIA` + `15m` | `30/60/90/300/600/900` | `failed_significance` | Original symbol is blocked natively; pair-specific `dji_system` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `DJI` + `1h` | `DIA` + `1h` | `30/60/90/300/600/900` | `failed_significance` | Original symbol is blocked natively; pair-specific `dji_system` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |

## Explicit X/Grok-confirmed combinations to evaluate next

These pairs come from the user-provided Grok summary of explicit X-post evidence. They were not independently re-verified from X in this environment.

| Runtime pair | Outfit context | X date | X URL | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| `ERX` + `30m` | `22/55/77/222/555/777` | `2025-06-05` | `https://x.com/UnfairMarket/status/1930650380960170435` | `pending_eval` | Native Alpaca timeframe. Pair-specific config and run completed on 2026-03-07, and a fresh rerun on 2026-03-07 still failed `verify-readiness --require-academic-validation` on gap quality (`unexpected_gap_count=1`, `max_gap_minutes=7170.0`). The gap localizes to missing ERX storage partitions from `2024-05-09` through `2024-05-10`, and a focused `make run ACTION=backfill` over `2024-05-09T14:30:00Z` -> `2024-05-10T21:00:00Z` hard-failed with `No Alpaca bars returned for ERX (1Min)` on both the default `data_feed: iex` path and a fresh isolated `data_feed: sip` probe. Keep `pending_eval` until the source-data gap is resolved. |
| `IWM` + `1D` | `10/50` | `2025-11-07` | `https://x.com/UnfairMarket/status/1986831372770808180` | `failed_significance` | Grok reported `Daily`; normalized here to repo timeframe `1D`. Grok follow-up on 2026-03-07 resolved this as an exact dedicated `10/50` route rather than a constrained `spx_system` variant. Pair-specific `base_10_50_iwm` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `NVDA` + `30m` | `MA50` | `2023-11-15` | `https://x.com/UnfairMarket/status/1724869140064968771` | `failed_significance` | Native Alpaca timeframe. Grok follow-up on 2026-03-07 resolved this as a dedicated standalone `MA50` route rather than `base2_nvda`. Pair-specific `ma50_nvda` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `QQQ` + `1m` | `11/44`, key `MA444` | `2024-08-12` | `https://x.com/rauitrades/status/1823011639941267570` | `failed_significance` | Native Alpaca timeframe. Pair-specific `an_11` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `QQQ` + `1h` | `MA512` | `2025-01-13` | `https://x.com/UnfairMarket/status/1878876569579716644` | `failed_significance` | Grok reported `1H`; normalized here to repo timeframe `1h`. Both tested pair-specific hypotheses failed on 2026-03-07, and the follow-up Grok review on 2026-03-07 indicates the author's live setup depends on millisecond ranking plus `5s/15s/30s` microterm confirmation with no documented `1m+` proxy. Treat as permanently out-of-scope for this Alpaca Basic subset unless new author evidence contradicts that. |
| `SOXL` + `2h` | `MA23/46/92/184/368/736` | `2025-12-17` | `https://x.com/UnfairMarket/status/2001344289453064535` | `failed_significance` | Derived in repo from `1h` bars. User-provided Grok audit on 2026-03-07 found no explicit millisecond, sub-minute, or sequencing dependency for this pair. Pair-specific `us_president_46` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `SQQQ` + `3m` | `MA254` | `2025-06-13` | `https://x.com/UnfairMarket/status/1933529917167374507` | `blocked_author_dependency` | Grok reported `3M`; normalized here to repo timeframe `3m`. User-provided Grok follow-up on 2026-03-07 confirms exclusion is due to explicit time-series ranking / outfit-duration sequencing from `https://x.com/UnfairMarket/status/1925572403167695222`, not because `3m` itself is unsupported. Exclude from the Alpaca Basic subset. |
| `SQQQ` + `15m` | `Putin 200`, key `MA31` | `2025-07-08` | `https://x.com/UnfairMarket/status/1942610253994156291` | `failed_significance` | Native Alpaca timeframe. Pair-specific `russia_president_2000` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `SQQQ` + `30m` | `MA33` | `2025-08-28` | `https://x.com/UnfairMarket/status/1961094588015501816` | `failed_significance` | Native Alpaca timeframe. Pair-specific `an_33` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `SPY` + `5m` | `29/58/116/232/464/928`, key `MA464` | `2025-06-11` | `https://x.com/UnfairMarket/status/1932867631956263205` | `failed_significance` | Native Alpaca timeframe. Pair-specific `spy_29_58_116_232_464_928` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `SVIX` + `1D` | `17/33/66/132/264/528` | `2025-09-17` | `https://x.com/UnfairMarket/status/1968378463611666832` | `failed_significance` | Grok reported `1D`; repo-native daily bars. Pair-specific `svix_17_33_66_132_264_528` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `SVXY` + `1h` | `MA24/48/96/192/384/768`, key `MA384` | `2025-06-23` | `https://x.com/UnfairMarket/status/1937222112554680460` | `failed_significance` | Grok reported `1H`; normalized here to repo timeframe `1h`. Pair-specific `turkiye_president_12` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `TSLA` + `2h` | `33/66/131/262/626/919` | `2025-07-23` | `https://x.com/UnfairMarket/status/1948147386599219660` | `failed_significance` | Derived in repo from `1h` bars. Pair-specific `tsla_33_66_131_262_626_919` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `TQQQ` + `10m` | `19/37/73/143/279/548` | `2025-07-23` | `https://x.com/UnfairMarket/status/1948037415085785112` | `failed_significance` | Derived in repo from `1m` bars. User-provided Grok follow-up on 2026-03-07 resolved this as a true `10m` bar setup with no sub-minute or sequencing dependency. Pair-specific `warings_problem` proxy run completed on 2026-03-07 and failed the academic/statistical gate. |
| `TSLT` + `15m` | `18/36/72/144/288` | `2025-06-25` | `https://x.com/UnfairMarket/status/1937696324629274643` | `blocked_author_dependency` | Native Alpaca timeframe. User-provided Grok follow-up on 2026-03-07 confirms exclusion is due to both explicit decisecond-level timing and explicit time-series / InfluxDB sequencing from `https://x.com/UnfairMarket/status/1937878569902072218`, not because `15m` itself is unsupported. Exclude from the Alpaca Basic subset. |
| `UPRO` + `2m` | `Xi outfit`, key `MA224` | `2025-06-11` | `https://x.com/UnfairMarket/status/1932832573002297519` | `blocked_author_dependency` | Derived in repo from `1m` bars. User-provided Grok follow-up on 2026-03-07 confirms exclusion is due to explicit time-series outfit-confirmation / sequencing from `https://x.com/UnfairMarket/status/1932836201998004252`, not because `2m` itself is unsupported. Exclude from the Alpaca Basic subset. |

## Symbols with no explicit timeframe evidence yet

Per the user-provided Grok summary, the following symbols still have no explicit timeframe evidence strong enough to justify opening a per-pair significance row:

- `DIA`, `WEBS`, `UDOW`, `SDOW`
- `VXX`, `UVXY`, `SOXS`, `UWM`
- `AAPL`, `MSFT`, `AMZN`, `GOOG`, `META`, `AMD`, `NFLX`, `INTC`
- `COIN`, `QCOM`, `PYPL`, `UPST`, `RBLX`, `AI`, `ARM`, `BRK.B`, `GM`, `JPM`, `V`, `UNH`, `ENPH`
- `BTC/USD`, `ETH/USD`, `BITO`, `DAX`, `BABA`, `TSM`
- `AAPD`, `AAPU`, `TSLQ`, `LABU`, `GUSH`, `DRIP`, `BOIL`, `DRN`, `REK`, `GLD`, `USO`, `TLT`, `TBT`

Do not create full ticker/timeframe cross-products for these until X/Grok provides explicit author evidence for the intended timeframe(s).

## Pair state transition rule

Use the operational contract in `docs/ticker_tf_execution_backlog.md`.

- `pending_eval` means the pair is admitted to the backlog but has not yet completed a pair-specific `e2e` plus `verify-readiness --require-academic-validation` cycle.
- `failed_significance` is reserved for completed pair-specific runs where the academic/statistical gate failed.
- Missing routes, missing configs, missing artifacts, blocked symbols/timeframes, and data-coverage failures are implementation blockers, not significance failures.

## Author-dependency exclusions

Do not implement the following pairs in this Alpaca Basic subset unless new author evidence contradicts the current X/Grok audit:

- `SQQQ 3m`: explicit time-series ranking / outfit-duration sequencing cited by user-provided Grok on 2026-03-07 (`https://x.com/UnfairMarket/status/1925572403167695222`). The blocker is sequencing dependency, not the `3m` label.
- `TSLT 15m`: explicit decisecond-level timing plus time-series / InfluxDB sequencing cited by user-provided Grok on 2026-03-07 (`https://x.com/UnfairMarket/status/1937878569902072218`). The blocker is both sub-minute dependency and sequencing dependency, not the `15m` label.
- `UPRO 2m`: explicit time-series outfit-confirmation / sequencing cited by user-provided Grok on 2026-03-07 (`https://x.com/UnfairMarket/status/1932836201998004252`). The blocker is sequencing dependency, not the `2m` label.

## Failed significance gate

Add rows here only after a pair has completed the full detection -> trading -> statistical-validation pipeline and failed acceptance.

| Runtime pair | Hypothesis | Evaluation window | Failure basis | Evidence/report |
| --- | --- | --- | --- | --- |
| `QQQ` + `1h` | `symmetric long+short penny-reference proxy` | `2020-11-24T13:00:00+00:00` -> `2026-03-07T00:48:20+00:00` | `wfo_min_closed_trades_per_fold_violation:3<14`, `fdr_qvalue_gate_failed` | `artifacts/pairs/qqq_1h/context/runs/20260307T010454Z/run_manifest.json`; `artifacts/pairs/qqq_1h/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `QQQ` + `1h` | `evidence-long close-reference proxy` | `2020-11-24T13:00:00+00:00` -> `2026-03-07T01:32:32+00:00` | `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:1<14`, `bootstrap_pvalue_gate_failed:p=0.255,threshold=0.06`, `fdr_qvalue_gate_failed` | `artifacts/pairs/qqq_1h_evidence_long/context/runs/20260307T014906Z/run_manifest.json`; `artifacts/pairs/qqq_1h_evidence_long/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07. User-provided Grok review on 2026-03-07 further indicates the author's documented setup is non-reproducible here because entry selection requires millisecond time-ranking and the hold override requires `5s/15s/30s` microterm data. |
| `QQQ` + `20m` | `README proxy via nas_system long-only route` | `2020-11-24T13:40:00+00:00` -> `2026-03-07T02:25:58+00:00` | `wfo_min_closed_trades_per_fold_violation:4<14`, `regime_stability_gate_failed` | `artifacts/pairs/qqq_20m/context/runs/20260307T024355Z/run_manifest.json`; `artifacts/pairs/qqq_20m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `QQQ` + `30m` | `README proxy via nas_system long-only route` | `2020-11-24T14:00:00+00:00` -> `2026-03-07T02:33:39+00:00` | `wfo_min_closed_trades_per_fold_violation:2<14`, `oos_sharpe_below_threshold:-801.227049<1.500000`, `bootstrap_pvalue_gate_failed:p=0.2734,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.500000<0.700000` | `artifacts/pairs/qqq_30m/context/runs/20260307T025127Z/run_manifest.json`; `artifacts/pairs/qqq_30m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `QQQ` + `1m` | `X proxy via an_11 long-only route` | `2020-11-24T13:31:00+00:00` -> `2026-03-07T03:40:40+00:00` | `oos_sharpe_below_threshold:-11.323303<1.500000`, `oos_calmar_not_above_threshold:-2.192186<=2.000000`, `bootstrap_pvalue_gate_failed:p=1.0,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.300000<0.700000` | `artifacts/pairs/qqq_1m/context/runs/20260307T041511Z/run_manifest.json`; `artifacts/pairs/qqq_1m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SOXL` + `2h` | `X proxy via us_president_46 long-only route` | `2020-11-24T14:00:00+00:00` -> `2026-03-07T04:16:40+00:00` | `wfo_fold_count_below_minimum:2<3`, `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:2<14`, `regime_stability_gate_failed` | `artifacts/pairs/soxl_2h/context/runs/20260307T043230Z/run_manifest.json`; `artifacts/pairs/soxl_2h/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SQQQ` + `15m` | `X proxy via russia_president_2000 long-only route` | `2020-11-24T13:45:00+00:00` -> `2026-03-07T04:27:47+00:00` | `regime_stability_gate_failed` | `artifacts/pairs/sqqq_15m/context/runs/20260307T044512Z/run_manifest.json`; `artifacts/pairs/sqqq_15m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SQQQ` + `30m` | `X proxy via an_33 long-only route` | `2020-11-24T14:00:00+00:00` -> `2026-03-07T04:35:58+00:00` | `regime_stability_gate_failed` | `artifacts/pairs/sqqq_30m/context/runs/20260307T045259Z/run_manifest.json`; `artifacts/pairs/sqqq_30m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SVXY` + `1h` | `X proxy via turkiye_president_12 long-only route` | `2020-11-24T13:00:00+00:00` -> `2026-03-07T04:50:56+00:00` | `wfo_min_closed_trades_per_fold_violation:1<14`, `regime_stability_gate_failed` | `artifacts/pairs/svxy_1h/context/runs/20260307T050651Z/run_manifest.json`; `artifacts/pairs/svxy_1h/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `IWM` + `1D` | `X proxy via base_10_50_iwm long-only route` | `2020-11-24T04:00:00+00:00` -> `2026-03-07T05:24:45+00:00` | `wfo_min_closed_trades_per_fold_violation:1<14`, `regime_stability_gate_failed` | `artifacts/pairs/iwm_1d/context/runs/20260307T054020Z/run_manifest.json`; `artifacts/pairs/iwm_1d/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `NVDA` + `30m` | `X proxy via ma50_nvda long-only route` | `2020-11-24T13:30:00+00:00` -> `2026-03-07T05:52:11+00:00` | `regime_stability_gate_failed` | `artifacts/pairs/nvda_30m/context/runs/20260307T060903Z/run_manifest.json`; `artifacts/pairs/nvda_30m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SPY` + `5m` | `X proxy via spy_29_58_116_232_464_928 long-only route` | `2020-11-24T12:50:00+00:00` -> `2026-03-07T06:12:58+00:00` | `wfo_min_closed_trades_per_fold_violation:6<14`, `oos_sharpe_below_threshold:-61.755872<1.500000`, `oos_calmar_not_above_threshold:-8.235771<=2.000000`, `bootstrap_pvalue_gate_failed:p=0.9429,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.200000<0.700000` | `artifacts/pairs/spy_5m/context/runs/20260307T063349Z/run_manifest.json`; `artifacts/pairs/spy_5m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SVIX` + `1D` | `X proxy via svix_17_33_66_132_264_528 long-only route` | `2022-07-29T04:00:00+00:00` -> `2026-03-07T06:32:39+00:00` | `wfo_fold_count_below_minimum:0<3`, `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:0<14`, `oos_sharpe_below_threshold:0.000000<1.500000`, `oos_calmar_not_above_threshold:0.000000<=2.000000`, `bootstrap_pvalue_gate_failed:p=None,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.200000<0.700000` | `artifacts/pairs/svix_1d/context/runs/20260307T064809Z/run_manifest.json`; `artifacts/pairs/svix_1d/context/reports/20220729_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `TSLA` + `2h` | `X proxy via tsla_33_66_131_262_626_919 long-only route` | `2020-11-24T14:00:00+00:00` -> `2026-03-07T06:42:30+00:00` | `wfo_fold_count_below_minimum:0<3`, `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:0<14`, `oos_sharpe_below_threshold:0.000000<1.500000`, `oos_calmar_not_above_threshold:0.000000<=2.000000`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.400000<0.700000` | `artifacts/pairs/tsla_2h/context/runs/20260307T065826Z/run_manifest.json`; `artifacts/pairs/tsla_2h/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `TQQQ` + `10m` | `X proxy via warings_problem long-only route` | `2020-11-24T13:30:00+00:00` -> `2026-03-07T07:43:10+00:00` | `wfo_min_closed_trades_per_fold_violation:11<14`, `regime_stability_gate_failed` | `artifacts/pairs/tqqq_10m/context/runs/20260307T080100Z/run_manifest.json`; `artifacts/pairs/tqqq_10m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `DIA` + `15m` | `README proxy via dji_system long-only route` | `2020-11-24T13:30:00+00:00` -> `2026-03-07T02:50:51+00:00` | `wfo_min_closed_trades_per_fold_violation:1<14`, `bootstrap_pvalue_gate_failed:p=0.1745,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.600000<0.700000` | `artifacts/pairs/dia_15m/context/runs/20260307T030911Z/run_manifest.json`; `artifacts/pairs/dia_15m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `DIA` + `1h` | `README proxy via dji_system long-only route` | `2020-11-24T13:00:00+00:00` -> `2026-03-07T02:59:09+00:00` | `wfo_window_infeasible_for_config`, `wfo_min_closed_trades_per_fold_violation:0<14`, `oos_sharpe_below_threshold:0.000000<1.500000`, `oos_calmar_not_above_threshold:0.000000<=2.000000`, `bootstrap_pvalue_gate_failed:p=0.0933,threshold=0.06`, `fdr_qvalue_gate_failed`, `author_alignment_score_below_threshold:0.500000<0.700000` | `artifacts/pairs/dia_1h/context/runs/20260307T031541Z/run_manifest.json`; `artifacts/pairs/dia_1h/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |
| `SPY` + `30m` | `README proxy via spx_system long-only route` | `2020-11-24T13:30:00+00:00` -> `2026-03-07T02:11:58+00:00` | `wfo_min_closed_trades_per_fold_violation:2<14`, `oos_sharpe_below_threshold:-64.899882<1.500000`, `bootstrap_pvalue_gate_failed:p=0.6519,threshold=0.06`, `fdr_qvalue_gate_failed`, `regime_stability_gate_failed`, `author_alignment_score_below_threshold:0.300000<0.700000` | `artifacts/pairs/spy_30m/context/runs/20260307T022943Z/run_manifest.json`; `artifacts/pairs/spy_30m/context/reports/20201124_20260307_academic_validation.json`; failed `verify-readiness --require-academic-validation` run on 2026-03-07 |

## Passed significance gate

| Runtime pair | Evaluation window | Evidence/report |
| --- | --- | --- |
| _none yet_ |  |  |
