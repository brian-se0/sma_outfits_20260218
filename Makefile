VENV := .venv
PYTHON := $(VENV)\Scripts\python.exe
PIP := $(PYTHON) -m pip
INSTALL_STAMP := $(VENV)\.install.stamp
INSTALL_DEPS := pyproject.toml

STRICT_CONFIG_PATH ?= configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml## help: Strict canonical config path.
REPLICATION_CONFIG_PATH ?= configs/settings.jan2025_confluence_atr_svix211_106_crossctx_replication_v1.yaml## help: Replication canonical config path.
CONFIG_PROFILE ?= strict## help: Config profile selector (strict|replication).
ifeq ($(CONFIG_PROFILE),strict)
ACTIVE_CONFIG := $(STRICT_CONFIG_PATH)
else ifeq ($(CONFIG_PROFILE),replication)
ACTIVE_CONFIG := $(REPLICATION_CONFIG_PATH)
else
$(error Unsupported CONFIG_PROFILE='$(CONFIG_PROFILE)'. Use: strict, replication)
endif

# e2e flag-driven defaults
# Usage examples:
#   make e2e
#   make e2e PROFILE=week SYMBOLS=SPY
#   make e2e PROFILE=max UNIVERSE=all TIMEFRAME_SET=all
#   make discover-range CONFIG_PROFILE=strict UNIVERSE=all TIMEFRAME_SET=all
#   make e2e PROFILE=max_common UNIVERSE=all TIMEFRAME_SET=all
#   make e2e PROFILE=max UNIVERSE=all_stocks TIMEFRAME_SET=all
#   make e2e PROFILE=month UNIVERSE=core_expanded TIMEFRAME_SET=core
#   make e2e PROFILE=custom START=2025-01-02T14:30:00Z END=2025-01-31T21:00:00Z
#   make e2e PROFILE=month WARMUP_DAYS=150
#   make e2e PROFILE=month STAGES=backfill,replay,report
PROFILE ?= smoke## help: Range profile (smoke|day|week|month|max|max_common|custom).
UNIVERSE ?= core## help: Symbol universe preset (core|core_expanded|all_stocks|all).
TIMEFRAME_SET ?= core## help: Timeframe preset (core|all).
STAGES ?= validate-config,backfill,replay,report## help: e2e stages CSV subset of validate-config,backfill,replay,report.
CORE_EXPANDED_SYMBOLS := QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY
ALL_STOCK_SYMBOLS := AAPL,AMDL,CONL,DUST,ETHU,IYR,MUU,NVD,NVDX,SPXU,SPY,QQQ,DIA,TNA,UPRO,TQQQ,TSLL,TSLT,TZA,SQQQ,UDOW,SDOW,SOXL,SOXS,SVIX,VIXY,XLF,JPM,NVDA,TSLA,AMD,GME,RWM,IWM,SMH,FAS,FAZ

comma := ,
empty :=
space := $(empty) $(empty)
STAGES_NORMALIZED := $(subst $(space),,$(STAGES))
STAGE_VALUES := $(subst $(comma),$(space),$(STAGES_NORMALIZED))
VALID_STAGES := validate-config backfill replay report
INVALID_STAGES := $(filter-out $(VALID_STAGES),$(STAGE_VALUES))
ifneq ($(strip $(INVALID_STAGES)),)
$(error Unsupported STAGES value(s): $(INVALID_STAGES). Allowed: $(VALID_STAGES))
endif
normalize_csv = $(subst $(space),,$(1))
has_stage_in = $(findstring $(comma)$(2)$(comma),$(comma)$(call normalize_csv,$(1))$(comma))
arg_if_set = $(if $(strip $(2)),$(1) $(2),)
or_default = $(if $(strip $(1)),$(1),$(2))

# Storage safety guard for larger e2e profiles.
MIN_FREE_GB ?= 50## help: Minimum free disk GB required for heavy profiles.

# Alpaca Trading API Basic/free plan defaults:
# - Historical equities timeframe: since 2016.
# - Historical endpoint limitation: latest 15 minutes.
ALPACA_BASIC_HISTORICAL_START ?= 2016-01-01T00:00:00Z## help: Alpaca Basic historical start anchor.
ALPACA_BASIC_HISTORICAL_DELAY_MINUTES ?= 15## help: Alpaca Basic historical delay minutes.
MAX_START ?= $(ALPACA_BASIC_HISTORICAL_START)
MAX_END ?= $(shell powershell -NoProfile -Command "[Console]::Out.Write((Get-Date).ToUniversalTime().AddMinutes(-1.0 * [double]'$(ALPACA_BASIC_HISTORICAL_DELAY_MINUTES)').ToString('yyyy-MM-ddTHH:mm:ssZ'))")
DISCOVER_START ?= $(ALPACA_BASIC_HISTORICAL_START)
DISCOVER_RANGE_OUTPUT ?= artifacts/readiness/discovered_range_manifest.json## help: discover-range output JSON path.
READINESS_ACCEPTANCE_OUTPUT ?= artifacts/readiness/readiness_acceptance.json## help: verify-readiness output JSON path.
READINESS_END ?= $(MAX_END)## help: Readiness/discover end timestamp.
FULL_RANGE_START_COMPUTED := $(shell powershell -NoProfile -Command 'if (Test-Path "$(DISCOVER_RANGE_OUTPUT)") { $$payload = Get-Content -Path "$(DISCOVER_RANGE_OUTPUT)" -Raw | ConvertFrom-Json; $$value = $$payload.full_range_start; if ($$null -ne $$value) { if ($$value -is [datetime]) { $$value = $$value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }; [Console]::Out.Write([string]$$value) } }')
FULL_RANGE_START ?= $(FULL_RANGE_START_COMPUTED)## help: Auto-loaded full_range_start from discover manifest.
ifeq ($(strip $(FULL_RANGE_START)),)
FULL_RANGE_START := $(FULL_RANGE_START_COMPUTED)
endif
# e2e warmup + reporting window controls:
# - Analysis window is what report summarizes.
# - Backfill/replay windows can include additional warmup bars.
WARMUP_DAYS ?= 120## help: Warmup days before analysis start for e2e.
COMMON_ANALYSIS_START_COMPUTED := $(shell powershell -NoProfile -Command 'if ("$(FULL_RANGE_START)" -ne "") { $$start=[DateTimeOffset]::Parse("$(FULL_RANGE_START)"); $$days=[double]"$(WARMUP_DAYS)"; [Console]::Out.Write($$start.AddDays($$days).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")) }')
COMMON_ANALYSIS_START ?= $(COMMON_ANALYSIS_START_COMPUTED)## help: Auto-computed analysis start for PROFILE=max_common from FULL_RANGE_START + WARMUP_DAYS.
VERIFY_READINESS_ARGS ?=## help: Extra verify-readiness CLI args (for example --require-academic-validation).

ifeq ($(PROFILE),smoke)
PROFILE_START := 2025-01-02T14:30:00Z
PROFILE_END := 2025-01-02T21:00:00Z
else ifeq ($(PROFILE),day)
PROFILE_START := 2025-01-02T14:30:00Z
PROFILE_END := 2025-01-02T21:00:00Z
else ifeq ($(PROFILE),week)
PROFILE_START := 2025-01-02T14:30:00Z
PROFILE_END := 2025-01-09T21:00:00Z
else ifeq ($(PROFILE),month)
PROFILE_START := 2025-01-02T14:30:00Z
PROFILE_END := 2025-01-31T21:00:00Z
else ifeq ($(PROFILE),max)
PROFILE_START := $(MAX_START)
PROFILE_END := $(MAX_END)
else ifeq ($(PROFILE),max_common)
ifeq ($(strip $(FULL_RANGE_START)),)
$(error PROFILE='max_common' requires DISCOVER_RANGE_OUTPUT with full_range_start. Run: make discover-range CONFIG_PROFILE=$(CONFIG_PROFILE) UNIVERSE=all TIMEFRAME_SET=all)
endif
ifeq ($(strip $(COMMON_ANALYSIS_START)),)
$(error PROFILE='max_common' could not compute analysis start from FULL_RANGE_START='$(FULL_RANGE_START)' and WARMUP_DAYS='$(WARMUP_DAYS)')
endif
PROFILE_START := $(COMMON_ANALYSIS_START)
PROFILE_END := $(MAX_END)
else ifeq ($(PROFILE),custom)
ifeq ($(origin START),undefined)
$(error PROFILE='custom' requires START=YYYY-MM-DDTHH:MM:SSZ)
endif
ifeq ($(origin END),undefined)
$(error PROFILE='custom' requires END=YYYY-MM-DDTHH:MM:SSZ)
endif
PROFILE_START := $(START)
PROFILE_END := $(END)
else
$(error Unsupported PROFILE='$(PROFILE)'. Use: smoke, day, week, month, max, max_common, custom)
endif

ifeq ($(UNIVERSE),core)
PROFILE_SYMBOLS := QQQ,RWM
else ifeq ($(UNIVERSE),core_expanded)
PROFILE_SYMBOLS := $(CORE_EXPANDED_SYMBOLS)
else ifeq ($(UNIVERSE),all_stocks)
PROFILE_SYMBOLS := $(ALL_STOCK_SYMBOLS)
else ifeq ($(UNIVERSE),all)
PROFILE_SYMBOLS :=
else
$(error Unsupported UNIVERSE='$(UNIVERSE)'. Use: core, core_expanded, all_stocks, all)
endif

ifeq ($(TIMEFRAME_SET),core)
PROFILE_TIMEFRAMES := 30m,1h
else ifeq ($(TIMEFRAME_SET),all)
PROFILE_TIMEFRAMES :=
else
$(error Unsupported TIMEFRAME_SET='$(TIMEFRAME_SET)'. Use: core, all)
endif

START ?= $(PROFILE_START)## help: Start timestamp (required when PROFILE=custom).
END ?= $(PROFILE_END)## help: End timestamp (required when PROFILE=custom).
SYMBOLS ?= $(PROFILE_SYMBOLS)## help: Symbols CSV override.
TIMEFRAMES ?= $(PROFILE_TIMEFRAMES)## help: Timeframes CSV override.
BACKFILL_SYMBOLS ?= $(SYMBOLS)## help: Backfill symbols CSV (defaults to SYMBOLS).
BACKFILL_TIMEFRAMES ?= $(TIMEFRAMES)## help: Backfill timeframes CSV (defaults to TIMEFRAMES).
REPLAY_SYMBOLS ?= $(SYMBOLS)## help: Replay symbols CSV (defaults to SYMBOLS).
REPLAY_TIMEFRAMES ?= $(TIMEFRAMES)## help: Replay timeframes CSV (defaults to TIMEFRAMES).

ANALYSIS_START ?= $(START)## help: Analysis/report start for e2e.
ANALYSIS_END ?= $(END)## help: Analysis/report end for e2e.
WARMUP_START ?= $(shell powershell -NoProfile -Command '$$start=[DateTimeOffset]::Parse("$(ANALYSIS_START)"); $$days=[double]"$(WARMUP_DAYS)"; [Console]::Out.Write($$start.AddDays(-1.0 * $$days).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))')
BACKFILL_START ?= $(WARMUP_START)
BACKFILL_END ?= $(ANALYSIS_END)
REPLAY_START ?= $(WARMUP_START)
REPLAY_END ?= $(ANALYSIS_END)
DEFAULT_REPORT_RANGE := $(ANALYSIS_START),$(ANALYSIS_END)
REPORT_RANGE ?=## help: Report range as start,end (defaults to analysis window in e2e).
REPORT_RANGE_FOR_E2E := $(if $(strip $(REPORT_RANGE)),$(REPORT_RANGE),$(DEFAULT_REPORT_RANGE))

SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)
BACKFILL_SYMBOLS_ARG := $(if $(strip $(BACKFILL_SYMBOLS)),--symbols $(BACKFILL_SYMBOLS),)
BACKFILL_TIMEFRAMES_ARG := $(if $(strip $(BACKFILL_TIMEFRAMES)),--timeframes $(BACKFILL_TIMEFRAMES),)
REPLAY_SYMBOLS_ARG := $(if $(strip $(REPLAY_SYMBOLS)),--symbols $(REPLAY_SYMBOLS),)
REPLAY_TIMEFRAMES_ARG := $(if $(strip $(REPLAY_TIMEFRAMES)),--timeframes $(REPLAY_TIMEFRAMES),)

define run_storage_preflight
	powershell -NoProfile -Command "$$profile='$(1)'; $$largeProfiles=@('week','month','max','max_common','custom'); if (-not ($$largeProfiles -contains $$profile)) { Write-Output ('storage preflight: skipped for PROFILE=' + $$profile); exit 0 }; $$targetPath = [System.IO.Path]::GetFullPath('$(CURDIR)'); $$root = [System.IO.Path]::GetPathRoot($$targetPath); if ([string]::IsNullOrWhiteSpace($$root)) { throw ('Unable to resolve path root for ' + $$targetPath) }; $$driveInfo = [System.IO.DriveInfo]::new($$root); $$freeBytes = [int64]$$driveInfo.AvailableFreeSpace; $$thresholdGb = [double]'$(MIN_FREE_GB)'; $$thresholdBytes = [int64]($$thresholdGb * 1GB); if ($$freeBytes -lt $$thresholdBytes) { throw ('Insufficient free disk space for PROFILE=' + $$profile + ': free=' + $$freeBytes + ' bytes, required>=' + $$thresholdBytes + ' bytes (MIN_FREE_GB=' + $$thresholdGb + ')') }; Write-Output ('storage preflight: ok PROFILE=' + $$profile + ' free_bytes=' + $$freeBytes + ' threshold_bytes=' + $$thresholdBytes + ' root=' + $$root)"
endef

define run_pipeline
	powershell -NoProfile -Command "Write-Output ('e2e config: profile=$(PIPE_PROFILE) stages=$(call normalize_csv,$(PIPE_STAGES)) symbols=$(PIPE_SYMBOLS) timeframes=$(PIPE_TIMEFRAMES) backfill_symbols=$(call or_default,$(PIPE_BACKFILL_SYMBOLS),$(PIPE_SYMBOLS)) backfill_timeframes=$(call or_default,$(PIPE_BACKFILL_TIMEFRAMES),$(PIPE_TIMEFRAMES)) replay_symbols=$(call or_default,$(PIPE_REPLAY_SYMBOLS),$(PIPE_SYMBOLS)) replay_timeframes=$(call or_default,$(PIPE_REPLAY_TIMEFRAMES),$(PIPE_TIMEFRAMES)) analysis_start=$(PIPE_ANALYSIS_START) analysis_end=$(PIPE_ANALYSIS_END) warmup_days=$(PIPE_WARMUP_DAYS) warmup_start=$(PIPE_WARMUP_START) backfill_start=$(PIPE_BACKFILL_START) backfill_end=$(PIPE_BACKFILL_END) replay_start=$(PIPE_REPLAY_START) replay_end=$(PIPE_REPLAY_END) report_range=$(PIPE_REPORT_RANGE)')"
	$(if $(call has_stage_in,$(PIPE_STAGES),validate-config),$(PYTHON) -m sma_outfits.cli validate-config --config $(PIPE_CONFIG),powershell -NoProfile -Command "Write-Output 'e2e skip: validate-config'")
	$(if $(call has_stage_in,$(PIPE_STAGES),backfill),$(PYTHON) -m sma_outfits.cli backfill --config $(PIPE_CONFIG) $(call arg_if_set,--symbols,$(call or_default,$(PIPE_BACKFILL_SYMBOLS),$(PIPE_SYMBOLS))) --start $(PIPE_BACKFILL_START) --end $(PIPE_BACKFILL_END) $(call arg_if_set,--timeframes,$(call or_default,$(PIPE_BACKFILL_TIMEFRAMES),$(PIPE_TIMEFRAMES))),powershell -NoProfile -Command "Write-Output 'e2e skip: backfill'")
	$(if $(call has_stage_in,$(PIPE_STAGES),replay),$(PYTHON) -m sma_outfits.cli replay --config $(PIPE_CONFIG) --start $(PIPE_REPLAY_START) --end $(PIPE_REPLAY_END) $(call arg_if_set,--symbols,$(call or_default,$(PIPE_REPLAY_SYMBOLS),$(PIPE_SYMBOLS))) $(call arg_if_set,--timeframes,$(call or_default,$(PIPE_REPLAY_TIMEFRAMES),$(PIPE_TIMEFRAMES))),powershell -NoProfile -Command "Write-Output 'e2e skip: replay'")
	$(if $(call has_stage_in,$(PIPE_STAGES),report),$(PYTHON) -m sma_outfits.cli report --config $(PIPE_CONFIG) $(call arg_if_set,--range,$(PIPE_REPORT_RANGE)),powershell -NoProfile -Command "Write-Output 'e2e skip: report'")
	$(PYTHON) -m sma_outfits.cli write-run-manifest --config $(PIPE_CONFIG) --profile $(PIPE_PROFILE) --stages $(call normalize_csv,$(PIPE_STAGES)) --analysis-start $(PIPE_ANALYSIS_START) --analysis-end $(PIPE_ANALYSIS_END) --warmup-days $(PIPE_WARMUP_DAYS) --warmup-start $(PIPE_WARMUP_START) --backfill-start $(PIPE_BACKFILL_START) --backfill-end $(PIPE_BACKFILL_END) --replay-start $(PIPE_REPLAY_START) --replay-end $(PIPE_REPLAY_END) --report-range $(PIPE_REPORT_RANGE) --command "$(PIPE_COMMAND)" $(call arg_if_set,--symbols,$(PIPE_SYMBOLS)) $(call arg_if_set,--timeframes,$(PIPE_TIMEFRAMES))
	powershell -NoProfile -Command "Write-Output 'e2e complete'"
endef

define set_pipe_context_e2e
$(eval PIPE_CONFIG := $(ACTIVE_CONFIG))
$(eval PIPE_PROFILE := $(PROFILE))
$(eval PIPE_STAGES := $(STAGES_NORMALIZED))
$(eval PIPE_SYMBOLS := $(SYMBOLS))
$(eval PIPE_TIMEFRAMES := $(TIMEFRAMES))
$(eval PIPE_BACKFILL_SYMBOLS := $(BACKFILL_SYMBOLS))
$(eval PIPE_BACKFILL_TIMEFRAMES := $(BACKFILL_TIMEFRAMES))
$(eval PIPE_REPLAY_SYMBOLS := $(REPLAY_SYMBOLS))
$(eval PIPE_REPLAY_TIMEFRAMES := $(REPLAY_TIMEFRAMES))
$(eval PIPE_ANALYSIS_START := $(ANALYSIS_START))
$(eval PIPE_ANALYSIS_END := $(ANALYSIS_END))
$(eval PIPE_WARMUP_DAYS := $(WARMUP_DAYS))
$(eval PIPE_WARMUP_START := $(WARMUP_START))
$(eval PIPE_BACKFILL_START := $(BACKFILL_START))
$(eval PIPE_BACKFILL_END := $(BACKFILL_END))
$(eval PIPE_REPLAY_START := $(REPLAY_START))
$(eval PIPE_REPLAY_END := $(REPLAY_END))
$(eval PIPE_REPORT_RANGE := $(REPORT_RANGE_FOR_E2E))
$(eval PIPE_COMMAND := make e2e CONFIG_PROFILE=$(CONFIG_PROFILE))
endef

.PHONY: help venv install validate-config discover-range verify-readiness test dead-code-check backfill replay run-live report migrate-storage-layout preflight-storage e2e clean clean-all

help: ## Print available targets, common variables, and examples.
	powershell -NoProfile -Command "$$lines = Get-Content -Path 'Makefile'; $$targets = @(); $$vars = @(); foreach ($$line in $$lines) { if ($$line -match '^(?<target>[A-Za-z0-9_.-]+):(?:[^#]|#(?!#))*## (?<desc>.+)$$') { if ($$matches.target -notlike '_*') { $$targets += [PSCustomObject]@{ key = $$matches.target; desc = $$matches.desc } } }; if ($$line -match '^(?<var>[A-Z][A-Z0-9_]*)\s*(?:\?|:|\+)?=\s*.*##\s*help:\s*(?<desc>.+)$$') { $$vars += [PSCustomObject]@{ key = $$matches.var; desc = $$matches.desc } } }; Write-Output 'Targets:'; foreach ($$entry in $$targets) { Write-Output ('  make ' + $$entry.key + ' - ' + $$entry.desc) }; Write-Output ''; Write-Output 'Common variables:'; foreach ($$entry in $$vars) { Write-Output ('  ' + $$entry.key + ' - ' + $$entry.desc) }; Write-Output ''; Write-Output 'Examples:'; $$examples = @('make discover-range CONFIG_PROFILE=strict UNIVERSE=all TIMEFRAME_SET=all','make e2e CONFIG_PROFILE=strict PROFILE=max_common UNIVERSE=all TIMEFRAME_SET=all','make discover-range CONFIG_PROFILE=replication UNIVERSE=all_stocks TIMEFRAME_SET=all','make migrate-storage-layout CONFIG_PROFILE=strict','make e2e CONFIG_PROFILE=strict PROFILE=custom START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all STAGES=validate-config,backfill','make e2e CONFIG_PROFILE=replication PROFILE=month UNIVERSE=core_expanded TIMEFRAME_SET=core','make verify-readiness CONFIG_PROFILE=replication START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all'); foreach ($$e in $$examples) { Write-Output ('  ' + $$e) }"

venv: ## Create/repair .venv and enforce Python 3.14.3.
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; if (!(Test-Path '$(PYTHON)')) { py -3.14 -m venv $(VENV) }; if (!(Test-Path '$(VENV)\\Scripts\\pip.exe')) { & '$(PYTHON)' -m ensurepip --upgrade --default-pip }"
	$(PYTHON) -c "import sys; assert sys.version_info[:3] == (3, 14, 3), f'Python 3.14.3 required, got {sys.version.split()[0]}'"

$(INSTALL_STAMP): $(INSTALL_DEPS) | venv
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pip install -e .[dev]"
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '$(VENV)' | Out-Null; Set-Content -Path '$(INSTALL_STAMP)' -Value (Get-Date -Format o)"

install: $(INSTALL_STAMP) ## Install project and dev dependencies into .venv.

validate-config: install ## Validate config schema and runtime settings.
	$(PYTHON) -m sma_outfits.cli validate-config --config $(ACTIVE_CONFIG)

discover-range: install ## Discover earliest available data range and write manifest.
	$(PYTHON) -m sma_outfits.cli discover-range --config $(ACTIVE_CONFIG) $(SYMBOLS_ARG) $(TIMEFRAMES_ARG) --output $(DISCOVER_RANGE_OUTPUT) --start $(DISCOVER_START) --end $(READINESS_END)

verify-readiness: install ## Run readiness acceptance checks and write JSON summary.
	$(PYTHON) -m sma_outfits.cli verify-readiness --config $(ACTIVE_CONFIG) --start $(START) --end $(END) $(SYMBOLS_ARG) $(TIMEFRAMES_ARG) --output $(READINESS_ACCEPTANCE_OUTPUT) $(VERIFY_READINESS_ARGS)

test: install ## Run full test suite.
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp\\pytest' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pytest"

dead-code-check: install ## Run dead-code analysis gate.
	$(PYTHON) -m vulture src --min-confidence 90 --ignore-names cls,settings_cls,init_settings,env_settings,file_secret_settings

backfill: install ## Backfill selected symbols/timeframes over START..END.
	$(PYTHON) -m sma_outfits.cli backfill --config $(ACTIVE_CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(START) --end $(END) $(BACKFILL_TIMEFRAMES_ARG)

replay: install ## Replay selected symbols/timeframes over START..END.
	$(PYTHON) -m sma_outfits.cli replay --config $(ACTIVE_CONFIG) --start $(START) --end $(END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG)

run-live: install ## Run live execution path.
	$(PYTHON) -m sma_outfits.cli run-live --config $(ACTIVE_CONFIG)

report: install ## Build report artifacts (optionally with REPORT_RANGE).
	$(PYTHON) -m sma_outfits.cli report --config $(ACTIVE_CONFIG) $(if $(strip $(REPORT_RANGE)),--range $(REPORT_RANGE),)

migrate-storage-layout: install ## Migrate storage layout in non-dry-run mode.
	$(PYTHON) -m sma_outfits.cli migrate-storage-layout --config $(ACTIVE_CONFIG) --no-dry-run

preflight-storage: ## Check free disk space for heavier profile runs.
	$(call run_storage_preflight,$(PROFILE))

e2e: preflight-storage ## Run staged non-live pipeline and write run manifest.
	$(call set_pipe_context_e2e)
	$(call run_pipeline)

clean: ## Remove artifacts, caches, and build outputs (keeps .venv).
	powershell -NoProfile -Command "$$targets = @('artifacts', '.tmp', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'build', 'dist'); foreach ($$t in $$targets) { if (Test-Path -LiteralPath $$t) { cmd /d /c ('rmdir /s /q ""{0}""' -f $$t) | Out-Null; if (Test-Path -LiteralPath $$t) { throw ('Failed to remove ' + $$t) } } }; $$scanRoots = @(Get-ChildItem -Path . -Directory -Force | Where-Object { $$_.Name -notin @('.venv', '.git') } | ForEach-Object { $$_.FullName }); if ($$scanRoots.Count -gt 0) { Get-ChildItem -Path $$scanRoots -Recurse -Directory -Filter '__pycache__' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path $$scanRoots -Recurse -File -Include '*.pyc','*.pyo' -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue }; Get-ChildItem -Path . -Directory -Filter '*.egg-info' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -File -Include '*.pyc','*.pyo' -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue"

clean-all: clean ## Run clean and also remove .venv.
	powershell -NoProfile -Command "if (Test-Path '$(VENV)') { Remove-Item -Recurse -Force '$(VENV)' }"
