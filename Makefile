VENV := .venv
PYTHON := $(VENV)\Scripts\python.exe
PIP := $(PYTHON) -m pip
INSTALL_STAMP := $(VENV)\.install.stamp

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
REPORT_ATTRIBUTION ?= both
REPORT_RANGE_FOR_E2E := $(if $(strip $(REPORT_RANGE)),$(REPORT_RANGE),$(DEFAULT_REPORT_RANGE))

BACKFILL_SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
BACKFILL_TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)
REPLAY_SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
REPLAY_TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)
REPORT_RANGE_ARG := $(if $(strip $(REPORT_RANGE)),--range $(REPORT_RANGE),)
REPORT_ATTRIBUTION_ARG := $(if $(strip $(REPORT_ATTRIBUTION)),--attribution $(REPORT_ATTRIBUTION),)
E2E_REPORT_RANGE_ARG := $(if $(strip $(REPORT_RANGE_FOR_E2E)),--range $(REPORT_RANGE_FOR_E2E),)
E2E_REPORT_ATTRIBUTION_ARG := $(if $(strip $(REPORT_ATTRIBUTION)),--attribution $(REPORT_ATTRIBUTION),)

.PHONY: help venv install validate-config discover-range verify-readiness test backfill replay run-live report preflight-storage e2e clean clean-all

help:
	powershell -NoProfile -Command "Write-Output 'Targets:'; Write-Output '  make validate-config'; Write-Output '  make discover-range'; Write-Output '  make verify-readiness'; Write-Output '  make test'; Write-Output '  make backfill'; Write-Output '  make replay'; Write-Output '  make run-live'; Write-Output '  make report'; Write-Output '  make e2e'; Write-Output '  make clean'; Write-Output '  make clean-all'; Write-Output ''; Write-Output 'Common variables:'; Write-Output '  CONFIG=...'; Write-Output '  PROFILE=smoke|day|week|month|max|custom'; Write-Output '  UNIVERSE=core|core_expanded|all_stocks|all'; Write-Output '  START=... END=... (required when PROFILE=custom)'; Write-Output '  SYMBOLS=CSV'; Write-Output '  TIMEFRAMES=CSV'; Write-Output '  STAGES=validate-config,backfill,replay,report'; Write-Output '  FEATURES=cross_symbol_context (rejected; not a runtime flag, use config route.cross_symbol_context)'; Write-Output '  DISCOVER_RANGE_OUTPUT=...'; Write-Output '  FULL_RANGE_START=... READINESS_END=...'; Write-Output '  ANALYSIS_START=... ANALYSIS_END=... WARMUP_DAYS=...'; Write-Output '  REPORT_RANGE=start,end REPORT_ATTRIBUTION=strike|close|both'; Write-Output ''; Write-Output 'Examples:'; Write-Output '  make discover-range CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml UNIVERSE=all_stocks TIMEFRAME_SET=all'; Write-Output '  make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all STAGES=validate-config,backfill'; Write-Output '  make e2e CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml PROFILE=custom START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all TIMEFRAME_SET=all STAGES=replay,report'; Write-Output '  make verify-readiness CONFIG=configs/settings.jan2025_confluence_atr_svix211_106_crossctx_v1.yaml START=$$env:FULL_RANGE_START END=$(READINESS_END) UNIVERSE=all_stocks TIMEFRAME_SET=all'"

venv:
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; if (!(Test-Path '$(PYTHON)')) { py -3.14 -m venv $(VENV) }; if (!(Test-Path '$(VENV)\\Scripts\\pip.exe')) { & '$(PYTHON)' -m ensurepip --upgrade --default-pip }"
	$(PYTHON) -c "import sys; assert sys.version_info[:3] == (3, 14, 3), f'Python 3.14.3 required, got {sys.version.split()[0]}'"

$(INSTALL_STAMP): pyproject.toml Makefile | venv
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pip install --upgrade pip; & '$(PYTHON)' -m pip install -e .[dev]"
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '$(VENV)' | Out-Null; Set-Content -Path '$(INSTALL_STAMP)' -Value (Get-Date -Format o)"

install: $(INSTALL_STAMP)

validate-config: install
	$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG)

discover-range: install
	$(PYTHON) -m sma_outfits.cli discover-range --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) $(BACKFILL_TIMEFRAMES_ARG) --output $(DISCOVER_RANGE_OUTPUT) --start $(DISCOVER_START) --end $(READINESS_END)

verify-readiness: install
	$(PYTHON) -m sma_outfits.cli verify-readiness --config $(CONFIG) --start $(START) --end $(END) $(BACKFILL_SYMBOLS_ARG) $(BACKFILL_TIMEFRAMES_ARG) --output $(READINESS_ACCEPTANCE_OUTPUT)

test: install
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp\\pytest' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pytest"

backfill: install
	$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(START) --end $(END) $(BACKFILL_TIMEFRAMES_ARG)

replay: install
	$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(START) --end $(END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG)

run-live: install
	$(PYTHON) -m sma_outfits.cli run-live --config $(CONFIG)

report: install
	$(PYTHON) -m sma_outfits.cli report --config $(CONFIG) $(REPORT_RANGE_ARG) $(REPORT_ATTRIBUTION_ARG)

preflight-storage:
	powershell -NoProfile -Command "$$profile='$(PROFILE)'; $$largeProfiles=@('week','month','max','custom'); if (-not ($$largeProfiles -contains $$profile)) { Write-Output ('storage preflight: skipped for PROFILE=' + $$profile); exit 0 }; $$targetPath = [System.IO.Path]::GetFullPath('$(CURDIR)'); $$root = [System.IO.Path]::GetPathRoot($$targetPath); if ([string]::IsNullOrWhiteSpace($$root)) { throw ('Unable to resolve path root for ' + $$targetPath) }; $$driveInfo = [System.IO.DriveInfo]::new($$root); $$freeBytes = [int64]$$driveInfo.AvailableFreeSpace; $$thresholdGb = [double]'$(MIN_FREE_GB)'; $$thresholdBytes = [int64]($$thresholdGb * 1GB); if ($$freeBytes -lt $$thresholdBytes) { throw ('Insufficient free disk space for PROFILE=' + $$profile + ': free=' + $$freeBytes + ' bytes, required>=' + $$thresholdBytes + ' bytes (MIN_FREE_GB=' + $$thresholdGb + ')') }; Write-Output ('storage preflight: ok PROFILE=' + $$profile + ' free_bytes=' + $$freeBytes + ' threshold_bytes=' + $$thresholdBytes + ' root=' + $$root)"

e2e: preflight-storage
	powershell -NoProfile -Command "Write-Output ('e2e config: profile=$(PROFILE) stages=$(STAGES_NORMALIZED) symbols=$(SYMBOLS) timeframes=$(TIMEFRAMES) analysis_start=$(ANALYSIS_START) analysis_end=$(ANALYSIS_END) warmup_days=$(WARMUP_DAYS) warmup_start=$(WARMUP_START) backfill_start=$(BACKFILL_START) backfill_end=$(BACKFILL_END) replay_start=$(REPLAY_START) replay_end=$(REPLAY_END) report_range=$(REPORT_RANGE_FOR_E2E) report_attribution=$(REPORT_ATTRIBUTION)')"
	$(if $(call has_stage,validate-config),$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG),powershell -NoProfile -Command "Write-Output 'e2e skip: validate-config'")
	$(if $(call has_stage,backfill),$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(BACKFILL_START) --end $(BACKFILL_END) $(BACKFILL_TIMEFRAMES_ARG),powershell -NoProfile -Command "Write-Output 'e2e skip: backfill'")
	$(if $(call has_stage,replay),$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(REPLAY_START) --end $(REPLAY_END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG),powershell -NoProfile -Command "Write-Output 'e2e skip: replay'")
	$(if $(call has_stage,report),$(PYTHON) -m sma_outfits.cli report --config $(CONFIG) $(E2E_REPORT_RANGE_ARG) $(E2E_REPORT_ATTRIBUTION_ARG),powershell -NoProfile -Command "Write-Output 'e2e skip: report'")
	powershell -NoProfile -Command "Write-Output 'e2e complete'"

clean:
	powershell -NoProfile -Command "$$targets = @('artifacts', '.tmp', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'build', 'dist'); foreach ($$t in $$targets) { if (Test-Path $$t) { Remove-Item -Recurse -Force $$t } }; Get-ChildItem -Path . -Recurse -Directory -Filter '__pycache__' | Where-Object { $$_.FullName -notlike '*\.venv\*' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -Recurse -File -Include '*.pyc','*.pyo' | Where-Object { $$_.FullName -notlike '*\.venv\*' } | Remove-Item -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -Directory -Filter '*.egg-info' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"

clean-all: clean
	powershell -NoProfile -Command "if (Test-Path '$(VENV)') { Remove-Item -Recurse -Force '$(VENV)' }"
