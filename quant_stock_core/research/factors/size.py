"""市值类因子"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.base import BaseFactor, FactorMeta


class CircMV(BaseFactor):
    """流通市值（万元）"""
    meta = FactorMeta("circ_mv", "size", direction=-1,
                      description="流通市值，越小越好（小市值因子）")

    def _compute_panel(self, start: str, end: str) -> pd.DataFrame:
        df = dq.sql(f"""
            SELECT trade_date, ts_code, circ_mv AS value
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND circ_mv IS NOT NULL AND circ_mv > 0
        """)
        return df


class TotalMV(BaseFactor):
    """总市值（万元）"""
    meta = FactorMeta("total_mv", "size", direction=-1)

    def _compute_panel(self, start: str, end: str) -> pd.DataFrame:
        return dq.sql(f"""
            SELECT trade_date, ts_code, total_mv AS value
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND total_mv IS NOT NULL AND total_mv > 0
        """)


class LogCircMV(BaseFactor):
    """对数流通市值（更接近正态分布）"""
    meta = FactorMeta("log_circ_mv", "size", direction=-1)

    def _compute_panel(self, start: str, end: str) -> pd.DataFrame:
        df = dq.sql(f"""
            SELECT trade_date, ts_code, circ_mv AS value
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND circ_mv IS NOT NULL AND circ_mv > 0
        """)
        df["value"] = np.log(df["value"])
        return df
