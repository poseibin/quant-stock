"""单因子有效性检验：IC、IR、分层回测"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.base import BaseFactor, to_panel_wide
from research.factors.momentum import _adj_close_panel


# ---------------------------------------------------------------------------
# 计算 forward return 面板
# ---------------------------------------------------------------------------
def forward_return(start: str, end: str, period: int = 20) -> pd.DataFrame:
    """计算 [trade_date x ts_code] 的未来 N 日收益。

    行情会额外向后取 ``period`` 个交易日，避免评估区间末尾
    因为价格窗口不足而少算可用样本。
    """
    extended_end = _extend_end_by_trade_days(end, period)
    wide = _adj_close_panel(start, extended_end)
    if wide.empty:
        return wide
    fwd = wide.shift(-period) / wide - 1.0
    return fwd.loc[(fwd.index >= start) & (fwd.index <= end)]


def _extend_end_by_trade_days(end: str, period: int) -> str:
    """把 end 延后 period 个交易日；若日历不足则返回可用最后交易日。"""
    try:
        cal = dq.get_trade_dates()
    except Exception:
        return end
    if not cal:
        return end
    future = [d for d in cal if d >= end]
    if not future:
        return end
    idx = cal.index(future[0])
    return cal[min(idx + period, len(cal) - 1)]


# ---------------------------------------------------------------------------
# IC / IR
# ---------------------------------------------------------------------------
def compute_ic(
    factor_panel: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    method: str = "spearman",
) -> pd.Series:
    """逐日计算横截面相关系数（IC）。

    factor_panel: long [trade_date, ts_code, value]
    fwd_ret: wide [trade_date x ts_code]
    """
    if factor_panel.empty or fwd_ret.empty:
        return pd.Series(dtype=float)

    fac_wide = to_panel_wide(factor_panel)
    common_dates = fac_wide.index.intersection(fwd_ret.index)
    fac_wide = fac_wide.loc[common_dates]
    ret = fwd_ret.loc[common_dates]

    ics = []
    for d in common_dates:
        f = fac_wide.loc[d]
        r = ret.loc[d]
        df = pd.concat([f, r], axis=1, join="inner").dropna()
        if len(df) < 30:
            ics.append((d, np.nan))
            continue
        ic = df.iloc[:, 0].corr(df.iloc[:, 1], method=method)
        ics.append((d, ic))
    out = pd.Series({d: v for d, v in ics}, name="ic")
    out.index.name = "trade_date"
    return out


def ic_summary(ic: pd.Series) -> dict:
    ic = ic.dropna()
    if ic.empty:
        return {}
    mean = ic.mean()
    std = ic.std()
    ir = mean / std if std else 0.0
    win = (ic > 0).mean()
    t = mean / (std / np.sqrt(len(ic))) if std else 0.0
    return {
        "ic_mean": float(mean),
        "ic_std": float(std),
        "ic_ir": float(ir),
        "ic_win_rate": float(win),
        "ic_t_stat": float(t),
        "n_periods": int(len(ic)),
    }


# ---------------------------------------------------------------------------
# 分层回测
# ---------------------------------------------------------------------------
def quantile_returns(
    factor_panel: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    n_quantile: int = 5,
) -> pd.DataFrame:
    """按因子值分 N 层，每层平均的 forward return。

    返回：DataFrame[trade_date x quantile]，quantile 从 1（最低）到 n_quantile（最高）
    """
    fac_wide = to_panel_wide(factor_panel)
    common = fac_wide.index.intersection(fwd_ret.index)
    fac_wide, ret = fac_wide.loc[common], fwd_ret.loc[common]

    rows = []
    for d in common:
        f = fac_wide.loc[d].dropna()
        r = ret.loc[d].dropna()
        df = pd.concat([f, r], axis=1, join="inner").dropna()
        df.columns = ["f", "r"]
        if len(df) < n_quantile * 5:
            continue
        df["q"] = pd.qcut(df["f"].rank(method="first"), n_quantile, labels=False) + 1
        avg = df.groupby("q")["r"].mean()
        avg.name = d
        rows.append(avg)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, axis=1).T
    out.index.name = "trade_date"
    return out


def long_short_return(qret: pd.DataFrame) -> pd.Series:
    """Top - Bottom 多空收益。"""
    if qret.empty:
        return pd.Series(dtype=float)
    top = qret.iloc[:, -1]
    bot = qret.iloc[:, 0]
    return (top - bot).rename("long_short")


# ---------------------------------------------------------------------------
# 一键检验
# ---------------------------------------------------------------------------
def evaluate(
    factor: BaseFactor,
    start: str,
    end: str,
    *,
    period: int = 20,
    n_quantile: int = 5,
) -> dict:
    """完整评估单个因子，返回 IC、分层、多空收益。"""
    panel = factor.compute_panel(start, end)
    fwd = forward_return(start, end, period=period)
    ic = compute_ic(panel, fwd)
    qret = quantile_returns(panel, fwd, n_quantile=n_quantile)
    ls = long_short_return(qret)
    return {
        "factor_name": factor.meta.name,
        "ic_summary": ic_summary(ic),
        "ic_series": ic,
        "quantile_returns": qret,
        "long_short_returns": ls,
        "long_short_mean": float(ls.mean()) if not ls.empty else 0.0,
        "long_short_sharpe": float(ls.mean() / ls.std() * np.sqrt(244 / period))
                             if not ls.empty and ls.std() else 0.0,
    }
