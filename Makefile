PY ?= python3
VENV ?= .venv

.PHONY: install test lint run clean

install:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt
	$(VENV)/bin/pip install -e .

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m compileall -q src tests

run:
	$(PY) -m tracker.cli --help

clean:
	rm -rf .pytest_cache src/*.egg-info build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
