"""DuckDB 查询封装

直接对 raw/ 下 parquet 文件做 SQL 查询，无需加载到内存。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Sequence

import duckdb
import pandas as pd

from common.config import RAW_DIR
from common.utils import get_logger

log = get_logger("duckdb_query")


def _conn() -> duckdb.DuckDBPyConnection:
    """每次返回一个新连接（DuckDB 内部连接是线程安全的，但保持简单）。"""
    return duckdb.connect()


def _glob(dataset: str) -> str:
    return str(RAW_DIR / dataset / "*.parquet")


def _quote_list(items: Iterable[str]) -> str:
    return ",".join(f"'{x}'" for x in items)


# ---------------------------------------------------------------------------
# 通用 SQL
# ---------------------------------------------------------------------------
def sql(query: str, params: list | None = None) -> pd.DataFrame:
    """执行任意 SQL，返回 DataFrame。

    若 SQL 中引用的 parquet glob 找不到任何文件（数据集尚未拉取），
    返回空 DataFrame 而不是抛 IO Error，便于上层平稳降级。
    """
    try:
        with _conn() as c:
            return c.execute(query, params or []).fetchdf()
    except duckdb.IOException as e:
        msg = str(e)
        if "No files found that match the pattern" in msg:
            log.warning(f"数据集尚未拉取，返回空结果：{msg.splitlines()[0]}")
            return pd.DataFrame()
        raise


# ---------------------------------------------------------------------------
# 行情 / 基础数据
# ---------------------------------------------------------------------------
def get_price(
    ts_codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    cols: Sequence[str] = ("ts_code", "trade_date", "open", "high", "low", "close",
                            "pre_close", "vol", "amount"),
) -> pd.DataFrame:
    """读取日线行情。"""
    select = ",".join(cols)
    where = ["1=1"]
    if ts_codes:
        where.append(f"ts_code IN ({_quote_list(ts_codes)})")
    if start:
        where.append(f"trade_date >= '{start}'")
    if end:
        where.append(f"trade_date <= '{end}'")
    q = f"""
        SELECT {select}
        FROM read_parquet('{_glob("daily")}')
        WHERE {' AND '.join(where)}
        ORDER BY trade_date, ts_code
    """
    return sql(q)


def get_daily_basic(
    ts_codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    where = ["1=1"]
    if ts_codes:
        where.append(f"ts_code IN ({_quote_list(ts_codes)})")
    if start:
        where.append(f"trade_date >= '{start}'")
    if end:
        where.append(f"trade_date <= '{end}'")
    q = f"""
        SELECT *
        FROM read_parquet('{_glob("daily_basic")}')
        WHERE {' AND '.join(where)}
        ORDER BY trade_date, ts_code
    """
    return sql(q)


def get_adj_factor(
    ts_codes: Sequence[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    where = ["1=1"]
    if ts_codes:
        where.append(f"ts_code IN ({_quote_list(ts_codes)})")
    if start:
        where.append(f"trade_date >= '{start}'")
    if end:
        where.append(f"trade_date <= '{end}'")
    q = f"""
        SELECT ts_code, trade_date, adj_factor
        FROM read_parquet('{_glob("adj_factor")}')
        WHERE {' AND '.join(where)}
    """
    return sql(q)


# ---------------------------------------------------------------------------
# 财务（按公告日 ann_date 对齐，避免未来函数）
# ---------------------------------------------------------------------------
def get_fundamental(
    table: str,
    ts_codes: Sequence[str] | None = None,
    ann_start: str | None = None,
    ann_end: str | None = None,
) -> pd.DataFrame:
    """读取财务表，按 ann_date 过滤。

    table: income / balancesheet / cashflow / fina_indicator
    """
    where = ["1=1"]
    if ts_codes:
        where.append(f"ts_code IN ({_quote_list(ts_codes)})")
    if ann_start:
        where.append(f"ann_date >= '{ann_start}'")
    if ann_end:
        where.append(f"ann_date <= '{ann_end}'")
    q = f"""
        SELECT *
        FROM read_parquet('{_glob(table)}')
        WHERE {' AND '.join(where)}
        ORDER BY ts_code, ann_date, end_date
    """
    return sql(q)


# ---------------------------------------------------------------------------
# 股票池 / 元信息
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_stock_basic() -> pd.DataFrame:
    """全部股票元信息（含已退市）。"""
    return sql(f"SELECT * FROM read_parquet('{_glob('stock_basic')}')")


@lru_cache(maxsize=1)
def get_trade_cal() -> pd.DataFrame:
    return sql(
        f"SELECT * FROM read_parquet('{_glob('trade_cal')}') ORDER BY cal_date"
    )


def get_trade_dates(start: str | None = None, end: str | None = None) -> list[str]:
    df = get_trade_cal()
    if df.empty:
        return []
    if "is_open" in df.columns:
        df = df[df["is_open"] == 1]
    if start:
        df = df[df["cal_date"] >= start]
    if end:
        df = df[df["cal_date"] <= end]
    return df["cal_date"].astype(str).tolist()


def get_universe(
    date: str,
    *,
    exclude_st: bool = True,
    exclude_delist: bool = True,
    min_listed_days: int = 0,
) -> pd.DataFrame:
    """获取某日的股票池基础列表（仅做最基础过滤，详细过滤见 universe/filters.py）。"""
    basic = get_stock_basic()
    df = basic.copy()

    df["list_date"] = df["list_date"].astype(str)

    if exclude_delist:
        df = df[(df["delist_date"].isna()) | (df["delist_date"].astype(str) > date)]
    df = df[df["list_date"] <= date]

    if min_listed_days > 0:
        from datetime import datetime, timedelta
        cutoff = (datetime.strptime(date, "%Y%m%d") - timedelta(days=int(min_listed_days * 1.5))).strftime("%Y%m%d")
        df = df[df["list_date"] <= cutoff]

    if exclude_st and "name" in df.columns:
        df = df[~df["name"].str.contains("ST", na=False)]
    return df.reset_index(drop=True)
