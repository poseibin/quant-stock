"""数据校验：检查日期空缺、字段完整性、关键字段合理范围。"""
from __future__ import annotations

import pandas as pd

from research.data.storage import duckdb_query as dq
from common.utils import get_logger

log = get_logger("validator")


def check_date_gaps(dataset: str = "daily") -> list[str]:
    """检查行情数据是否存在交易日空缺。"""
    df = dq.sql(f"""
        SELECT DISTINCT trade_date
        FROM read_parquet('{dq.RAW_DIR / dataset / "*.parquet"}')
    """)
    have = set(df["trade_date"].astype(str))
    expect = set(dq.get_trade_dates(min(have) if have else None,
                                    max(have) if have else None))
    miss = sorted(expect - have)
    if miss:
        log.warning(f"{dataset} 缺失 {len(miss)} 个交易日，前 5 个：{miss[:5]}")
    return miss


def check_pe_pb_sanity() -> dict:
    """daily_basic 中 PE/PB 合理性检查。"""
    df = dq.sql(f"""
        SELECT
            COUNT(*) AS total,
            COUNT_IF(pe IS NULL) AS pe_null,
            COUNT_IF(pb IS NULL) AS pb_null,
            COUNT_IF(pe < 0) AS pe_neg,
            COUNT_IF(pb < 0) AS pb_neg
        FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
    """)
    return df.iloc[0].to_dict()


def summary() -> pd.DataFrame:
    """各 dataset 的简要统计（含日期区间）。"""
    # 每个数据集的"主日期字段"，用于展示数据覆盖区间。
    # None 表示没有合适的日期字段（如 stock_basic）。
    DATE_COL = {
        "stock_basic":     None,
        "trade_cal":       "cal_date",
        "daily":           "trade_date",
        "daily_basic":     "trade_date",
        "adj_factor":      "trade_date",
        "income":          "end_date",
        "balancesheet":    "end_date",
        "cashflow":        "end_date",
        "fina_indicator":  "end_date",
        "forecast":        "ann_date",
        "stk_holdertrade": "ann_date",
        "top_list":        "trade_date",
        "top_inst":        "trade_date",
    }

    rows = []
    for ds, date_col in DATE_COL.items():
        files = list((dq.RAW_DIR / ds).glob("*.parquet"))
        if not files:
            rows.append({"dataset": ds, "files": 0, "rows": 0,
                         "date_col": date_col, "min_date": "", "max_date": ""})
            continue

        glob = dq.RAW_DIR / ds / "*.parquet"
        if date_col:
            stat = dq.sql(f"""
                SELECT COUNT(*) AS n,
                       MIN({date_col}) AS d_min,
                       MAX({date_col}) AS d_max
                FROM read_parquet('{glob}')
            """)
            n = int(stat["n"].iloc[0]) if not stat.empty else 0
            d_min = stat["d_min"].iloc[0] if not stat.empty else None
            d_max = stat["d_max"].iloc[0] if not stat.empty else None
        else:
            stat = dq.sql(f"SELECT COUNT(*) AS n FROM read_parquet('{glob}')")
            n = int(stat["n"].iloc[0]) if not stat.empty else 0
            d_min = d_max = None

        rows.append({
            "dataset": ds,
            "files": len(files),
            "rows": n,
            "date_col": date_col,
            "min_date": "" if d_min is None else str(d_min),
            "max_date": "" if d_max is None else str(d_max),
        })
    return pd.DataFrame(rows)
