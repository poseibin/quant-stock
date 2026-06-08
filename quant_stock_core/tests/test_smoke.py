"""无依赖的基础冒烟测试

仅检查模块可被导入与基础类可实例化，不实际拉数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_imports():
    import common.config  # noqa
    from research.data.storage import duckdb_query  # noqa
    from research.factors import value, quality, momentum, size, liquidity, event, neutralize, evaluate  # noqa
    from research.universe import build, UniverseConfig  # noqa
    from trading.backtest import run, BacktestConfig, CostModel  # noqa
    from trading.strategy import combiner  # noqa
    from trading.execution import signal, notifier, paper_trade  # noqa
    from scripts import evaluate_strategies  # noqa


def test_config_paths():
    from common.config import RAW_DIR, FACTOR_CACHE_DIR, BACKTEST_DIR, LOG_DIR
    for p in (RAW_DIR, FACTOR_CACHE_DIR, BACKTEST_DIR, LOG_DIR):
        assert p.exists(), f"{p} 不存在"


def test_strategy_config_loadable():
    from trading.strategy.base import StrategyConfig
    from trading.strategy import registry
    names = registry.all_names()
    assert names, "未发现任何已注册策略"
    for name in names:
        cfg = StrategyConfig.from_yaml(name)
        assert cfg.name == name


def test_strategy_registry():
    from trading.strategy import registry
    names = registry.all_names()
    # 每个注册策略都应可构造，且有中文标签
    labels = registry.labels()
    for name in names:
        assert name in labels
        s = registry.build(name)
        assert s.cfg.name == name


def test_cost_model():
    from trading.backtest.cost_model import CostModel
    c = CostModel()
    rt = c.round_trip_cost_pct()
    assert 0 < rt < 0.05


def test_rebalance_dates():
    from trading.strategy.base import get_rebalance_dates
    # 不依赖数据，仅验证函数可调用且返回 list
    out = get_rebalance_dates("20240101", "20240105", "monthly")
    assert isinstance(out, list)


def test_weekly_rebalance_uses_iso_year(monkeypatch):
    from trading.strategy.base import get_rebalance_dates
    from research.data.storage import duckdb_query

    monkeypatch.setattr(
        duckdb_query,
        "get_trade_dates",
        lambda start, end: ["20241230", "20241231", "20250102", "20250103"],
    )
    assert get_rebalance_dates("20241230", "20250103", "weekly") == ["20250103"]


def test_breakout_pullback_uses_daily_touch_window():
    import pandas as pd
    from scripts.limit_breakout_model_worker import simulate_breakout_pullback_return

    row = pd.Series({
        "close": 100.0,
        "future_low_3d": 90.0,
        "future_high_3d": 101.0,
        "exit_close_5d": 101.0,
        "next_low_1d": 90.0,
        "next_high_1d": 94.0,
        "next_low_2d": 90.0,
        "next_high_2d": 94.0,
        "next_low_3d": 90.0,
        "next_high_3d": 94.0,
    })
    ret = simulate_breakout_pullback_return(row, 5, -0.05, 3, 0.12, -0.05, 0, 0, 0, 0)
    assert ret is None


def test_breakout_confirmation_starts_after_confirm_close():
    import pandas as pd
    from scripts.limit_breakout_model_worker import simulate_breakout_confirmation_return

    row = pd.Series({
        "close": 100.0,
        "entry_open_1d": 101.0,
        "entry_gap_1d": 0.01,
        "exit_close_1d": 104.0,
        "future_high_5d": 200.0,
        "future_low_5d": 90.0,
        "next_high_2d": 105.0,
        "next_low_2d": 103.0,
        "next_high_3d": 105.0,
        "next_low_3d": 103.0,
        "next_high_4d": 105.0,
        "next_low_4d": 103.0,
        "next_high_5d": 105.0,
        "next_low_5d": 103.0,
        "next_high_6d": 105.0,
        "next_low_6d": 103.0,
        "exit_close_after_confirm_5d": 105.0,
    })
    ret = simulate_breakout_confirmation_return(row, 5, 0.04, 0.08, 0.12, -0.05, 0, 0, 0, 0)
    assert ret == (105.0 / 104.0 - 1)


if __name__ == "__main__":
    test_imports()
    test_config_paths()
    test_strategy_config_loadable()
    test_strategy_registry()
    test_cost_model()
    test_rebalance_dates()
    print("All smoke tests passed")
