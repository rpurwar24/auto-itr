# ITR-2 Utility - common tasks
.DEFAULT_GOAL := help
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT ?= 8000

.PHONY: help setup run dev test clean

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## create the venv and install all dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "\nSetup complete. Run 'make run' to start the app."

run: dev  ## alias for 'dev'

dev:  ## run the web app with auto-reload (http://127.0.0.1:$(PORT))
	$(PY) -m uvicorn app.server:app --reload --host 127.0.0.1 --port $(PORT)

test:  ## run the test suite
	$(PY) -m pytest tests/ -q

clean:  ## remove caches and generated output (keeps .users/ workspaces)
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache output/*.json output/csv
