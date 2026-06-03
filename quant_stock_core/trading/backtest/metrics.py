"""绩效指标计算"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common.config import TRADING_DAYS_PER_YEAR


def annual_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    cumulative = (1 + returns).prod() - 1
    years = len(returns) / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return 0.0
    return float((1 + cumulative) ** (1 / years) - 1)


def annual_volatility(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float(returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    excess = returns - rf / TRADING_DAYS_PER_YEAR
    return float(excess.mean() / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    roll_max = equity.cummax()
    dd = equity / roll_max - 1
    return float(dd.min())


def calmar_ratio(returns: pd.Series, equity: pd.Series) -> float:
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    return float(annual_return(returns) / mdd)


def win_rate(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return float((returns > 0).mean())


def turnover_rate(weights: pd.DataFrame) -> float:
    """平均日换手率：相邻日权重变动绝对值之和的均值 / 2"""
    if weights.empty or len(weights) < 2:
        return 0.0
    diff = weights.diff().abs().sum(axis=1).iloc[1:] / 2
    return float(diff.mean())


def excess_metrics(strat_ret: pd.Series, bench_ret: pd.Series) -> dict:
    """超额收益指标（相对基准）"""
    common = strat_ret.index.intersection(bench_ret.index)
    s = strat_ret.loc[common]
    b = bench_ret.loc[common]
    excess = s - b
    return {
        "excess_annual_return": annual_return(excess),
        "excess_sharpe": sharpe_ratio(excess),
        "excess_max_drawdown": max_drawdown((1 + excess).cumprod()),
        "win_rate_vs_bench": float((s > b).mean()) if len(s) else 0.0,
    }


def summary(returns: pd.Series, weights: pd.DataFrame | None = None,
            benchmark: pd.Series | None = None) -> dict:
    if returns.empty:
        return {}
    equity = (1 + returns).cumprod()
    out = {
        "annual_return": annual_return(returns),
        "annual_volatility": annual_volatility(returns),
        "sharpe": sharpe_ratio(returns),
        "max_drawdown": max_drawdown(equity),
        "calmar": calmar_ratio(returns, equity),
        "win_rate": win_rate(returns),
        "total_return": float(equity.iloc[-1] - 1),
        "n_days": int(len(returns)),
    }
    if weights is not None:
        out["avg_turnover"] = turnover_rate(weights)
    if benchmark is not None:
        out.update(excess_metrics(returns, benchmark))
    return out
