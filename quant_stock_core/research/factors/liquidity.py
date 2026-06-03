"""流动性类因子"""
from __future__ import annotations

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.base import BaseFactor, FactorMeta


class AvgAmount20D(BaseFactor):
    """近 20 日日均成交额（元）"""
    meta = FactorMeta("avg_amount_20d", "liquidity", direction=1)

    def _compute_panel(self, start: str, end: str):
        from datetime import datetime, timedelta
        pad = (datetime.strptime(start, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT trade_date, ts_code, amount
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
            WHERE trade_date >= '{pad}' AND trade_date <= '{end}'
        """)
        if df.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        wide = df.pivot(index="trade_date", columns="ts_code", values="amount").sort_index()
        avg = wide.rolling(20, min_periods=10).mean()
        avg = avg.loc[(avg.index >= start) & (avg.index <= end)]
        long = avg.stack().reset_index()
        long.columns = ["trade_date", "ts_code", "value"]
        long["value"] = long["value"] * 1000.0  # tushare amount 单位为千元
        return long


class Turnover20D(BaseFactor):
    """近 20 日平均换手率"""
    meta = FactorMeta("turnover_20d", "liquidity", direction=1)

    def _compute_panel(self, start: str, end: str):
        from datetime import datetime, timedelta
        pad = (datetime.strptime(start, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT trade_date, ts_code, turnover_rate
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{pad}' AND trade_date <= '{end}'
              AND turnover_rate IS NOT NULL
        """)
        if df.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        wide = df.pivot(index="trade_date", columns="ts_code", values="turnover_rate").sort_index()
        avg = wide.rolling(20, min_periods=10).mean()
        avg = avg.loc[(avg.index >= start) & (avg.index <= end)]
        long = avg.stack().reset_index()
        long.columns = ["trade_date", "ts_code", "value"]
        return long
