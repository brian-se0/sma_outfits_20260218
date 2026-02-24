# Null Hypothesis Assessment

Date of assessment: 2026-02-24 (UTC)  
Workspace: `d:\sma_outfits_20260218`

## 1) Statistical Question and Hypotheses

This project should be evaluated with a conventional inferential framing:

- `H0 (no-edge null)`: mean realized return per closed trade `<= 0`.
- `H1`: mean realized return per closed trade `> 0`.

Your project-level operational claim ("reliable profitable signal") is stronger than `H1`, so it also needs gate-based reliability evidence (WFO trade density, WFO Sharpe/Calmar, multiple-testing control, regime stability, execution realism).

## 2) Exact Evidence Sources (Local Artifacts)

Strict lane (latest strict manifest):

- `d:\sma_outfits_20260218\artifacts\svix211_106\runs\20260224T155856Z\run_manifest.json`
- `generated_at`: `2026-02-24T15:58:56.852048+00:00`
- `config`: `configs\settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml`
- `git_sha`: `3b3e054bdc966b7722a5e29f9409a2c0d27407d1`
- `analysis_start`: `2022-03-31T15:30:00+00:00`
- `analysis_end`: `2026-02-24T15:30:39+00:00`
- stage outcomes: `backfill=completed`, `replay=completed`, `report=completed`, `validate-config=skipped`

Replication lane (latest replication manifest):

- `d:\sma_outfits_20260218\artifacts\svix211_106\runs\20260224T161452Z\run_manifest.json`
- `generated_at`: `2026-02-24T16:14:52.618721+00:00`
- `config`: `configs\settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml`
- `git_sha`: `3b3e054bdc966b7722a5e29f9409a2c0d27407d1`
- `analysis_start`: `2022-03-31T16:00:00+00:00`
- `analysis_end`: `2026-02-24T15:30:39+00:00`
- stage outcomes: `backfill=completed`, `replay=completed`, `report=completed`, `validate-config=completed`

Discovered full-range anchors:

- `d:\sma_outfits_20260218\artifacts\readiness\discovered_range_strict.json`
  - `full_range_start=2022-03-31T15:30:00+00:00`
- `d:\sma_outfits_20260218\artifacts\readiness\discovered_range_replication.json`
  - `full_range_start=2022-03-31T16:00:00+00:00`

Conclusion on full-range execution status:

- Strict lane: run start equals discovered full-range start.
- Replication lane: run start equals discovered full-range start.
- Both lanes were already run on the discovered full date range.

## 3) Immutability Caveat (Important)

- `readiness_acceptance.json` currently reflects the replication lane (`config ...crossctx_replication_v1.yaml`, checked at `2026-02-24T16:15:20.266709+00:00`).
- Strict/replication outputs share report paths in some cases (for example `20220331_20260224_*`), so later runs can overwrite earlier lane artifacts.
- Strict-lane statistical results below are taken from strict-specific timestamped report artifacts that remain present:
  - `d:\sma_outfits_20260218\artifacts\svix211_106\reports\20211201T153000_20260224T153039.*`

## 4) Core Statistical Results

### 4.1 Distribution and Risk Diagnostics (close-time statistical validation)

| Metric | Strict lane | Replication lane |
| --- | --- | --- |
| Closed positions | 96 | 215 |
| Total signals | 96 | 215 |
| Mean R | 63.7038479167 | 88.3108665117 |
| Median R | -0.6262500000 | -0.4742000000 |
| Std R | 294.0690809422 | 373.9661422473 |
| Skew | 9.0141940139 | 6.0100748118 |
| Kurtosis | 85.3104266654 | 41.2648196057 |
| Win rate | 0.4270833333 | 0.4930232558 |
| Payoff ratio | 149.3429753910 | 11.0891427579 |
| Max drawdown (R) | -7.3900000000 | -1299.0000000003 |
| Ulcer index (R) | 2.1944368211 | 117.0345032405 |
| Sharpe annualized | 3.4388764423 | 3.7487124816 |
| Sortino annualized | 2971.7493258353 | 13.8126078570 |
| Turnover proxy (positions/month) | 8.0 | 17.9166666667 |

### 4.2 Hypothesis-Test and Uncertainty Outputs

| Metric | Strict lane | Replication lane |
| --- | --- | --- |
| One-sided p-value for mean R > 0 (close validation) | 0.0168970214730374 | 0.0002675013079433963 |
| 95% bootstrap CI for mean R (close validation) | [24.32600054687613, 126.67279247402854] | [45.20850909303085, 140.0913149574435] |
| Test statistic | 2.122520620635018 | 3.462590170127564 |
| Cohen's d | 0.21662885371213586 | 0.23614668959331025 |

Academic-validation bootstrap (stationary block):

| Metric | Strict lane | Replication lane |
| --- | --- | --- |
| Mean | 14.6617795458105 | 78.6651616549492 |
| Std | 8.04522238776166 | 43.5740513987447 |
| CI lower | -2.09894774958325 | 15.547435940333 |
| CI upper | 29.3744744227131 | 177.713888531752 |
| One-sided p-value (mean > 0) | 0.0432 | 0.001 |
| Samples | 10000 | 10000 |
| Block length | 10 | 13 |

Random strategy Monte Carlo comparison:

| Metric | Strict lane | Replication lane |
| --- | --- | --- |
| Null mean | 0.0426568989142439 | 0.515698639571325 |
| Null std | 7.9790351805143 | 44.1193197187112 |
| Observed mean | 14.4927456416028 | 79.2738576677286 |
| One-sided p-value (observed > null) | 0.0256 | 0.0566 |
| Samples | 10000 | 10000 |

### 4.3 Multiple Testing (FDR)

Strict lane:

- method: `fdr_bh`
- threshold: `0.05`
- all_pass: `true`
- rows:
  - `magnetized_buy`: raw p `0.0324141318226716`, q `0.0324141318226716`, pass `true`

Replication lane:

- method: `fdr_bh`
- threshold: `0.07`
- all_pass: `true`
- rows:
  - `magnetized_buy`: raw p `0.0143526721105893`, q `0.0243651474295571`, pass `true`
  - `optimized_buy`: raw p `0.0243651474295571`, q `0.0243651474295571`, pass `true`

### 4.4 WFO Reliability and Gate Outcomes

#### Strict lane (academic validation not ready)

- `ready=false`
- blockers:
  - `wfo_min_closed_trades_per_fold_violation:2<14`
  - `oos_sharpe_below_threshold:-37.082376<1.500000`
- WFO aggregate:
  - folds `5`, min fold trades `2`, all folds min-trade pass `false`
  - OOS mean R `18.1909952064959`
  - OOS total R `1291.56065966121`
  - OOS Sharpe `-37.0823758456681`
  - OOS Calmar `51.0107109638417`
- WFO feasibility:
  - available months `48`
  - required months for min folds `47`
  - max feasible folds `3`
  - feasible `true`

Strict WFO folds:

| Fold | Closed trades | Mean R | Sharpe | Calmar | Min-trade gate |
| --- | --- | --- | --- | --- | --- |
| 1 | 32 | 21.5720670668906 | 3.95439235613047 | 50.3773077204606 | true |
| 2 | 17 | 20.4275942712121 | 3.04180019437833 | 43.7083804294335 | true |
| 3 | 12 | 12.4601916875086 | 3.5561171227477 | 25.6025242126514 | false |
| 4 | 8 | 15.7829394087503 | 4.89471152391103 | 182.441601527918 | false |
| 5 | 2 | -10.9002023050002 | -1446.46547070365 | -250.059469348757 | false |

#### Replication lane (academic validation ready)

- `ready=true`
- blockers: none
- WFO aggregate:
  - folds `4`, min fold trades `8`, all folds min-trade pass `true`
  - OOS mean R `124.549918324916`
  - OOS total R `10586.7430576178`
  - OOS Sharpe `6.09456344643072`
  - OOS Calmar `152.667371882576`
- WFO feasibility:
  - available months `47`
  - required months for min folds `36`
  - max feasible folds `3`
  - feasible `true`

Replication WFO folds:

| Fold | Closed trades | Mean R | Sharpe | Calmar | Min-trade gate |
| --- | --- | --- | --- | --- | --- |
| 1 | 40 | 31.4139237535051 | 8.33606750473008 | 103.699478719218 | true |
| 2 | 17 | 1.21714716829952 | 0.0405015832180341 | 0.720317398324915 | true |
| 3 | 8 | 931.262803134602 | 10.2988417736306 | 450.151309920829 | true |
| 4 | 20 | 92.9696090269866 | 5.07579658268284 | 260.764579305603 | true |

### 4.5 Regime Stability

Strict lane:

- passes `true`
- high-vol count `48`, mean R `12.2160641904275`
- low-vol count `46`, mean R `16.8684132428291`
- proxy symbol `VIXY`

Replication lane:

- passes `true`
- high-vol count `81`, mean R `122.861143162197`
- low-vol count `82`, mean R `36.2181244353882`
- proxy symbol `VIXY`

### 4.6 Replication Check Matrix (id/description/evidence/passed/weight)

Strict lane score: `8/10` (`0.8`)

| id | description | evidence_key | passed | weight |
| --- | --- | --- | --- | --- |
| wfo_min_folds | Walk-forward fold count meets configured minimum. | wfo_min_folds | true | 1.0 |
| wfo_min_closed_trades_per_fold | Each OOS fold has enough closed trades. | wfo_min_closed_trades_per_fold | false | 1.0 |
| oos_sharpe_threshold | Aggregate OOS Sharpe meets configured threshold. | oos_sharpe_threshold | false | 1.0 |
| oos_calmar_threshold | Aggregate OOS Calmar meets configured threshold. | oos_calmar_threshold | true | 1.0 |
| bootstrap_significance | One-sided bootstrap p-value passes alpha threshold. | bootstrap_significance | true | 1.0 |
| fdr_gate | FDR-adjusted q-values pass threshold. | fdr_gate | true | 1.0 |
| regime_positive_means | Regime split means are positive for high-vol and low-vol. | regime_positive_means | true | 1.0 |
| random_mc_outperformance | Observed average return beats random-strategy Monte Carlo expectation. | random_mc_outperformance | true | 1.0 |
| execution_realism_non_negative | Most conservative net scenario is not strongly negative. | execution_realism_non_negative | true | 1.0 |
| citation_pack_present | Citation pack loaded and valid. | citation_pack_present | true | 1.0 |

Replication lane score: `10/10` (`1.0`)

| id | description | evidence_key | passed | weight |
| --- | --- | --- | --- | --- |
| wfo_min_folds | Walk-forward fold count meets configured minimum. | wfo_min_folds | true | 1.0 |
| wfo_min_closed_trades_per_fold | Each OOS fold has enough closed trades. | wfo_min_closed_trades_per_fold | true | 1.0 |
| oos_sharpe_threshold | Aggregate OOS Sharpe meets configured threshold. | oos_sharpe_threshold | true | 1.0 |
| oos_calmar_threshold | Aggregate OOS Calmar meets configured threshold. | oos_calmar_threshold | true | 1.0 |
| bootstrap_significance | One-sided bootstrap p-value passes alpha threshold. | bootstrap_significance | true | 1.0 |
| fdr_gate | FDR-adjusted q-values pass threshold. | fdr_gate | true | 1.0 |
| regime_positive_means | Regime split means are positive for high-vol and low-vol. | regime_positive_means | true | 1.0 |
| random_mc_outperformance | Observed average return beats random-strategy Monte Carlo expectation. | random_mc_outperformance | true | 1.0 |
| execution_realism_non_negative | Most conservative net scenario is not strongly negative. | execution_realism_non_negative | true | 1.0 |
| citation_pack_present | Citation pack loaded and valid. | citation_pack_present | true | 1.0 |

## 5) Decision on the Null

For the conventional no-edge null (`mean R <= 0`):

- Replication lane: reject `H0` at conventional levels based on both close-validation test and academic bootstrap (`p=0.001`), with positive CIs and FDR pass.
- Strict lane: also shows positive-mean significance in close validation and bootstrap, but fails key reliability gates (trade density and OOS Sharpe), so it is not statistically "production reliable."

For the stronger project claim ("reliable profitable signal"):

- Replication lane currently has substantial support under the project's gate framework (`ready=true`, 10/10 checks).
- But reliability remains tail-sensitive (high skew/kurtosis, large drawdown, and one WFO fold with very low Sharpe), so this should be treated as "supported but fragile," not "universally stable."

## 6) Is Item 0 Needed Before Your Step Plan?

Short answer: yes, but as a lightweight protocol hardening step, not a full redesign.

Recommended Item 0:

1. Freeze and document the formal null/alternative in repo docs and run manifests.
2. Record the number of tried configs/hypotheses and add a global overfitting correction (for example, White Reality Check / SPA / deflated Sharpe workflow).
3. Add immutable lane-specific artifact namespaces (strict vs replication) so inference provenance cannot be overwritten.
4. Lock an untouched forward holdout window for final confirmation after infrastructure changes.

You already have strong statistical machinery; Item 0 is about inferential hygiene and auditability.
