"""动量与波动类因子"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.base import BaseFactor, FactorMeta


def _adj_close_panel(start: str, end: str) -> pd.DataFrame:
    """前复权收盘价宽表 [trade_date x ts_code]。"""
    # 取宽松窗口以保证滚动窗口可计算
    from datetime import datetime, timedelta
    pad_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
    df = dq.sql(f"""
        SELECT d.trade_date, d.ts_code, d.close * a.adj_factor AS adj_close
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
        JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
          ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
        WHERE d.trade_date >= '{pad_start}' AND d.trade_date <= '{end}'
    """)
    if df.empty:
        return pd.DataFrame()
    return df.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()


def _to_long(wide: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if wide.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
    wide = wide.loc[(wide.index >= start) & (wide.index <= end)]
    long = wide.stack().reset_index()
    long.columns = ["trade_date", "ts_code", "value"]
    return long


class Return20D(BaseFactor):
    meta = FactorMeta("ret_20d", "momentum", direction=1,
                      description="20 个交易日累计收益率")

    def _compute_panel(self, start: str, end: str):
        wide = _adj_close_panel(start, end)
        if wide.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        ret = wide.pct_change(20)
        return _to_long(ret, start, end)


class Return60D(BaseFactor):
    meta = FactorMeta("ret_60d", "momentum", direction=1)

    def _compute_panel(self, start: str, end: str):
        wide = _adj_close_panel(start, end)
        if wide.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        ret = wide.pct_change(60)
        return _to_long(ret, start, end)


class Return120D(BaseFactor):
    meta = FactorMeta("ret_120d", "momentum", direction=1)

    def _compute_panel(self, start: str, end: str):
        wide = _adj_close_panel(start, end)
        if wide.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        ret = wide.pct_change(120)
        return _to_long(ret, start, end)


class Volatility20D(BaseFactor):
    """20 日年化波动率，越小越好"""
    meta = FactorMeta("vol_20d", "risk", direction=-1)

    def _compute_panel(self, start: str, end: str):
        wide = _adj_close_panel(start, end)
        if wide.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        ret = wide.pct_change()
        vol = ret.rolling(20).std() * np.sqrt(244)
        return _to_long(vol, start, end)


class MaxDrawdown60D(BaseFactor):
    """近 60 日最大回撤（负值，越小越好）"""
    meta = FactorMeta("mdd_60d", "risk", direction=1)

    def _compute_panel(self, start: str, end: str):
        wide = _adj_close_panel(start, end)
        if wide.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        roll_max = wide.rolling(60, min_periods=20).max()
        dd = wide / roll_max - 1.0
        mdd = dd.rolling(60, min_periods=20).min()
        return _to_long(mdd, start, end)
