# Proven Edge Plan v1: Academic Validation Appendix + Strict WFO Gate

## Summary
Implement a deterministic, config-driven “Academic Validation Appendix” that is auto-included in every generated `report.md`, while enforcing a strict proven-edge gate for promotion decisions. The appendix will produce WFO tables, bootstrap histograms (both markdown table + PNG), p-value summaries, and a versioned citation pack grounded in reliable published sources.  
This plan is scoped to the liquid-core validation universe first: `QQQ, SPY, TQQQ, SQQQ, SVIX, VIXY`.

## Decision Lock-Ins (Already Chosen)
1. Validation scope: liquid-core symbols first.
2. Promotion gate: strict WFO.
3. Execution realism: modeled now in backtest stage.
4. Histogram output: both markdown table and PNG.
5. Citation maintenance: versioned citation pack in repo.
6. Fold enforcement: hard fail if any OOS fold has `< 50` closed trades.

## Implementation Plan

## 1) Add Config-Driven Validation + Execution Cost Schemas
Update `src/sma_outfits/config/models.py` and strategy config files to make all academic and execution assumptions explicit.

### New top-level config sections
- `validation`
- `execution_costs`
- `citations`

### Required fields (initial defaults)
- `validation.scope_symbols`: `["QQQ","SPY","TQQQ","SQQQ","SVIX","VIXY"]`
- `validation.wfo.train_months`: `24`
- `validation.wfo.test_months`: `6`
- `validation.wfo.step_months`: `6`
- `validation.wfo.min_folds`: `5`
- `validation.wfo.min_closed_trades_per_fold`: `50`
- `validation.thresholds.oos_sharpe_min`: `1.5`
- `validation.thresholds.oos_calmar_min`: `2.0`
- `validation.bootstrap.method`: `stationary_block`
- `validation.bootstrap.samples`: `10000`
- `validation.bootstrap.alpha`: `0.05`
- `validation.multiple_testing.method`: `fdr_bh`
- `validation.regime.proxy_symbol`: `VIXY`
- `validation.regime.require_positive_mean_in_each`: `true`
- `execution_costs.slippage_bps_scenarios`: `[2.0, 3.5, 5.0]`
- `execution_costs.commission_bps_scenarios`: `[0.5, 0.75, 1.0]`
- `execution_costs.latency_bars_scenarios`: `[0, 1, 1]`
- `execution_costs.partial_fill_round_lot`: `true`
- `citations.pack_path`: `src/sma_outfits/reporting/citations/academic_validation.yaml`

## 2) Build Execution-Realism Overlay for Outcome Metrics
Implement a deterministic execution-cost overlay used by report analytics (not live order routing), applied to close-attribution outcomes.

### Code touchpoints
- New module: `src/sma_outfits/reporting/execution_realism.py`
- Integrate from: `src/sma_outfits/reporting/summary.py`

### Behavior
- Compute gross realized R from existing events.
- Compute net realized R per scenario from config:
  - slippage on entry and exit.
  - commission bps.
  - latency penalty via next-bar execution proxy when configured.
- Emit scenario table in appendix:
  - `baseline_gross`, `net_s1`, `net_s2`, `net_s3`.
- Use net scenario metrics for strict gate checks.

## 3) Implement Academic Validation Engine
Create a dedicated module that generates WFO, bootstrap, p-values, and regime stability outputs.

### Code touchpoints
- New module: `src/sma_outfits/reporting/academic_validation.py`
- Called from `build_summary_from_records` path in `src/sma_outfits/reporting/summary.py`

### Outputs
- `wfo_folds`: fold-by-fold OOS metrics table.
- `wfo_aggregate`: pass/fail and blocker reasons.
- `bootstrap`: distribution stats + CI + p-value.
- `pvalues`: primary and multiple-testing adjusted q-values.
- `regime_stability`: high-vol vs low-vol metrics.
- `random_strategy_mc`: 10,000 null simulations with block structure.

### Hard gate logic
A report is academically ready only if all are true:
1. At least 5 folds.
2. Each fold has at least 50 closed trades.
3. OOS Sharpe >= 1.5.
4. OOS Calmar > 2.0.
5. Bootstrap one-sided p-value < 0.05.
6. FDR-adjusted q-values pass configured threshold.
7. Regime stability positive in high-vol and low-vol splits.
8. Replication score >= 80% for configured author-ground-truth checklist file (see section 6).

## 4) Extend Markdown Report Writer to Always Include Appendix
Modify `write_summary_report` in `src/sma_outfits/reporting/summary.py` so every report includes:

- `## Academic Validation Appendix`
- `### Walk-Forward Optimization (WFO)`
- `### Bootstrap Distribution`
- `### P-Value and Multiple-Testing Summary`
- `### Execution Realism Sensitivity`
- `### Regime Stability`
- `### Citation Pack`

### New artifacts written per report label
- `archive/reports/<label>.md` (appendix embedded)
- `archive/reports/<label>_academic_validation.json`
- `archive/reports/<label>_wfo_table.csv`
- `archive/reports/<label>_pvalues.csv`
- `archive/reports/<label>_bootstrap_bins.csv`
- `archive/reports/figures/<label>_bootstrap_hist.png`

## 5) Wire Strict Academic Gate into Readiness
Extend `verify-readiness` in `src/sma_outfits/cli.py` to consume appendix outputs and enforce hard-fail gate.

### CLI changes
- Add flag: `--require-academic-validation/--no-require-academic-validation` (default true).
- Add manifest fields under `readiness_acceptance.json`:
  - `academic_validation.ready`
  - `academic_validation.blocking_reasons`
  - `academic_validation.fold_count`
  - `academic_validation.min_fold_trade_count`
  - `academic_validation.bootstrap_p_value`
  - `academic_validation.fdr_summary`

### Makefile changes
- Add `make prove-edge` target that runs:
  1. `make e2e ... STAGES=validate-config,backfill,replay,report`
  2. `make verify-readiness ...` with academic gate required
- Add vars:
  - `PROVEN_EDGE_SYMBOLS`
  - `PROVEN_EDGE_TIMEFRAMES`
  - `VALIDATION_CONFIG_OVERRIDE` (optional)

## 6) Add Versioned Citation Pack + Ground-Truth Mapping
Create repo-tracked citation metadata and author-ground-truth mapping used by appendix and replication scoring.

### New files
- `src/sma_outfits/reporting/citations/academic_validation.yaml`
- `src/sma_outfits/reporting/citations/README.md`
- `artifacts/ground_truth/author_alignment_rules.yaml` (or config path equivalent)

### Citation pack fields
- `id`, `title`, `authors`, `year`, `venue`, `type`, `url`, `why_it_matters`, `retrieved_at_utc`.

### Initial citation set (pin now)
1. White (2000), Reality Check for Data Snooping  
   https://econpapers.repec.org/RePEc:ecm:emetrp:v:68:y:2000:i:5:p:1097-1126
2. Hansen (2005), Superior Predictive Ability test  
   https://econpapers.repec.org/RePEc:bes:jnlbes:v:23:y:2005:p:365-380
3. Bailey et al. (2017), Probability of Backtest Overfitting  
   https://ideas.repec.org/a/rsk/journ4/2464632.html
4. Benjamini & Hochberg (1995), FDR control  
   https://doi.org/10.1111/j.2517-6161.1995.tb02031.x
5. Politis & White (2004), Automatic block-length selection  
   https://www3.stat.sinica.edu.tw/statistica/j14n1/j14n11/j14n11.html
6. Dong et al. (2024), ML methods for stock price prediction (baseline modern comparator)  
   https://www.sciencedirect.com/science/article/pii/S0950705124002934
7. Rahimikia et al. (2026), GT-Score framework (recent published benchmark context)  
   https://doi.org/10.3390/fi18020081
8. Khilar et al. (2025), CV + Monte Carlo robustness in algorithmic trading (recent arXiv)  
   https://arxiv.org/abs/2512.12924

## Important Public API / Interface Changes

| Area | Change |
|---|---|
| Config schema | Add `validation`, `execution_costs`, `citations` top-level sections |
| Summary payload | Add `academic_validation` object with deterministic sub-keys |
| Report artifacts | Add JSON/CSV/PNG sidecar files for appendix diagnostics |
| CLI | `verify-readiness` gains academic gate requirement flag |
| Makefile | Add `prove-edge` target and validation-scope vars |

## Test Cases and Scenarios

## Unit tests
1. `tests/unit/test_academic_validation.py`:
   - fold construction deterministic.
   - hard fail when any fold has `<50` closes.
   - bootstrap reproducibility with fixed seed.
   - FDR adjustment correctness.
2. `tests/unit/test_execution_realism.py`:
   - slippage/commission/latency overlay math.
   - scenario table outputs expected columns.
3. Extend `tests/unit/test_reporting_summary.py`:
   - report markdown contains appendix headings.
   - CSV/JSON/PNG sidecars are produced.
   - citation IDs rendered in report.

## Integration tests
1. `tests/integration/test_report_academic_appendix_end_to_end.py`:
   - replay + report writes appendix artifacts.
2. `tests/integration/test_verify_readiness_academic_gate.py`:
   - fails with insufficient folds or low significance.
   - passes with fixture data meeting strict thresholds.

## Acceptance criteria
1. Every report markdown includes Academic Validation Appendix sections.
2. WFO table + bootstrap table + bootstrap PNG + p-value summary generated per report label.
3. Readiness hard-fails on strict gate violations.
4. All new behavior is config-driven and deterministic.
5. Makefile-only workflow supports end-to-end proven-edge validation.

## Assumptions and Defaults
1. No repo mutation is performed in this plan phase.
2. If no 2026 arXiv WFO-specific paper is found, latest reliable recent sources are used (2025 arXiv + 2026 published journal + foundational econometrics).
3. Appendix uses close-attribution outcomes as the promotion gate basis; strike-attribution remains descriptive.
4. Random simulation count is fixed at 10,000 with seeded RNG for reproducibility.
5. Missing citation pack or malformed citation entry is a hard error.
