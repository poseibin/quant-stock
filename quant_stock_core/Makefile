PY ?= .venv/bin/python

.PHONY: smoke test test-mysql e2e-mysql backtest-help evaluate-help clean

smoke:
	PYTHONDONTWRITEBYTECODE=1 $(PY) tests/test_smoke.py

test:
	PYTHONDONTWRITEBYTECODE=1 $(PY) -m pytest -q

test-mysql:
	PYTHONDONTWRITEBYTECODE=1 $(PY) -m pytest -q tests/test_mysql_infra.py tests/test_worker_mysql_cache.py

e2e-mysql:
	PYTHONDONTWRITEBYTECODE=1 $(PY) scripts/verify_core_e2e.py

backtest-help:
	PYTHONDONTWRITEBYTECODE=1 $(PY) scripts/run_backtest.py --help

evaluate-help:
	PYTHONDONTWRITEBYTECODE=1 $(PY) scripts/evaluate_strategies.py --help

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache *.egg-info
