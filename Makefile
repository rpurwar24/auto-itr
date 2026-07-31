# auto-itr - common tasks (folder-local venv; uv if available, else python venv + pip)
.DEFAULT_GOAL := help
VENV := .venv
PY := $(VENV)/bin/python
PORT ?= 8000
PYVER ?= 3.12
UV := $(shell command -v uv 2>/dev/null)

.PHONY: help setup setup-dev check run dev test clean

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

# auto-bootstrap: create the folder-local venv only if it doesn't exist yet
$(PY):
	@echo "no venv at $(VENV) - setting up..."
	@$(MAKE) --no-print-directory setup

setup:  ## create the folder-local .venv and install runtime deps
ifneq ($(UV),)
	@echo "-> uv detected ($(UV)); provisioning Python $(PYVER)"
	uv venv --python $(PYVER) $(VENV)
	uv pip install --python $(PY) -r requirements.txt
else
	@echo "-> uv not found; using system python3 + pip"
	@python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' || { \
		echo ""; \
		echo "  ERROR: Python 3.10+ required (found $$(python3 -V 2>&1))."; \
		echo "  Easiest fix - install uv, which fetches its own Python:"; \
		echo "      brew install uv        # or: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo "      make setup"; \
		echo "  Or install Python 3.10+ and re-run 'make setup'."; \
		exit 1; }
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
endif
	@echo "\nSetup complete. 'make check' to verify, 'make run' to start."

setup-dev:  ## like setup, plus dev extras (pytest + numbers-parser oracle)
ifneq ($(UV),)
	uv venv --python $(PYVER) $(VENV)
	uv pip install --python $(PY) -r requirements-dev.txt
else
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-dev.txt
endif

check: $(PY)  ## show python + installed dependency versions (auto-sets-up if missing)
	@$(PY) scripts/doctor.py

run: dev  ## alias for 'dev'

dev: $(PY)  ## run the web app with auto-reload (auto-sets-up if missing) at :$(PORT)
	$(PY) -m uvicorn app.server:app --reload --host 127.0.0.1 --port $(PORT)

test: $(PY)  ## run the test suite (local only - tests/ is not published)
	@if [ ! -d tests ]; then echo "no tests/ in this distribution (kept local)"; \
	elif ! $(PY) -c "import pytest" 2>/dev/null; then echo "pytest not installed - run 'make setup-dev'"; \
	else $(PY) -m pytest tests/ -q; fi

clean:  ## remove caches and generated output (keeps .venv and .users/ workspaces)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache output/*.json output/csv
