# SMA-outfits

Deterministic, fail-fast SMA-outfits research stack built around Alpaca free data only.

## Current Status

- Phase 1 historical closeout is complete.
- Phase 2 is the current focus: live-paper hardening for broker submission, fill processing, and drawdown alerting.
- Supported runtime profiles are `context` and `strict` only. `context` is the operational default.

## Repository Contract

- Python runtime is fixed at `3.14.3` in a local `.venv`.
- Project workflows run through `Makefile` targets only.
- Secrets and Alpaca credentials are read from `.env.local` only.
- Data and runtime paths are Alpaca-only and constrained to free-tier historical bounds.
- Missing, stale, malformed, or inconsistent required inputs are hard errors. There is no alternate-provider or placeholder fallback behavior.
- Reports are bar-level approximations and do not claim tick/second/millisecond reproduction.
- Active profiles write to isolated artifact/state roots under `artifacts/svix211_106/<profile>`.
- Live execution currently supports state persistence, duplicate-bar protection, stale-feed recovery, and optional reconciliation.
- Live execution does not yet submit broker orders or process fill callbacks.
- `make run ACTION=phase1-close` defaults to a max-common historical recheck and auto-discovers the per-profile common start before each pass.

## Common Workflows

```powershell
make setup
make run
make run ACTION=e2e CONFIG_PROFILE=strict PROFILE=month
make run ACTION=phase1-close
make run ACTION=phase2-preflight CONFIG_PROFILE=context
make qa
make clean SCOPE=all
```

Additional command details live in `make_commands.md`.

## Repository Layout

- `src/sma_outfits/`: application code for config, data, indicators, signals, risk, replay, live execution, reporting, and CLI entrypoints
- `configs/`: canonical runtime profile YAML files
- `tests/`: unit and integration coverage
- `scripts/`: repo-maintained orchestration helpers such as `phase1_close.ps1`
- `docs/history/`: archived historical writeups and preserved source-context documents
- `ASSUMPTIONS.md`: concise assumptions and ambiguity register
- `Phase2_PLAN.md`: current Phase 2 work plan

## Historical Material

Historical source/context documents were moved out of the repository root so the root docs only describe the current codebase.

- `docs/history/README.md`
- `docs/history/phase1/End_of_Phase1_Report.md`
- `docs/history/phase1/Null_Hypothesis.md`
- `docs/history/source/README_original_context.md`
- `docs/history/source/UnfairMkt_X_Context.md`

## Notes

- `CONFIG_PROFILE=replication` is historical only and now hard-fails.
- Closed-trade analytics must filter `positions` on `action == "close"`.
- `context` is the operational validation lane; `strict` is the baseline comparator lane.
