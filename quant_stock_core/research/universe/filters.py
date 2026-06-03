"""股票池过滤器

每个过滤器接收一个股票列表，返回过滤后的股票列表。
组合方式：universe = builder.build(date, filters=[...])
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Sequence

import pandas as pd

from research.data.storage import duckdb_query as dq


# ---------------------------------------------------------------------------
# 基础过滤
# ---------------------------------------------------------------------------
def exclude_st(ts_codes: Sequence[str]) -> list[str]:
    basic = dq.get_stock_basic()
    keep = basic[~basic["name"].fillna("").str.contains("ST", na=False)]
    return [c for c in ts_codes if c in set(keep["ts_code"])]


def exclude_new_listing(ts_codes: Sequence[str], date: str, min_days: int = 250) -> list[str]:
    """剔除上市未满 min_days 个日历日的次新股（粗略折算）。"""
    basic = dq.get_stock_basic()[["ts_code", "list_date"]].dropna()
    cutoff = (datetime.strptime(date, "%Y%m%d") - timedelta(days=int(min_days * 1.5))).strftime("%Y%m%d")
    keep = set(basic.loc[basic["list_date"].astype(str) <= cutoff, "ts_code"])
    return [c for c in ts_codes if c in keep]


def exclude_delisted(ts_codes: Sequence[str], date: str) -> list[str]:
    basic = dq.get_stock_basic()
    delist = basic.dropna(subset=["delist_date"])
    blocked = set(delist.loc[delist["delist_date"].astype(str) <= date, "ts_code"])
    return [c for c in ts_codes if c not in blocked]


def exclude_market(ts_codes: Sequence[str], markets: Iterable[str]) -> list[str]:
    """剔除指定市场，例如 ['BJ'] 剔除北交所。"""
    basic = dq.get_stock_basic()
    blocked = set(basic.loc[basic["exchange"].isin(list(markets)), "ts_code"])
    return [c for c in ts_codes if c not in blocked]


def keep_market(ts_codes: Sequence[str], markets: Iterable[str]) -> list[str]:
    basic = dq.get_stock_basic()
    keep = set(basic.loc[basic["exchange"].isin(list(markets)), "ts_code"])
    return [c for c in ts_codes if c in keep]


# ---------------------------------------------------------------------------
# 流动性过滤（依赖 daily 数据）
# ---------------------------------------------------------------------------
def filter_min_avg_amount(
    ts_codes: Sequence[str],
    date: str,
    min_amount: float = 20_000_000,
    window: int = 20,
) -> list[str]:
    """近 window 日日均成交额 >= min_amount（元）。"""
    pad = (datetime.strptime(date, "%Y%m%d") - timedelta(days=int(window * 2))).strftime("%Y%m%d")
    df = dq.sql(f"""
        SELECT ts_code, AVG(amount) * 1000 AS avg_amount
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date >= '{pad}' AND trade_date <= '{date}'
        GROUP BY ts_code
        HAVING avg_amount >= {min_amount}
    """)
    keep = set(df["ts_code"])
    return [c for c in ts_codes if c in keep]


def filter_market_cap(
    ts_codes: Sequence[str],
    date: str,
    *,
    min_total_mv: float | None = None,
    max_total_mv: float | None = None,
    min_circ_mv: float | None = None,
    max_circ_mv: float | None = None,
) -> list[str]:
    """按市值区间过滤。

    参数单位为元；Tushare daily_basic 中 total_mv/circ_mv 单位为万元。
    """
    if not ts_codes:
        return []
    codes_sql = ",".join(f"'{c}'" for c in ts_codes)
    where = [f"trade_date = '{date}'", f"ts_code IN ({codes_sql})"]
    if min_total_mv is not None:
        where.append(f"total_mv >= {float(min_total_mv) / 10_000}")
    if max_total_mv is not None:
        where.append(f"total_mv <= {float(max_total_mv) / 10_000}")
    if min_circ_mv is not None:
        where.append(f"circ_mv >= {float(min_circ_mv) / 10_000}")
    if max_circ_mv is not None:
        where.append(f"circ_mv <= {float(max_circ_mv) / 10_000}")
    df = dq.sql(f"""
        SELECT ts_code
        FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
        WHERE {' AND '.join(where)}
    """)
    keep = set(df["ts_code"]) if not df.empty else set()
    return [c for c in ts_codes if c in keep]


def filter_recent_return(
    ts_codes: Sequence[str],
    date: str,
    *,
    window: int,
    min_return: float | None = None,
    max_return: float | None = None,
) -> list[str]:
    """按近 window 个交易日收益过滤，避免追高或过滤弱势。"""
    if not ts_codes:
        return []
    pad = (datetime.strptime(date, "%Y%m%d") - timedelta(days=int(window * 3))).strftime("%Y%m%d")
    df = dq.sql(f"""
        SELECT trade_date, ts_code, close
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date >= '{pad}' AND trade_date <= '{date}'
          AND ts_code IN ({",".join(f"'{c}'" for c in ts_codes)})
        ORDER BY trade_date
    """)
    if df.empty:
        return []
    close = df.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    if len(close) <= window:
        return ts_codes if min_return is None else []
    ret = close.pct_change(window).iloc[-1]
    keep = ret.dropna()
    if min_return is not None:
        keep = keep[keep >= min_return]
    if max_return is not None:
        keep = keep[keep <= max_return]
    keep_set = set(keep.index)
    return [c for c in ts_codes if c in keep_set]


def filter_amount_spike(
    ts_codes: Sequence[str],
    date: str,
    *,
    window: int = 20,
    max_spike: float = 4.0,
) -> list[str]:
    """过滤成交额异常爆炸的拥挤票。

    max_spike=4 表示最近一日成交额不能超过近 window 日均额 4 倍。
    """
    if not ts_codes:
        return []
    pad = (datetime.strptime(date, "%Y%m%d") - timedelta(days=int(window * 3))).strftime("%Y%m%d")
    df = dq.sql(f"""
        SELECT trade_date, ts_code, amount
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date >= '{pad}' AND trade_date <= '{date}'
          AND ts_code IN ({",".join(f"'{c}'" for c in ts_codes)})
        ORDER BY trade_date
    """)
    if df.empty:
        return []
    amount = df.pivot(index="trade_date", columns="ts_code", values="amount").sort_index()
    if len(amount) < window:
        return list(ts_codes)
    latest = amount.iloc[-1]
    avg = amount.tail(window).mean()
    keep = latest[(avg > 0) & (latest / avg <= max_spike)].index
    keep_set = set(keep)
    return [c for c in ts_codes if c in keep_set]


# ---------------------------------------------------------------------------
# 涨跌停 / 停牌过滤（用于回测层）
# ---------------------------------------------------------------------------
def is_limit_up(open_p: float, prev_close: float, market: str) -> bool:
    """判断当日是否一字涨停（开盘即涨停）。粗略用涨停价 == open。"""
    from common.config import (PRICE_LIMIT_PCT, KCB_GEM_LIMIT_PCT, BJ_LIMIT_PCT)
    if market == "BJ":
        pct = BJ_LIMIT_PCT
    elif market in ("KCB", "GEM"):
        pct = KCB_GEM_LIMIT_PCT
    else:
        pct = PRICE_LIMIT_PCT
    limit = round(prev_close * (1 + pct), 2)
    return abs(open_p - limit) < 1e-4


def filter_tradable(date: str, ts_codes: Sequence[str]) -> list[str]:
    """剔除当日停牌、一字涨跌停，返回可成交标的。"""
    df = dq.sql(f"""
        SELECT d.ts_code, d.open, d.high, d.low, d.close, d.pre_close, d.vol
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
        WHERE d.trade_date = '{date}'
          AND d.ts_code IN ({",".join(f"'{c}'" for c in ts_codes)})
    """) if ts_codes else pd.DataFrame()
    if df.empty:
        return []
    # 简化：vol 为 0 视为停牌；high == low 视为一字
    df = df[df["vol"] > 0]
    df = df[df["high"] != df["low"]]
    return df["ts_code"].tolist()
