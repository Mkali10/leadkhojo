.PHONY: help install dev scan test lint format check plugins rules clean

PY := backend/.venv/Scripts/python.exe
ifeq ($(OS),)
PY := backend/.venv/bin/python
endif

help:
	@echo "LeadKhojo - Website Intelligence Platform"
	@echo ""
	@echo "  make install    Create the virtualenv and install dependencies"
	@echo "  make check      Lint, type-check and test (run before every commit)"
	@echo "  make test       Run the test suite"
	@echo "  make lint       Ruff check + format check"
	@echo "  make format     Apply formatting"
	@echo "  make plugins    Show registered plugins and execution order"
	@echo "  make rules      Show loaded rule pack counts"
	@echo ""
	@echo "  make scan URL=acme.com"
	@echo "  make scan CSV=domains.csv"

install:
	cd backend && python -m venv .venv
	$(PY) -m pip install --upgrade pip
	cd backend && ../$(PY) -m pip install -e ".[dev]"
	@echo "Ready. Try: make plugins"

scan:
ifdef URL
	$(PY) -m leadkhojo.cli scan --url "$(URL)" --out results --pdf
else ifdef CSV
	$(PY) -m leadkhojo.cli scan --csv "$(CSV)" --out results --pdf
else
	@echo "Usage: make scan URL=acme.com   or   make scan CSV=domains.csv"
endif

plugins:
	$(PY) -m leadkhojo.cli plugins

rules:
	$(PY) -m leadkhojo.cli rules

test:
	cd backend && ../$(PY) -m pytest tests/ -q

# Architecture guards first: a rule violation should stop the pipeline in
# seconds, not after the full suite.
check:
	cd backend && ../$(PY) -m ruff check src tests
	cd backend && ../$(PY) -m ruff format --check src tests
	cd backend && ../$(PY) -m pytest tests/architecture -q
	cd backend && ../$(PY) -m pytest tests/ -q

lint:
	cd backend && ../$(PY) -m ruff check src tests
	cd backend && ../$(PY) -m ruff format --check src tests

format:
	cd backend && ../$(PY) -m ruff format src tests
	cd backend && ../$(PY) -m ruff check --fix src tests

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
