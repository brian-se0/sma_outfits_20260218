VENV := .venv
PYTHON := $(VENV)\Scripts\python.exe
PIP := $(PYTHON) -m pip
INSTALL_STAMP := $(VENV)\.install.stamp
INSTALL_DEPS := pyproject.toml

CONFIG ?= configs/settings.example.yaml

# e2e flag-driven defaults
# Usage examples:
#   make e2e
#   make e2e PROFILE=week SYMBOLS=SPY
#   make e2e PROFILE=max UNIVERSE=all TIMEFRAME_SET=all
#   make e2e PROFILE=max UNIVERSE=all_stocks TIMEFRAME_SET=all
#   make e2e PROFILE=month UNIVERSE=core_expanded TIMEFRAME_SET=core
#   make e2e PROFILE=custom START=2025-01-02T14:30:00Z END=2025-01-31T21:00:00Z
#   make e2e PROFILE=month WARMUP_DAYS=150
#   make e2e PROFILE=month STAGES=backfill,replay,report
PROFILE ?= smoke
UNIVERSE ?= core
TIMEFRAME_SET ?= core
STAGES ?= validate-config,backfill,replay,report
FEATURES ?=
CORE_EXPANDED_SYMBOLS := QQQ,RWM,SVIX,SQQQ,TQQQ,IWM,XLF,SOXL,SPY,UPRO,VIXY
ALL_STOCK_SYMBOLS := AAPL,AMDL,CONL,DUST,ETHU,IYR,MUU,NVD,NVDX,SPXU,SPY,QQQ,DIA,TNA,UPRO,TQQQ,TSLL,TSLT,TZA,SQQQ,UDOW,SDOW,SOXL,SOXS,SVIX,VIXY,XLF,JPM,NVDA,TSLA,AMD,GME,RWM,IWM,SMH,FAS,FAZ

comma := ,
empty :=
space := $(empty) $(empty)
STAGES_NORMALIZED := $(subst $(space),,$(STAGES))
STAGES_CSV := $(comma)$(STAGES_NORMALIZED)$(comma)
STAGE_VALUES := $(subst $(comma),$(space),$(STAGES_NORMALIZED))
VALID_STAGES := validate-config backfill replay report
INVALID_STAGES := $(filter-out $(VALID_STAGES),$(STAGE_VALUES))
ifneq ($(strip $(INVALID_STAGES)),)
$(error Unsupported STAGES value(s): $(INVALID_STAGES). Allowed: $(VALID_STAGES))
endif
has_stage = $(findstring $(comma)$(1)$(comma),$(STAGES_CSV))

# Features are explicitly validated so unknown flags cannot be passed silently.
FEATURES_NORMALIZED := $(subst $(space),,$(FEATURES))
FEATURES_CSV := $(comma)$(FEATURES_NORMALIZED)$(comma)
FEATURE_VALUES := $(subst $(comma),$(space),$(FEATURES_NORMALIZED))
VALID_FEATURES := cross_symbol_context
INVALID_FEATURES := $(filter-out $(VALID_FEATURES),$(FEATURE_VALUES))
ifneq ($(strip $(INVALID_FEATURES)),)
$(error Unsupported FEATURES value(s): $(INVALID_FEATURES). Allowed: $(VALID_FEATURES))
endif
ifneq ($(strip $(FEATURES_NORMALIZED)),)
ifneq ($(findstring $(comma)cross_symbol_context$(comma),$(FEATURES_CSV)),)
$(error FEATURES includes cross_symbol_context, but this is not implemented as a runtime flag; use config-driven route.cross_symbol_context instead)
endif
endif

# Storage safety guard for larger e2e profiles.
MIN_FREE_GB ?= 50

MAX_START ?= 2016-01-01T00:00:00Z
MAX_END ?= $(shell powershell -NoProfile -Command "[Console]::Out.Write((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))")
DISCOVER_START ?= 2000-01-01T00:00:00Z
DISCOVER_RANGE_OUTPUT ?= artifacts/readiness/discovered_range_manifest.json
READINESS_ACCEPTANCE_OUTPUT ?= artifacts/readiness/readiness_acceptance.json
READINESS_END ?= $(MAX_END)
FULL_RANGE_START ?= $(shell powershell -NoProfile -Command "if (Test-Path '$(DISCOVER_RANGE_OUTPUT)') { $$payload = Get-Content -Path '$(DISCOVER_RANGE_OUTPUT)' -Raw | ConvertFrom-Json; if ($$null -ne $$payload.full_range_start) { [Console]::Out.Write([string]$$payload.full_range_start) } }")

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
$(error Unsupported PROFILE='$(PROFILE)'. Use: smoke, day, week, month, max, custom)
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

START ?= $(PROFILE_START)
END ?= $(PROFILE_END)
SYMBOLS ?= $(PROFILE_SYMBOLS)
TIMEFRAMES ?= $(PROFILE_TIMEFRAMES)
BACKFILL_SYMBOLS ?= $(SYMBOLS)
BACKFILL_TIMEFRAMES ?= $(TIMEFRAMES)
REPLAY_SYMBOLS ?= $(SYMBOLS)
REPLAY_TIMEFRAMES ?= $(TIMEFRAMES)

# e2e warmup + reporting window controls:
# - Analysis window is what report summarizes.
# - Backfill/replay windows can include additional warmup bars.
ANALYSIS_START ?= $(START)
ANALYSIS_END ?= $(END)
WARMUP_DAYS ?= 120
WARMUP_START ?= $(shell powershell -NoProfile -Command '$$start=[DateTimeOffset]::Parse("$(ANALYSIS_START)"); $$days=[double]"$(WARMUP_DAYS)"; [Console]::Out.Write($$start.AddDays(-1.0 * $$days).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))')
BACKFILL_START ?= $(WARMUP_START)
BACKFILL_END ?= $(ANALYSIS_END)
REPLAY_START ?= $(WARMUP_START)
REPLAY_END ?= $(ANALYSIS_END)
DEFAULT_REPORT_RANGE := $(ANALYSIS_START),$(ANALYSIS_END)
REPORT_RANGE ?=
REPORT_RANGE_FOR_E2E := $(if $(strip $(REPORT_RANGE)),$(REPORT_RANGE),$(DEFAULT_REPORT_RANGE))

SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)
BACKFILL_SYMBOLS_ARG := $(if $(strip $(BACKFILL_SYMBOLS)),--symbols $(BACKFILL_SYMBOLS),)
BACKFILL_TIMEFRAMES_ARG := $(if $(strip $(BACKFILL_TIMEFRAMES)),--timeframes $(BACKFILL_TIMEFRAMES),)
REPLAY_SYMBOLS_ARG := $(if $(strip $(REPLAY_SYMBOLS)),--symbols $(REPLAY_SYMBOLS),)
REPLAY_TIMEFRAMES_ARG := $(if $(strip $(REPLAY_TIMEFRAMES)),--timeframes $(REPLAY_TIMEFRAMES),)
REPORT_RANGE_ARG := $(if $(strip $(REPORT_RANGE)),--range $(REPORT_RANGE),)
E2E_REPORT_RANGE_ARG := $(if $(strip $(REPORT_RANGE_FOR_E2E)),--range $(REPORT_RANGE_FOR_E2E),)
RUN_MANIFEST_SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
RUN_MANIFEST_TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)

.PHONY: help venv install validate-config discover-range verify-readiness test dead-code-check backfill replay run-live report migrate-storage-layout preflight-storage e2e clean clean-all

help:
	powershell -NoProfile -Command "Write-Output 'Targets:'; Write-Output '  make validate-config'; Write-Output '  make discover-range'; Write-Output '  make verify-readiness'; Write-Output '  make test'; Write-Output '  make dead-code-check'; Write-Output '  make backfill'; Write-Output '  make replay'; Write-Output '  make run-live'; Write-Output '  make report'; Write-Output '  make migrate-storage-layout'; Write-Output '  make e2e'; Write-Output '  make clean'; Write-Output '  make clean-all'; Write-Output ''; Write-Output 'Common variables:'; Write-Output '  CONFIG=...'; Write-Output '  PROFILE=smoke|day|week|month|max|custom'; Write-Output '  UNIVERSE=core|core_expanded|all_stocks|all'; Write-Output '  START=... END=... (required when PROFILE=custom)'; Write-Output '  SYMBOLS=CSV'; Write-Output '  TIMEFRAMES=CSV'; Write-Output '  BACKFILL_SYMBOLS=CSV (defaults to SYMBOLS)'; Write-Output '  BACKFILL_TIMEFRAMES=CSV (defaults to TIMEFRAMES)'; Write-Output '  REPLAY_SYMBOLS=CSV (defaults to SYMBOLS)'; Write-Output '  REPLAY_TIMEFRAMES=CSV (defaults to TIMEFRAMES)'; Write-Output '  STAGES=validate-config,backfill,replay,report'; Write-Output '  FEATURES=cross_symbol_context (rejected; not a runtime flag, use config route.cross_symbol_context)'; Write-Output '  DISCOVER_RANGE_OUTPUT=...'; Write-Output '  FULL_RANGE_START=... READINESS_END=...'; Write-Output '  ANALYSIS_START=... ANALYSIS_END=... WARMUP_DAYS=...'; Write-Output '  REPORT_RANGE=start,end'; Write-Output ''; Write-Output 'Examples:'; Write-Output '  make discover-range CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml UNIVERSE=all_stocks TIMEFRAME_SET=all'; Write-Output '  make migrate-storage-layout CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml'; Write-Output '  make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all STAGES=validate-config,backfill'; Write-Output '  make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all REPLAY_SYMBOLS= REPLAY_TIMEFRAMES= STAGES=validate-config,backfill,replay,report'; Write-Output '  make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all TIMEFRAME_SET=all STAGES=replay,report'; Write-Output '  make verify-readiness CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all'"

venv:
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; if (!(Test-Path '$(PYTHON)')) { py -3.14 -m venv $(VENV) }; if (!(Test-Path '$(VENV)\\Scripts\\pip.exe')) { & '$(PYTHON)' -m ensurepip --upgrade --default-pip }"
	$(PYTHON) -c "import sys; assert sys.version_info[:3] == (3, 14, 3), f'Python 3.14.3 required, got {sys.version.split()[0]}'"

$(INSTALL_STAMP): $(INSTALL_DEPS) | venv
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pip install -e .[dev]"
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '$(VENV)' | Out-Null; Set-Content -Path '$(INSTALL_STAMP)' -Value (Get-Date -Format o)"

install: $(INSTALL_STAMP)

validate-config: install
	$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG)

discover-range: install
	$(PYTHON) -m sma_outfits.cli discover-range --config $(CONFIG) $(SYMBOLS_ARG) $(TIMEFRAMES_ARG) --output $(DISCOVER_RANGE_OUTPUT) --start $(DISCOVER_START) --end $(READINESS_END)

verify-readiness: install
	$(PYTHON) -m sma_outfits.cli verify-readiness --config $(CONFIG) --start $(START) --end $(END) $(SYMBOLS_ARG) $(TIMEFRAMES_ARG) --output $(READINESS_ACCEPTANCE_OUTPUT)

test: install
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp\\pytest' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pytest"

dead-code-check: install
	$(PYTHON) -m vulture src --min-confidence 90 --ignore-names cls,settings_cls,init_settings,env_settings,file_secret_settings

backfill: install
	$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(START) --end $(END) $(BACKFILL_TIMEFRAMES_ARG)

replay: install
	$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(START) --end $(END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG)

run-live: install
	$(PYTHON) -m sma_outfits.cli run-live --config $(CONFIG)

report: install
	$(PYTHON) -m sma_outfits.cli report --config $(CONFIG) $(REPORT_RANGE_ARG)

migrate-storage-layout: install
	$(PYTHON) -m sma_outfits.cli migrate-storage-layout --config $(CONFIG) --no-dry-run

preflight-storage:
	powershell -NoProfile -Command "$$profile='$(PROFILE)'; $$largeProfiles=@('week','month','max','custom'); if (-not ($$largeProfiles -contains $$profile)) { Write-Output ('storage preflight: skipped for PROFILE=' + $$profile); exit 0 }; $$targetPath = [System.IO.Path]::GetFullPath('$(CURDIR)'); $$root = [System.IO.Path]::GetPathRoot($$targetPath); if ([string]::IsNullOrWhiteSpace($$root)) { throw ('Unable to resolve path root for ' + $$targetPath) }; $$driveInfo = [System.IO.DriveInfo]::new($$root); $$freeBytes = [int64]$$driveInfo.AvailableFreeSpace; $$thresholdGb = [double]'$(MIN_FREE_GB)'; $$thresholdBytes = [int64]($$thresholdGb * 1GB); if ($$freeBytes -lt $$thresholdBytes) { throw ('Insufficient free disk space for PROFILE=' + $$profile + ': free=' + $$freeBytes + ' bytes, required>=' + $$thresholdBytes + ' bytes (MIN_FREE_GB=' + $$thresholdGb + ')') }; Write-Output ('storage preflight: ok PROFILE=' + $$profile + ' free_bytes=' + $$freeBytes + ' threshold_bytes=' + $$thresholdBytes + ' root=' + $$root)"

e2e: preflight-storage
	powershell -NoProfile -Command "Write-Output ('e2e config: profile=$(PROFILE) stages=$(STAGES_NORMALIZED) symbols=$(SYMBOLS) timeframes=$(TIMEFRAMES) backfill_symbols=$(BACKFILL_SYMBOLS) backfill_timeframes=$(BACKFILL_TIMEFRAMES) replay_symbols=$(REPLAY_SYMBOLS) replay_timeframes=$(REPLAY_TIMEFRAMES) analysis_start=$(ANALYSIS_START) analysis_end=$(ANALYSIS_END) warmup_days=$(WARMUP_DAYS) warmup_start=$(WARMUP_START) backfill_start=$(BACKFILL_START) backfill_end=$(BACKFILL_END) replay_start=$(REPLAY_START) replay_end=$(REPLAY_END) report_range=$(REPORT_RANGE_FOR_E2E)')"
	$(if $(call has_stage,validate-config),$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG),powershell -NoProfile -Command "Write-Output 'e2e skip: validate-config'")
	$(if $(call has_stage,backfill),$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(BACKFILL_START) --end $(BACKFILL_END) $(BACKFILL_TIMEFRAMES_ARG),powershell -NoProfile -Command "Write-Output 'e2e skip: backfill'")
	$(if $(call has_stage,replay),$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(REPLAY_START) --end $(REPLAY_END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG),powershell -NoProfile -Command "Write-Output 'e2e skip: replay'")
	$(if $(call has_stage,report),$(PYTHON) -m sma_outfits.cli report --config $(CONFIG) $(E2E_REPORT_RANGE_ARG),powershell -NoProfile -Command "Write-Output 'e2e skip: report'")
	$(PYTHON) -m sma_outfits.cli write-run-manifest --config $(CONFIG) --profile $(PROFILE) --stages $(STAGES_NORMALIZED) --analysis-start $(ANALYSIS_START) --analysis-end $(ANALYSIS_END) --warmup-days $(WARMUP_DAYS) --warmup-start $(WARMUP_START) --backfill-start $(BACKFILL_START) --backfill-end $(BACKFILL_END) --replay-start $(REPLAY_START) --replay-end $(REPLAY_END) --report-range $(REPORT_RANGE_FOR_E2E) --command "make e2e" $(RUN_MANIFEST_SYMBOLS_ARG) $(RUN_MANIFEST_TIMEFRAMES_ARG)
	powershell -NoProfile -Command "Write-Output 'e2e complete'"

clean:
	powershell -NoProfile -Command "$$targets = @('artifacts', '.tmp', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'build', 'dist'); foreach ($$t in $$targets) { if (Test-Path -LiteralPath $$t) { cmd /d /c ('rmdir /s /q ""{0}""' -f $$t) | Out-Null; if (Test-Path -LiteralPath $$t) { throw ('Failed to remove ' + $$t) } } }; $$scanRoots = @(Get-ChildItem -Path . -Directory -Force | Where-Object { $$_.Name -notin @('.venv', '.git') } | ForEach-Object { $$_.FullName }); if ($$scanRoots.Count -gt 0) { Get-ChildItem -Path $$scanRoots -Recurse -Directory -Filter '__pycache__' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path $$scanRoots -Recurse -File -Include '*.pyc','*.pyo' -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue }; Get-ChildItem -Path . -Directory -Filter '*.egg-info' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -File -Include '*.pyc','*.pyo' -Force -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue"

clean-all: clean
	powershell -NoProfile -Command "if (Test-Path '$(VENV)') { Remove-Item -Recurse -Force '$(VENV)' }"
