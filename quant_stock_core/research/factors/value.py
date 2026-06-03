"""估值类因子（PE / PB / PS / PCF / EP / BP / SP）

A 股注意：
- 用 daily_basic 中的 pe_ttm / pb / ps_ttm
- 负值视为缺失（亏损公司 PE 无意义）
- 反向用 1/PE 形式（EP）便于与其他因子合成
"""
from __future__ import annotations

import numpy as np

from research.data.storage import duckdb_query as dq
from research.factors.base import BaseFactor, FactorMeta


class PE_TTM(BaseFactor):
    meta = FactorMeta("pe_ttm", "value", direction=-1,
                      description="市盈率（TTM），越小越好；负值剔除")

    def _compute_panel(self, start: str, end: str):
        return dq.sql(f"""
            SELECT trade_date, ts_code, pe_ttm AS value
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND pe_ttm IS NOT NULL AND pe_ttm > 0
        """)


class PB(BaseFactor):
    meta = FactorMeta("pb", "value", direction=-1,
                      description="市净率，越小越好；负值剔除")

    def _compute_panel(self, start: str, end: str):
        return dq.sql(f"""
            SELECT trade_date, ts_code, pb AS value
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND pb IS NOT NULL AND pb > 0
        """)


class PS_TTM(BaseFactor):
    meta = FactorMeta("ps_ttm", "value", direction=-1)

    def _compute_panel(self, start: str, end: str):
        return dq.sql(f"""
            SELECT trade_date, ts_code, ps_ttm AS value
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND ps_ttm IS NOT NULL AND ps_ttm > 0
        """)


class EP(BaseFactor):
    """1/PE，越大越好"""
    meta = FactorMeta("ep", "value", direction=1)

    def _compute_panel(self, start: str, end: str):
        df = dq.sql(f"""
            SELECT trade_date, ts_code, pe_ttm AS pe
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND pe_ttm IS NOT NULL AND pe_ttm > 0
        """)
        df["value"] = 1.0 / df["pe"]
        return df.drop(columns=["pe"])


class BP(BaseFactor):
    """1/PB，越大越好"""
    meta = FactorMeta("bp", "value", direction=1)

    def _compute_panel(self, start: str, end: str):
        df = dq.sql(f"""
            SELECT trade_date, ts_code, pb
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND pb IS NOT NULL AND pb > 0
        """)
        df["value"] = 1.0 / df["pb"]
        return df.drop(columns=["pb"])


class SP(BaseFactor):
    """1/PS，越大越好"""
    meta = FactorMeta("sp", "value", direction=1)

    def _compute_panel(self, start: str, end: str):
        df = dq.sql(f"""
            SELECT trade_date, ts_code, ps_ttm AS ps
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date >= '{start}' AND trade_date <= '{end}'
              AND ps_ttm IS NOT NULL AND ps_ttm > 0
        """)
        df["value"] = 1.0 / df["ps"]
        return df.drop(columns=["ps"])
