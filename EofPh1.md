# End of Phase 1 Report

Date: 2026-03-04
Project: `sma_outfits_20260218`

## Executive Summary
Phase 1 delivered a stable, reproducible backtesting workflow and a finalized profile policy (`context` as canonical). However, the academic/statistical gate is still the blocker, so Phase 1 is not yet complete for alpha-claim purposes and Phase 2 remains blocked.

## Decision Log (What We Decided and Why)

1. Keep the statistical bar strict (no gate relaxation).
- Decision: Keep strict significance requirements (including FDR/q-value style gating and minimum WFO trade-count constraints).
- Reasoning: We need a defensible alpha claim before live paper escalation. Loosening thresholds would weaken claim integrity.
- Evidence: repeated readiness failures with `fdr_qvalue_gate_failed` and later WFO trade-count violations.

2. Do not proceed to Phase 2 until Phase 1 is statistically significant.
- Decision: Phase 2 (live paper hardening/execution) is blocked until Phase 1 passes the academic gate.
- Reasoning: This was explicitly adopted as a project gate: no live progression without statistically significant alpha.

3. Set `context` as canonical config profile.
- Decision: `context` is the main profile and only `strict|context|replication` are supported.
- Reasoning: mixed profile aliases became redundant and were removed to keep the profile contract unambiguous.
- Implemented in:
  - `Makefile` (`CONFIG_PROFILE ?= context`; explicit support only for `strict|context|replication`)
  - `src/sma_outfits/cli.py` default profile/config alignment
  - `README.md`, `ASSUMPTIONS.md`, and `make_commands.md`

4. Keep strict baseline and replication lane as explicit comparators.
- Decision: Keep strict for baseline and replication as alternate lane, but avoid unsupported source drift.
- Reasoning: Needed for controlled A/B comparisons under fixed windows and scope.

5. Do not force a global SVIX operative key switch to 211.
- Decision: No global route-level 211 conversion.
- Reasoning: Source evidence supports 211 as outfit notation/label but not a universal operative trigger for all actions/timeframes.

6. Use volatility-conditioned trigger logic where required for candle-close confirmation.
- Decision: Preserve conditional trigger logic (crossover/OHLC-touch + volatility close confirmation behavior) where configured.
- Reasoning: Best match to sourced descriptions while remaining implementable with free-data constraints.

7. Rework target focused on failing family (`automated_short`) while preserving test rigor.
- Decision: Perform composition experiments (long-only and hybrid-short variants) instead of weakening statistical criteria.
- Reasoning: Failures indicated family-level quality/trade-density issues, so the fix path is strategy composition/quality, not threshold changes.

8. Keep free-data limitation explicitly documented.
- Decision: Continue labeling outputs as free-Alpaca/IEX bar-proxy approximation versus tick/ms ideal.
- Reasoning: Required for honesty of claims and reproducibility boundaries.

## Implemented During Phase 1

1. Profile policy and defaults finalized around `context`.
2. Mixed-profile deprecation implemented as aliases.
3. Auditability improvements present (position lifecycle `open`/`close` visibility and action breakdown reporting).
4. Close-only risk knob guardrails enforced in config validation.
5. Test suite updated and passing for impacted behavior.

## Statistical Outcome at Phase 1 Boundary

1. Comparative backtests showed performance deltas between profiles, but gates remained blocked for significance/readiness in key runs.
2. Observed blocking reasons across verification runs included:
- `fdr_qvalue_gate_failed`
- `wfo_min_closed_trades_per_fold_violation` (examples observed: `8<14`, `11<14`, `13<14`)
3. Conclusion: Alpha claim is not yet accepted under the required strict gate.

## Plan/Artifact Hygiene Decisions

Based on implemented-or-rejected criteria:
- Remove: `audit_PLAN.md` (implemented)
- Remove: `grok_v6_PLAN.md` (superseded/non-selected path)
- Remove: `replication_lane_pass_PLAN.md` (partially implemented; remaining steps superseded)
- Keep: `Freeze_Enforce_Complete_PLAN.md` (not implemented and not explicitly abandoned)

## Phase Gate Status

- Phase 1 status: Incomplete for alpha certification.
- Phase 2 status: Blocked.

## Next Required Work (to complete Phase 1)

1. Improve strategy composition to satisfy both:
- significance gate (FDR/q-value pass)
- WFO minimum closed trades per fold
2. Re-run fixed-window, fixed-scope protocol across required profiles.
3. Promote to Phase 2 only after academic readiness passes under unchanged strict standards.
