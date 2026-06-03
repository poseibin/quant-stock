"""因子预处理：去极值、标准化、行业/市值中性化"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.data.storage import duckdb_query as dq


# ---------------------------------------------------------------------------
# 去极值
# ---------------------------------------------------------------------------
def winsorize_mad(s: pd.Series, n: float = 5.0) -> pd.Series:
    """MAD 去极值"""
    s = s.copy()
    med = s.median()
    mad = (s - med).abs().median()
    if mad == 0 or np.isnan(mad):
        return s
    upper = med + n * 1.4826 * mad
    lower = med - n * 1.4826 * mad
    return s.clip(lower, upper)


def winsorize_quantile(s: pd.Series, lo: float = 0.01, hi: float = 0.99) -> pd.Series:
    """分位数截断去极值"""
    if s.empty:
        return s
    ql, qh = s.quantile([lo, hi])
    return s.clip(ql, qh)


# ---------------------------------------------------------------------------
# 标准化
# ---------------------------------------------------------------------------
def zscore(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return s - s.mean()
    return (s - s.mean()) / std


def rank_pct(s: pd.Series) -> pd.Series:
    """转换为分位数排名（0-1）"""
    return s.rank(pct=True, method="average")


# ---------------------------------------------------------------------------
# 行业/市值中性化
# ---------------------------------------------------------------------------
def neutralize(
    factor: pd.Series,
    industry: pd.Series | None = None,
    log_mv: pd.Series | None = None,
) -> pd.Series:
    """对因子做行业 + 市值中性化（OLS 回归取残差）。

    factor: index=ts_code 的横截面因子
    industry: index=ts_code，值为行业名（用 one-hot 处理）
    log_mv: index=ts_code 的对数市值
    """
    df = pd.DataFrame({"y": factor})
    if log_mv is not None:
        df["log_mv"] = log_mv
    if industry is not None:
        ind = pd.get_dummies(industry, prefix="ind", drop_first=True)
        df = df.join(ind)
    df = df.dropna()
    if df.empty or df.shape[1] < 2:
        return factor

    X = df.drop(columns=["y"]).astype(float).values
    y = df["y"].astype(float).values
    X = np.column_stack([np.ones(len(y)), X])
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
    except np.linalg.LinAlgError:
        return factor
    out = pd.Series(resid, index=df.index, name=factor.name)
    return out.reindex(factor.index)


def get_industry_map() -> pd.Series:
    """从 stock_basic 取行业映射，index=ts_code, value=industry。

    简化使用 Tushare stock_basic.industry（行业分类粒度较粗）。
    后续可换 sw_index_member 等更精细的申万分类。
    """
    df = dq.get_stock_basic()
    return df.set_index("ts_code")["industry"]


# ---------------------------------------------------------------------------
# 横截面预处理一键流水线
# ---------------------------------------------------------------------------
def preprocess(
    factor: pd.Series,
    *,
    do_winsorize: bool = True,
    do_zscore: bool = True,
    industry_map: pd.Series | None = None,
    log_mv: pd.Series | None = None,
) -> pd.Series:
    s = factor.dropna()
    if s.empty:
        return s
    if do_winsorize:
        s = winsorize_mad(s)
    if industry_map is not None or log_mv is not None:
        s = neutralize(s, industry_map.reindex(s.index) if industry_map is not None else None,
                       log_mv.reindex(s.index) if log_mv is not None else None)
    if do_zscore:
        s = zscore(s)
    return s
