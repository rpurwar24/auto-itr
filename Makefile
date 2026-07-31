# ITR-2 Utility - common tasks (folder-local venv; uv if available, else python venv + pip)
.DEFAULT_GOAL := help
VENV := .venv
PY := $(VENV)/bin/python
PORT ?= 8000
UV := $(shell command -v uv 2>/dev/null)

.PHONY: help setup check run dev test clean

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

# auto-bootstrap: create the folder-local venv only if it doesn't exist yet
$(PY):
	@echo "no venv at $(VENV) - setting up..."
	@$(MAKE) --no-print-directory setup

setup:  ## create the folder-local .venv and install deps (uv if available, else pip)
ifneq ($(UV),)
	@echo "-> uv detected: $(UV)"
	uv venv $(VENV)
	uv pip install --python $(PY) -r requirements.txt
else
	@echo "-> uv not found: using python3 -m venv + pip"
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
endif
	@echo "\nSetup complete. 'make check' to verify, 'make run' to start."

check: $(PY)  ## show python + installed dependency versions (auto-sets-up if missing)
	@$(PY) scripts/doctor.py

run: dev  ## alias for 'dev'

dev: $(PY)  ## run the web app with auto-reload (auto-sets-up if missing) at :$(PORT)
	$(PY) -m uvicorn app.server:app --reload --host 127.0.0.1 --port $(PORT)

test: $(PY)  ## run the test suite
	$(PY) -m pytest tests/ -q

clean:  ## remove caches and generated output (keeps .venv and .users/ workspaces)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache output/*.json output/csv
