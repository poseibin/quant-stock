# Quant Stock Core

Python core for strategy selection, signal generation, portfolio execution helpers, and time-machine evaluation.

Runtime state does not live in this directory. The desktop app and Python workers share:

- MySQL database `quant_stock`
- `../data_store/raw/`
- `../data_store/backtest_results/`
- `../data_store/factor_cache/`
- `../data_store/logs/`

Strategy configuration is stored in MySQL `cfg_app_settings`, not in YAML files.

## Desktop Scheduler

The desktop app owns scheduled strategy refreshes from the Settings page. A run
updates market data first, then refreshes enabled recommendation modules and
generates the one-click rebalance plan. The scheduler records recent run
results in `cfg_app_settings.strategy_schedule_reports`, including per-module
status, WeCom notification status, and the markdown content that was pushed.

The full data refresh intentionally excludes the slow top-holder dataset so API
limits do not block Profit Arena recommendations. Desktop production data
updates no longer expose that dataset as an operator action.

## Strategy Plugins

Strategies are auto-discovered from `trading/strategy/*.py` through the registry.
Production defaults stay conservative: newly researched ideas are added as
disabled candidate plugins first, then promoted only after multi-window
time-machine evaluation.

Current candidate families:

- `retail_edge` universe: avoid institution-dominated mega caps while keeping
  enough liquidity for small-account execution.
- `forecast_revision`: performance forecast / earnings revision events.
- `dividend_low_vol`: dividend, low-volatility, and quality defense.
- `trend_quality`: medium-term trend with pullback and quality filters.
- `garp_quality`: quality growth at a reasonable price.
- `moneyflow_pullback`: money-flow follow-through with pullback entry.
- `market_regime`: portfolio-level exposure control in `portfolio_risk`.

## Layout

- `common/`: configuration, shared MySQL access, locks, status, and logging.
- `research/`: DuckDB data access, universe construction, and factor utilities.
- `trading/`: strategies, backtest engine, signal generation, position helpers, and time-machine evaluation.
- `scripts/`: CLI entry points used by desktop workers.
- `tests/`: smoke tests.

## Local Checks

```bash
make smoke
make test
make test-mysql
make e2e-mysql
```

- `make test` runs the Python unit/integration suite, including board eligibility filters and MySQL worker cache writes.
- `make test-mysql` runs only the MySQL-backed checks that previously caught schema drift such as `rank`/`rank_no`.
- `make e2e-mysql` verifies the live MySQL pipeline health: base market data, core cache write/read, factor model artifacts, admission records, and whether a usable `ml_factor_ranker` model is active. It is expected to fail when model data has been cleared, training has not produced new artifacts, or the latest model is rejected by admission checks.

Useful CLI entry points:

```bash
make signal-help
make backtest-help
make evaluate-help
```
