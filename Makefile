VENV := .venv
PYTHON := $(VENV)\Scripts\python.exe
PIP := $(PYTHON) -m pip
CONFIG ?= configs/settings.example.yaml
START ?= 2025-01-02T09:30:00Z
END ?= 2025-01-02T16:00:00Z
SYMBOLS ?= SPY,QQQ
TIMEFRAMES ?= 1m,5m,15m,1h,1D

.PHONY: venv install check-python validate-config test backfill replay run-live report clean clean-all

venv:
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; if (!(Test-Path '$(PYTHON)')) { py -3.14 -m venv $(VENV) }; if (!(Test-Path '$(VENV)\\Scripts\\pip.exe')) { & '$(PYTHON)' -m ensurepip --upgrade --default-pip }"
	$(PYTHON) -c "import sys; assert sys.version_info[:3] == (3, 14, 3), f'Python 3.14.3 required, got {sys.version.split()[0]}'"

check-python: venv

install: check-python
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null; $$env:TEMP='$(CURDIR)\\.tmp'; $$env:TMP='$(CURDIR)\\.tmp'; & '$(PYTHON)' -m pip install --upgrade pip; & '$(PYTHON)' -m pip install -e .[dev]"

validate-config: install
	$(PYTHON) -m sma_outfits.cli validate-config --config $(CONFIG)

test: install
	$(PYTHON) -m pytest

backfill: install
	$(PYTHON) -m sma_outfits.cli backfill --config $(CONFIG) --symbols $(SYMBOLS) --start $(START) --end $(END) --timeframes $(TIMEFRAMES)

replay: install
	$(PYTHON) -m sma_outfits.cli replay --config $(CONFIG) --start $(START) --end $(END)

run-live: install
	$(PYTHON) -m sma_outfits.cli run-live --config $(CONFIG)

report: install
	$(PYTHON) -m sma_outfits.cli report --config $(CONFIG)

clean:
	powershell -NoProfile -Command "$$targets = @('artifacts', '.tmp', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'build', 'dist'); foreach ($$t in $$targets) { if (Test-Path $$t) { Remove-Item -Recurse -Force $$t } }; Get-ChildItem -Path . -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -Recurse -File -Include '*.pyc','*.pyo','*.pyd' | Remove-Item -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path . -Directory -Filter '*.egg-info' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"

clean-all: clean
	powershell -NoProfile -Command "if (Test-Path '$(VENV)') { Remove-Item -Recurse -Force '$(VENV)' }"
