PY ?= .venv/bin/python

.PHONY: smoke signal-help backtest-help evaluate-help clean

smoke:
	PYTHONDONTWRITEBYTECODE=1 $(PY) tests/test_smoke.py

signal-help:
	PYTHONDONTWRITEBYTECODE=1 $(PY) scripts/daily_signal.py --help

backtest-help:
	PYTHONDONTWRITEBYTECODE=1 $(PY) scripts/run_backtest.py --help

evaluate-help:
	PYTHONDONTWRITEBYTECODE=1 $(PY) scripts/evaluate_strategies.py --help

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache *.egg-info
