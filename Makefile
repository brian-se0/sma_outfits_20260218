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
#   make e2e START=2025-01-02T14:30:00Z END=2025-01-31T21:00:00Z
PROFILE ?= smoke
UNIVERSE ?= core
TIMEFRAME_SET ?= core

# Storage safety guard for larger e2e profiles.
MIN_FREE_GB ?= 50

MAX_START ?= 2025-01-01T00:00:00Z
MAX_END ?= $(shell powershell -NoProfile -Command "[Console]::Out.Write((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))")

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
else
$(error Unsupported PROFILE='$(PROFILE)'. Use: smoke, day, week, month, max)
endif

ifeq ($(UNIVERSE),core)
PROFILE_SYMBOLS := QQQ,RWM
else ifeq ($(UNIVERSE),all)
PROFILE_SYMBOLS :=
else
$(error Unsupported UNIVERSE='$(UNIVERSE)'. Use: core, all)
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

BACKFILL_SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
BACKFILL_TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)
REPLAY_SYMBOLS_ARG := $(if $(strip $(SYMBOLS)),--symbols $(SYMBOLS),)
REPLAY_TIMEFRAMES_ARG := $(if $(strip $(TIMEFRAMES)),--timeframes $(TIMEFRAMES),)

.PHONY: venv install check-python validate-config test backfill replay run-live report preflight-storage e2e e2e-smoke e2e-week e2e-max clean clean-all

venv:
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; if (!(Test-Path '$(PYTHON)')) { py -3.14 -m venv $(VENV) }; if (!(Test-Path '$(VENV)\\Scripts\\pip.exe')) { & '$(PYTHON)' -m ensurepip --upgrade --default-pip }"
	$(PYTHON) -c "import sys; assert sys.version_info[:3] == (3, 14, 3), f'Python 3.14.3 required, got {sys.version.split()[0]}'"

check-python: venv

$(INSTALL_STAMP): pyproject.toml Makefile | check-python
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pip install --upgrade pip; & '$(PYTHON)' -m pip install -e .[dev]"
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '$(VENV)' | Out-Null; Set-Content -Path '$(INSTALL_STAMP)' -Value (Get-Date -Format o)"

install: $(INSTALL_STAMP)

validate-config: install
	$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG)

test: install
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp\\pytest' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pytest"

backfill: install
	$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(START) --end $(END) $(BACKFILL_TIMEFRAMES_ARG)

replay: install
	$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(START) --end $(END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG)

run-live: install
	$(PYTHON) -m sma_outfits.cli run-live --config $(CONFIG)

report: install
	$(PYTHON) -m sma_outfits.cli report --config $(CONFIG)

preflight-storage:
	powershell -NoProfile -Command "$$profile='$(PROFILE)'; $$largeProfiles=@('week','month','max'); if (-not ($$largeProfiles -contains $$profile)) { Write-Output ('storage preflight: skipped for PROFILE=' + $$profile); exit 0 }; $$targetPath = [System.IO.Path]::GetFullPath('$(CURDIR)'); $$root = [System.IO.Path]::GetPathRoot($$targetPath); if ([string]::IsNullOrWhiteSpace($$root)) { throw ('Unable to resolve path root for ' + $$targetPath) }; $$driveInfo = [System.IO.DriveInfo]::new($$root); $$freeBytes = [int64]$$driveInfo.AvailableFreeSpace; $$thresholdGb = [double]'$(MIN_FREE_GB)'; $$thresholdBytes = [int64]($$thresholdGb * 1GB); if ($$freeBytes -lt $$thresholdBytes) { throw ('Insufficient free disk space for PROFILE=' + $$profile + ': free=' + $$freeBytes + ' bytes, required>=' + $$thresholdBytes + ' bytes (MIN_FREE_GB=' + $$thresholdGb + ')') }; Write-Output ('storage preflight: ok PROFILE=' + $$profile + ' free_bytes=' + $$freeBytes + ' threshold_bytes=' + $$thresholdBytes + ' root=' + $$root)"

e2e: preflight-storage
	$(MAKE) install
	powershell -NoProfile -Command "Write-Progress -Activity 'make e2e' -Status 'validate-config (1/5)' -PercentComplete 5"
	$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG)
	powershell -NoProfile -Command "Write-Progress -Activity 'make e2e' -Status 'test (2/5)' -PercentComplete 25"
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp\\pytest' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pytest"
	powershell -NoProfile -Command "Write-Progress -Activity 'make e2e' -Status 'backfill (3/5)' -PercentComplete 50"
	$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) $(BACKFILL_SYMBOLS_ARG) --start $(START) --end $(END) $(BACKFILL_TIMEFRAMES_ARG)
	powershell -NoProfile -Command "Write-Progress -Activity 'make e2e' -Status 'replay (4/5)' -PercentComplete 75"
	$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(START) --end $(END) $(REPLAY_SYMBOLS_ARG) $(REPLAY_TIMEFRAMES_ARG)
	powershell -NoProfile -Command "Write-Progress -Activity 'make e2e' -Status 'report (5/5)' -PercentComplete 90"
	$(PYTHON) -m sma_outfits.cli report --config $(CONFIG)
	powershell -NoProfile -Command "Write-Progress -Activity 'make e2e' -Completed"

e2e-smoke:
	$(MAKE) e2e PROFILE=smoke

e2e-week:
	$(MAKE) e2e PROFILE=week

e2e-max:
	$(MAKE) e2e PROFILE=max

clean:
	powershell -NoProfile -Command "$$targets = @('artifacts', '.tmp', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'build', 'dist'); foreach ($$t in $$targets) { if (Test-Path $$t) { Remove-Item -Recurse -Force $$t } }; Get-ChildItem -Path . -Recurse -Directory -Filter '__pycache__' | Where-Object { $$_.FullName -notlike '*\.venv\*' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -Recurse -File -Include '*.pyc','*.pyo' | Where-Object { $$_.FullName -notlike '*\.venv\*' } | Remove-Item -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -Directory -Filter '*.egg-info' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"

clean-all: clean
	powershell -NoProfile -Command "if (Test-Path '$(VENV)') { Remove-Item -Recurse -Force '$(VENV)' }"
