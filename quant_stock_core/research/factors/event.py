"""事件类因子（增持事件、龙虎榜、业绩预告）

事件因子的特点：
- 触发式而非周期性
- 通常用作策略信号而非排序因子
- 这里实现为：返回触发日的"标记/强度"，方便策略层使用
"""
from __future__ import annotations

import pandas as pd

from research.data.storage import duckdb_query as dq


def insider_buy_events(
    start: str,
    end: str,
    *,
    min_amount: float = 10_000_000,
) -> pd.DataFrame:
    """大股东 / 高管增持事件清单。

    返回列：[ts_code, ann_date, holder_name, change_vol, avg_price, amount, in_de]
    in_de = 'IN' 表示增持
    """
    df = dq.sql(f"""
        SELECT ts_code, ann_date, holder_name, in_de,
               change_vol, avg_price,
               (change_vol * avg_price) AS amount
        FROM read_parquet('{dq.RAW_DIR / "stk_holdertrade" / "*.parquet"}')
        WHERE ann_date >= '{start}' AND ann_date <= '{end}'
          AND in_de = 'IN'
          AND change_vol IS NOT NULL AND avg_price IS NOT NULL
    """)
    if df.empty:
        return df
    df = df[df["amount"] >= min_amount]
    return df.reset_index(drop=True)


def institution_net_buy(
    start: str,
    end: str,
    *,
    min_net: float = 50_000_000,
) -> pd.DataFrame:
    """龙虎榜机构席位净买入。

    top_inst 已含机构买卖明细，按交易日聚合机构净买入。
    """
    df = dq.sql(f"""
        SELECT ts_code, trade_date,
               SUM(buy) AS inst_buy,
               SUM(sell) AS inst_sell,
               SUM(net_buy) AS inst_net_buy
        FROM read_parquet('{dq.RAW_DIR / "top_inst" / "*.parquet"}')
        WHERE trade_date >= '{start}' AND trade_date <= '{end}'
        GROUP BY ts_code, trade_date
    """)
    if df.empty:
        return df
    df = df[df["inst_net_buy"] >= min_net]
    return df.reset_index(drop=True)


def performance_forecast(
    start: str,
    end: str,
    *,
    only_increase: bool = True,
) -> pd.DataFrame:
    """业绩预告。

    返回列含：ts_code, ann_date, end_date, type, p_change_min, p_change_max
    type 类似：预增/预减/略增/略减/扭亏/首亏/续亏/续盈
    """
    df = dq.sql(f"""
        SELECT ts_code, ann_date, end_date, type,
               p_change_min, p_change_max, summary
        FROM read_parquet('{dq.RAW_DIR / "forecast" / "*.parquet"}')
        WHERE ann_date >= '{start}' AND ann_date <= '{end}'
    """)
    if df.empty:
        return df
    if only_increase:
        df = df[df["type"].isin(["预增", "略增", "续盈", "扭亏"])]
    return df.reset_index(drop=True)
