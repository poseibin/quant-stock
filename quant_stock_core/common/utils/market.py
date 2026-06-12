from __future__ import annotations

import pandas as pd

from common.config import BJ_LIMIT_PCT, KCB_GEM_LIMIT_PCT, PRICE_LIMIT_PCT, ST_PRICE_LIMIT_PCT

BJ_EXCHANGES = {"BJ", "BSE"}


def normalize_ts_code(ts_code: object) -> str:
    return str(ts_code or "").strip().upper()


def is_bj_stock(ts_code: object = "", exchange: object = "", market: object = "") -> bool:
    code = normalize_ts_code(ts_code)
    exchange_value = str(exchange or "").strip().upper()
    market_value = str(market or "")
    return (
        exchange_value in BJ_EXCHANGES
        or "北交" in market_value
        or code.endswith(".BJ")
        or code.startswith("4")
        or code.startswith("8")
    )


def bj_stock_mask(df: pd.DataFrame) -> pd.Series:
    index = df.index
    ts_code = df.get("ts_code", pd.Series("", index=index)).fillna("").astype(str).str.upper()
    exchange = df.get("exchange", pd.Series("", index=index)).fillna("").astype(str).str.upper()
    market = df.get("market", pd.Series("", index=index)).fillna("").astype(str)
    return (
        exchange.isin(BJ_EXCHANGES)
        | market.str.contains("北交", na=False)
        | ts_code.str.endswith(".BJ")
        | ts_code.str.startswith("4")
        | ts_code.str.startswith("8")
    )


def bj_exclude_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias and not alias.endswith(".") else alias
    return (
        f"COALESCE({prefix}exchange, '') NOT IN ('BJ', 'BSE') "
        f"AND COALESCE({prefix}market, '') NOT LIKE '%北交%' "
        f"AND COALESCE({prefix}ts_code, '') NOT LIKE '4%' "
        f"AND COALESCE({prefix}ts_code, '') NOT LIKE '8%' "
        f"AND COALESCE({prefix}ts_code, '') NOT LIKE '%.BJ'"
    )


def bj_include_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias and not alias.endswith(".") else alias
    return (
        f"(COALESCE({prefix}exchange, '') IN ('BJ', 'BSE') "
        f"OR COALESCE({prefix}market, '') LIKE '%北交%' "
        f"OR COALESCE({prefix}ts_code, '') LIKE '4%' "
        f"OR COALESCE({prefix}ts_code, '') LIKE '8%' "
        f"OR COALESCE({prefix}ts_code, '') LIKE '%.BJ')"
    )


def is_star_stock(ts_code: object = "", market: object = "") -> bool:
    code = normalize_ts_code(ts_code)
    return code.startswith("688") or "科创" in str(market or "")


def is_gem_stock(ts_code: object = "", market: object = "") -> bool:
    code = normalize_ts_code(ts_code)
    return code.startswith("300") or code.startswith("301") or "创业" in str(market or "")


def is_restricted_stock(ts_code: object = "", exchange: object = "", market: object = "") -> bool:
    return is_bj_stock(ts_code, exchange, market) or is_star_stock(ts_code, market) or is_gem_stock(ts_code, market)


def star_stock_mask(df: pd.DataFrame) -> pd.Series:
    index = df.index
    ts_code = df.get("ts_code", pd.Series("", index=index)).fillna("").astype(str).str.upper()
    market = df.get("market", pd.Series("", index=index)).fillna("").astype(str)
    return ts_code.str.startswith("688") | market.str.contains("科创", na=False)


def gem_stock_mask(df: pd.DataFrame) -> pd.Series:
    index = df.index
    ts_code = df.get("ts_code", pd.Series("", index=index)).fillna("").astype(str).str.upper()
    market = df.get("market", pd.Series("", index=index)).fillna("").astype(str)
    return ts_code.str.startswith("300") | ts_code.str.startswith("301") | market.str.contains("创业", na=False)


def restricted_stock_mask(df: pd.DataFrame) -> pd.Series:
    return bj_stock_mask(df) | star_stock_mask(df) | gem_stock_mask(df)


def exclude_restricted_stocks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.loc[~restricted_stock_mask(df)].copy()


def restricted_exclude_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias and not alias.endswith(".") else alias
    return (
        f"{bj_exclude_sql(alias)} "
        f"AND COALESCE({prefix}market, '') NOT LIKE '%科创%' "
        f"AND COALESCE({prefix}market, '') NOT LIKE '%创业%' "
        f"AND COALESCE({prefix}ts_code, '') NOT LIKE '688%' "
        f"AND COALESCE({prefix}ts_code, '') NOT LIKE '300%' "
        f"AND COALESCE({prefix}ts_code, '') NOT LIKE '301%'"
    )


def price_limit_rate(ts_code: object, name: object = "", exchange: object = "", market: object = "") -> float:
    code = normalize_ts_code(ts_code)
    upper_name = str(name or "").upper()
    if "ST" in upper_name:
        return ST_PRICE_LIMIT_PCT
    if is_bj_stock(code, exchange, market):
        return BJ_LIMIT_PCT
    if code.startswith("688") or code.startswith("300") or code.startswith("301") or "科创" in str(market or "") or "创业" in str(market or ""):
        return KCB_GEM_LIMIT_PCT
    return PRICE_LIMIT_PCT


def price_limit_pct_series(df: pd.DataFrame, listed_trading_days: pd.Series | None = None) -> pd.Series:
    trade_date = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    delist_date = pd.to_datetime(
        df.get("delist_date", pd.Series("", index=df.index)).astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    name = df.get("name", pd.Series("", index=df.index)).fillna("").astype(str)

    pct = pd.Series(PRICE_LIMIT_PCT, index=df.index, dtype=float)
    is_st = name.str.contains("ST", na=False)
    is_bj = bj_stock_mask(df)
    is_star = star_stock_mask(df)
    is_gem = gem_stock_mask(df)

    star_20 = is_star & (trade_date >= pd.Timestamp("2019-07-22"))
    gem_20 = is_gem & (trade_date >= pd.Timestamp("2020-08-24"))
    bj_30 = is_bj & (trade_date >= pd.Timestamp("2021-11-15"))

    pct.loc[star_20 | gem_20] = KCB_GEM_LIMIT_PCT
    pct.loc[bj_30 | is_bj] = BJ_LIMIT_PCT
    pct.loc[is_st] = ST_PRICE_LIMIT_PCT

    delist_window = delist_date.notna() & (trade_date <= delist_date) & ((delist_date - trade_date).dt.days <= 30)
    pct.loc[delist_window] = PRICE_LIMIT_PCT

    if listed_trading_days is not None:
        mainboard_ipo_free = (~is_star & ~is_gem & ~is_bj) & (listed_trading_days == 1)
        registration_ipo_free = (is_star | gem_20 | is_bj) & (listed_trading_days >= 1) & (listed_trading_days <= 5)
        pct.loc[mainboard_ipo_free | registration_ipo_free] = float("inf")
    return pct


def price_limit_threshold_pct(ts_code: object, name: object = "", exchange: object = "", market: object = "", buffer_pct: float = 0.8) -> float:
    return max(0.0, price_limit_rate(ts_code, name, exchange, market) * 100.0 - buffer_pct)
