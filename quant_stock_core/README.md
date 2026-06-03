# Quant Stock Core

Python core for strategy selection, signal generation, portfolio execution helpers, and time-machine evaluation.

Runtime state does not live in this directory. The desktop app and Python workers share:

- `../data_store/meta.db`
- `../data_store/raw/`
- `../data_store/backtest_results/`
- `../data_store/factor_cache/`
- `../data_store/logs/`

Strategy configuration is stored in SQLite `app_settings`, not in YAML files.

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

- `common/`: configuration, shared SQLite access, locks, status, and logging.
- `research/`: DuckDB data access, universe construction, and factor utilities.
- `trading/`: strategies, backtest engine, signal generation, position helpers, and time-machine evaluation.
- `scripts/`: CLI entry points used by desktop workers.
- `tests/`: smoke tests.

## Local Checks

```bash
make smoke
```

Useful CLI entry points:

```bash
make signal-help
make backtest-help
make evaluate-help
```
