"""质量类因子（ROE、负债率、毛利率、商誉占比）

财务因子的关键：以 ann_date（公告日）对齐到交易日，避免未来函数。
做法：每个交易日 d，使用 ann_date <= d 的最新一期财务数据。
"""
from __future__ import annotations

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.base import BaseFactor, FactorMeta


def _align_to_trade_date(
    fin_df: pd.DataFrame,
    value_col: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """把财务数据按 ann_date 对齐到交易日，前向填充。

    输入：fin_df 含列 ts_code, ann_date, end_date, <value_col>
    输出：[trade_date, ts_code, value] long 表
    """
    if fin_df.empty:
        return pd.DataFrame(columns=["trade_date", "ts_code", "value"])

    fin_df = fin_df.dropna(subset=[value_col]).copy()
    fin_df["ann_date"] = fin_df["ann_date"].astype(str)
    fin_df["end_date"] = fin_df["end_date"].astype(str)
    fin_df = (fin_df.sort_values(["ts_code", "ann_date", "end_date"])
              .drop_duplicates(subset=["ts_code", "ann_date"], keep="last"))

    trade_dates = dq.get_trade_dates(start, end)
    if not trade_dates:
        return pd.DataFrame(columns=["trade_date", "ts_code", "value"])

    codes = fin_df["ts_code"].dropna().unique()
    cal = pd.MultiIndex.from_product(
        [codes, trade_dates], names=["ts_code", "trade_date"]
    ).to_frame(index=False)

    left = cal.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    right = (fin_df[["ts_code", "ann_date", value_col]]
             .rename(columns={"ann_date": "trade_date"})
             .sort_values(["ts_code", "trade_date"])
             .reset_index(drop=True))

    merged = pd.merge_asof(
        left,
        right,
        on="trade_date",
        by="ts_code",
        direction="backward",
    )
    merged = merged.rename(columns={value_col: "value"})
    return merged[["trade_date", "ts_code", "value"]].dropna(subset=["value"])


class ROE_TTM(BaseFactor):
    meta = FactorMeta("roe_ttm", "quality", direction=1,
                      description="ROE（TTM 或最新期）")

    def _compute_panel(self, start: str, end: str):
        # 拉取宽松窗口的财务数据（往前 1 年）
        from datetime import datetime, timedelta
        ann_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=800)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, roe
            FROM read_parquet('{dq.RAW_DIR / "fina_indicator" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{end}'
              AND roe IS NOT NULL
        """)
        return _align_to_trade_date(df, "roe", start, end)


class DebtToAsset(BaseFactor):
    meta = FactorMeta("debt_to_asset", "quality", direction=-1,
                      description="资产负债率，越小越好")

    def _compute_panel(self, start: str, end: str):
        from datetime import datetime, timedelta
        ann_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=800)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, debt_to_assets
            FROM read_parquet('{dq.RAW_DIR / "fina_indicator" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{end}'
              AND debt_to_assets IS NOT NULL
        """)
        return _align_to_trade_date(df, "debt_to_assets", start, end)


class GrossMargin(BaseFactor):
    meta = FactorMeta("grossprofit_margin", "quality", direction=1,
                      description="毛利率")

    def _compute_panel(self, start: str, end: str):
        from datetime import datetime, timedelta
        ann_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=800)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, grossprofit_margin
            FROM read_parquet('{dq.RAW_DIR / "fina_indicator" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{end}'
              AND grossprofit_margin IS NOT NULL
        """)
        return _align_to_trade_date(df, "grossprofit_margin", start, end)


class GoodwillToEquity(BaseFactor):
    """商誉 / 净资产"""
    meta = FactorMeta("goodwill_to_equity", "quality", direction=-1)

    def _compute_panel(self, start: str, end: str):
        from datetime import datetime, timedelta
        ann_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=800)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, goodwill, total_hldr_eqy_exc_min_int AS equity
            FROM read_parquet('{dq.RAW_DIR / "balancesheet" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{end}'
              AND total_hldr_eqy_exc_min_int IS NOT NULL
              AND total_hldr_eqy_exc_min_int > 0
        """)
        if df.empty:
            return pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        df["ratio"] = df["goodwill"].fillna(0) / df["equity"]
        return _align_to_trade_date(df[["ts_code", "ann_date", "end_date", "ratio"]],
                                    "ratio", start, end)


class CFOToNI(BaseFactor):
    """经营现金流 / 净利润，验证利润质量"""
    meta = FactorMeta("cfo_to_ni", "quality", direction=1)

    def _compute_panel(self, start: str, end: str):
        from datetime import datetime, timedelta
        ann_start = (datetime.strptime(start, "%Y%m%d") - timedelta(days=800)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, ocf_to_profit AS value
            FROM read_parquet('{dq.RAW_DIR / "fina_indicator" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{end}'
              AND ocf_to_profit IS NOT NULL
        """)
        return _align_to_trade_date(df, "value", start, end)
