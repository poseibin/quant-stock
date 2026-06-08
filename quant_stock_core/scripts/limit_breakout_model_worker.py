from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import replace_sql, write_transaction
from scripts.limit_up_model_worker import (
    limit_threshold,
    metrics_for_top,
    now_text,
    sample_quality_summary,
    safe_float,
    tier_metrics_list,
    top_rows_by_date,
)


TASK_NAME = "limit_breakout_model"

FEATURES = [
    "flat_score",
    "startup_score",
    "base_ratio_250",
    "base_ratio_500",
    "base_return_250",
    "base_return_500",
    "base_volatility_120",
    "ret3",
    "ret5",
    "ret10",
    "ret20",
    "drawdown60",
    "distance_high250",
    "breakout_ratio250",
    "amount_chg5",
    "amount_chg20",
    "volume_surge_120",
    "turnover_rate",
    "volume_ratio",
    "limit_up_count10",
    "circ_mv_log",
    "roe",
    "netprofit_margin",
    "debt_to_assets",
    "industry_ret5",
    "industry_ret20",
    "industry_up_ratio",
    "industry_limit_up_ratio",
    "market_up_ratio",
    "market_limit_up_ratio",
]


def tier_set(top_k: int) -> list[int]:
    out: list[int] = []
    for value in (1, 3, 5, int(top_k)):
        if value > 0 and value not in out:
            out.append(value)
    return out


def equity_stats(daily_returns: pd.Series) -> dict[str, float]:
    if daily_returns.empty:
        return {"compound_return": 0.0, "max_drawdown": 0.0}
    equity = (1 + daily_returns.fillna(0.0)).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak.replace(0, np.nan) - 1
    return {
        "compound_return": safe_float(equity.iloc[-1] - 1),
        "max_drawdown": safe_float(drawdown.min()),
    }


def trade_return_from_bounds(entry_price: float, future_high: float, future_low: float, exit_close: float, take_profit: float, stop_loss: float, buy_slippage: float, sell_slippage: float, commission: float, stamp_tax: float) -> float | None:
    if entry_price <= 0 or future_high <= 0 or future_low <= 0 or exit_close <= 0:
        return None
    high_ret = future_high / entry_price - 1
    low_ret = future_low / entry_price - 1
    if low_ret <= stop_loss:
        gross = stop_loss
    elif high_ret >= take_profit:
        gross = take_profit
    else:
        gross = exit_close / entry_price - 1
    return (1 + gross) * (1 - sell_slippage - commission - stamp_tax) / (1 + buy_slippage + commission) - 1


def simulate_breakout_pullback_return(row: pd.Series, hold_days: int, entry_discount: float, touch_days: int, take_profit: float, stop_loss: float, buy_slippage: float, sell_slippage: float, commission: float, stamp_tax: float) -> float | None:
    signal_close = safe_float(row.get("close"))
    if signal_close <= 0:
        return None
    entry_price = signal_close * (1 + entry_discount)
    touch_day = 0
    for day in range(1, min(touch_days, hold_days) + 1):
        day_low = safe_float(row.get(f"next_low_{day}d"))
        day_high = safe_float(row.get(f"next_high_{day}d"))
        if day_low > 0 and day_high > 0 and day_low <= entry_price <= day_high:
            touch_day = day
            break
    if touch_day <= 0:
        return None
    highs = [safe_float(row.get(f"next_high_{day}d")) for day in range(touch_day, hold_days + 1)]
    lows = [safe_float(row.get(f"next_low_{day}d")) for day in range(touch_day, hold_days + 1)]
    highs = [value for value in highs if value > 0]
    lows = [value for value in lows if value > 0]
    future_high = max(highs) if highs else 0.0
    future_low = min(lows) if lows else 0.0
    exit_close = safe_float(row.get(f"exit_close_{hold_days}d"))
    return trade_return_from_bounds(entry_price, future_high, future_low, exit_close, take_profit, stop_loss, buy_slippage, sell_slippage, commission, stamp_tax)


def simulate_breakout_confirmation_return(row: pd.Series, hold_days: int, max_gap: float, max_next_return: float, take_profit: float, stop_loss: float, buy_slippage: float, sell_slippage: float, commission: float, stamp_tax: float) -> float | None:
    signal_close = safe_float(row.get("close"))
    entry_open = safe_float(row.get("entry_open_1d"))
    entry_gap = safe_float(row.get("entry_gap_1d"))
    next_close = safe_float(row.get("exit_close_1d"))
    if signal_close <= 0 or entry_open <= 0 or next_close <= 0:
        return None
    next_return = next_close / signal_close - 1
    if entry_gap > max_gap or next_return <= 0 or next_return > max_next_return:
        return None
    if hold_days <= 1:
        return None
    highs = [safe_float(row.get(f"next_high_{day}d")) for day in range(2, hold_days + 2)]
    lows = [safe_float(row.get(f"next_low_{day}d")) for day in range(2, hold_days + 2)]
    highs = [value for value in highs if value > 0]
    lows = [value for value in lows if value > 0]
    future_high = max(highs) if highs else 0.0
    future_low = min(lows) if lows else 0.0
    exit_close = safe_float(row.get(f"exit_close_after_confirm_{hold_days}d"))
    return trade_return_from_bounds(next_close, future_high, future_low, exit_close, take_profit, stop_loss, buy_slippage, sell_slippage, commission, stamp_tax)


def breakout_trade_metrics(pred: pd.DataFrame, top_n: int, hold_days: int, entry_mode: str, entry_discount: float = 0.0, touch_days: int = 3, max_gap: float = 0.04, max_next_return: float = 0.08, take_profit: float = 0.12, stop_loss: float = -0.055, buy_slippage: float = 0.002, sell_slippage: float = 0.002, commission: float = 0.00025, stamp_tax: float = 0.0005, min_market_up_ratio: float = 0.0, min_market_limit_up_ratio: float = 0.0) -> dict[str, Any]:
    frame = pred.copy()
    if min_market_up_ratio > 0:
        frame = frame[frame["market_up_ratio"] >= min_market_up_ratio]
    if min_market_limit_up_ratio > 0:
        frame = frame[frame["market_limit_up_ratio"] >= min_market_limit_up_ratio]
    signals = top_rows_by_date(frame, int(top_n))
    trade_rows: list[dict[str, Any]] = []
    for row in signals.to_dict("records"):
        series = pd.Series(row)
        if entry_mode == "pullback":
            ret = simulate_breakout_pullback_return(series, hold_days, entry_discount, touch_days, take_profit, stop_loss, buy_slippage, sell_slippage, commission, stamp_tax)
        else:
            ret = simulate_breakout_confirmation_return(series, hold_days, max_gap, max_next_return, take_profit, stop_loss, buy_slippage, sell_slippage, commission, stamp_tax)
        if ret is None:
            continue
        trade_rows.append({"trade_date": str(row.get("trade_date")), "year": int(str(row.get("trade_date"))[:4]), "return": safe_float(ret)})
    trades = pd.DataFrame(trade_rows)
    if entry_mode == "pullback":
        label = f"回踩{entry_discount:.0%}买"
    else:
        label = "次日确认买"
    if min_market_up_ratio > 0 or min_market_limit_up_ratio > 0:
        label += f" / 市场{min_market_up_ratio:.0%}+涨停{min_market_limit_up_ratio:.1%}+"
    base = {
        "name": f"Top{top_n} / {label} / {hold_days}日",
        "entry_mode": entry_mode,
        "top_n": int(top_n),
        "hold_days": int(hold_days),
        "signal_count": int(len(signals)),
        "rule": {
            "entry_mode": entry_mode,
            "entry_discount": entry_discount,
            "touch_days": touch_days,
            "max_gap": max_gap,
            "max_next_return": max_next_return,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "min_market_up_ratio": min_market_up_ratio,
            "min_market_limit_up_ratio": min_market_limit_up_ratio,
            "buy_slippage": buy_slippage,
            "sell_slippage": sell_slippage,
            "commission": commission,
            "stamp_tax": stamp_tax,
            "path_assumption": "daily_ohlc_stop_first",
        },
    }
    if trades.empty:
        return {**base, "trade_count": 0, "fill_rate": 0.0, "avg_return": 0.0, "win_rate": 0.0, "compound_return": 0.0, "max_drawdown": 0.0, "yearly": []}
    daily_returns = trades.groupby("trade_date")["return"].mean().sort_index()
    stats = equity_stats(daily_returns)
    yearly = []
    for year, year_trades in trades.groupby("year", sort=True):
        year_daily = year_trades.groupby("trade_date")["return"].mean().sort_index()
        year_stats = equity_stats(year_daily)
        yearly.append({
            "year": int(year),
            "trade_count": int(len(year_trades)),
            "avg_return": safe_float(year_trades["return"].mean()),
            "win_rate": safe_float((year_trades["return"] > 0).mean()),
            "compound_return": year_stats["compound_return"],
            "max_drawdown": year_stats["max_drawdown"],
        })
    return {
        **base,
        "trade_count": int(len(trades)),
        "fill_rate": safe_float(len(trades) / max(len(signals), 1)),
        "avg_return": safe_float(trades["return"].mean()),
        "win_rate": safe_float((trades["return"] > 0).mean()),
        "compound_return": stats["compound_return"],
        "max_drawdown": stats["max_drawdown"],
        "yearly": yearly,
    }


def breakout_trading_validation(pred: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        breakout_trade_metrics(pred, top_n=3, hold_days=5, entry_mode="pullback", entry_discount=-0.05, touch_days=3, stop_loss=-0.06, min_market_up_ratio=0.45, min_market_limit_up_ratio=0.015),
        breakout_trade_metrics(pred, top_n=3, hold_days=5, entry_mode="pullback", entry_discount=-0.05, touch_days=3, stop_loss=-0.06, min_market_up_ratio=0.45, min_market_limit_up_ratio=0.010),
        breakout_trade_metrics(pred, top_n=3, hold_days=5, entry_mode="pullback", entry_discount=-0.05, touch_days=3, stop_loss=-0.06, min_market_up_ratio=0.60, min_market_limit_up_ratio=0.020),
        breakout_trade_metrics(pred, top_n=3, hold_days=5, entry_mode="pullback", entry_discount=-0.02, touch_days=3),
        breakout_trade_metrics(pred, top_n=5, hold_days=5, entry_mode="pullback", entry_discount=0.00, touch_days=3),
    ]


def ensure_tables(db_path: str | None) -> None:
    with write_transaction(db_path) as conn:
        if conn.backend == "mysql":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_breakout_model_runs (
                    run_id VARCHAR(255) PRIMARY KEY,
                    start_date VARCHAR(16) NOT NULL,
                    end_date VARCHAR(16) NOT NULL,
                    horizon BIGINT NOT NULL DEFAULT 5,
                    model_type VARCHAR(64) NOT NULL,
                    feature_count BIGINT NOT NULL DEFAULT 0,
                    status VARCHAR(32) NOT NULL,
                    summary_json LONGTEXT,
                    model_path VARCHAR(1024),
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_breakout_model_features (
                    run_id VARCHAR(255) NOT NULL,
                    feature VARCHAR(255) NOT NULL,
                    importance DOUBLE NOT NULL DEFAULT 0,
                    rank_no BIGINT NOT NULL DEFAULT 0,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, feature)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_breakout_model_predictions (
                    run_id VARCHAR(255) NOT NULL,
                    trade_date VARCHAR(16) NOT NULL,
                    ts_code VARCHAR(32) NOT NULL,
                    name VARCHAR(255) NOT NULL DEFAULT '',
                    industry VARCHAR(255) NOT NULL DEFAULT '',
                    prob DOUBLE NOT NULL DEFAULT 0,
                    model_score DOUBLE NOT NULL DEFAULT 0,
                    label BIGINT NOT NULL DEFAULT 0,
                    fwd5_return DOUBLE NOT NULL DEFAULT 0,
                    fwd5_max_return DOUBLE NOT NULL DEFAULT 0,
                    max_drawdown_5d DOUBLE NOT NULL DEFAULT 0,
                    hit_limit_up_5d BIGINT NOT NULL DEFAULT 0,
                    is_latest BIGINT NOT NULL DEFAULT 0,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, trade_date, ts_code),
                    KEY idx_limit_breakout_model_latest (run_id, is_latest, model_score),
                    KEY idx_limit_breakout_model_date (run_id, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_breakout_model_tm_slices (
                    run_id VARCHAR(255) NOT NULL,
                    trade_date VARCHAR(16) NOT NULL,
                    candidate_count BIGINT NOT NULL DEFAULT 0,
                    top_count BIGINT NOT NULL DEFAULT 0,
                    avg_return DOUBLE NOT NULL DEFAULT 0,
                    avg_max_return DOUBLE NOT NULL DEFAULT 0,
                    hit_rate DOUBLE NOT NULL DEFAULT 0,
                    limit_up_hit_rate DOUBLE NOT NULL DEFAULT 0,
                    avg_drawdown DOUBLE NOT NULL DEFAULT 0,
                    rank_ic DOUBLE NOT NULL DEFAULT 0,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        else:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS limit_breakout_model_runs (
                    run_id TEXT PRIMARY KEY,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    horizon INTEGER NOT NULL DEFAULT 5,
                    model_type TEXT NOT NULL,
                    feature_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    model_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS limit_breakout_model_features (
                    run_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0,
                    rank_no INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, feature)
                );
                CREATE TABLE IF NOT EXISTS limit_breakout_model_predictions (
                    run_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    ts_code TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    industry TEXT NOT NULL DEFAULT '',
                    prob REAL NOT NULL DEFAULT 0,
                    model_score REAL NOT NULL DEFAULT 0,
                    label INTEGER NOT NULL DEFAULT 0,
                    fwd5_return REAL NOT NULL DEFAULT 0,
                    fwd5_max_return REAL NOT NULL DEFAULT 0,
                    max_drawdown_5d REAL NOT NULL DEFAULT 0,
                    hit_limit_up_5d INTEGER NOT NULL DEFAULT 0,
                    is_latest INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, trade_date, ts_code)
                );
                CREATE TABLE IF NOT EXISTS limit_breakout_model_tm_slices (
                    run_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    top_count INTEGER NOT NULL DEFAULT 0,
                    avg_return REAL NOT NULL DEFAULT 0,
                    avg_max_return REAL NOT NULL DEFAULT 0,
                    hit_rate REAL NOT NULL DEFAULT 0,
                    limit_up_hit_rate REAL NOT NULL DEFAULT 0,
                    avg_drawdown REAL NOT NULL DEFAULT 0,
                    rank_ic REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, trade_date)
                );
                """
            )


def read_market_panel(data_path: Path, start: str, end: str) -> pd.DataFrame:
    raw = data_path / "raw"
    warmup = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=900)).strftime("%Y%m%d")
    con = duckdb.connect()
    try:
        market = con.execute(
            f"""
            SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pct_chg, d.amount,
                   COALESCE(b.turnover_rate, 0) AS turnover_rate,
                   COALESCE(b.volume_ratio, 0) AS volume_ratio,
                   COALESCE(b.circ_mv, 0) AS circ_mv,
                   COALESCE(s.name, '') AS name,
                   COALESCE(NULLIF(s.industry, ''), '未分类') AS industry
            FROM read_parquet('{raw / "daily" / "*.parquet"}') d
            LEFT JOIN read_parquet('{raw / "daily_basic" / "*.parquet"}') b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            LEFT JOIN read_parquet('{raw / "stock_basic" / "data.parquet"}') s
              ON d.ts_code = s.ts_code
            WHERE d.trade_date BETWEEN '{warmup}' AND '{end}'
              AND d.close IS NOT NULL
              AND d.pct_chg IS NOT NULL
              AND COALESCE(s.list_status, 'L') = 'L'
              AND COALESCE(s.name, '') NOT LIKE '%ST%'
              AND COALESCE(s.name, '') NOT LIKE '退市%'
            ORDER BY d.ts_code, d.trade_date
            """
        ).fetch_df()
        financial = con.execute(
            f"""
            SELECT ts_code,
                   COALESCE(NULLIF(ann_date, ''), end_date) AS report_date,
                   COALESCE(roe, 0) AS roe,
                   COALESCE(netprofit_margin, 0) AS netprofit_margin,
                   COALESCE(debt_to_assets, 0) AS debt_to_assets
            FROM read_parquet('{raw / "fina_indicator" / "*.parquet"}')
            WHERE ts_code IS NOT NULL
              AND COALESCE(NULLIF(ann_date, ''), end_date) IS NOT NULL
              AND COALESCE(NULLIF(ann_date, ''), end_date) <= '{end}'
            ORDER BY ts_code, report_date
            """
        ).fetch_df()
    finally:
        con.close()
    return attach_asof_financials(market, financial)


def attach_asof_financials(market: pd.DataFrame, financial: pd.DataFrame) -> pd.DataFrame:
    if market.empty:
        return market
    market = market.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    if financial.empty:
        market[["roe", "netprofit_margin", "debt_to_assets"]] = 0.0
        return market

    out_parts: list[pd.DataFrame] = []
    financial = financial.copy()
    financial["report_date"] = financial["report_date"].astype(str)
    financial["report_dt"] = pd.to_datetime(financial["report_date"], format="%Y%m%d", errors="coerce")
    financial = financial.dropna(subset=["report_dt"])
    for col in ["roe", "netprofit_margin", "debt_to_assets"]:
        financial[col] = pd.to_numeric(financial[col], errors="coerce").fillna(0.0)
    fin_groups = {code: group.sort_values("report_date") for code, group in financial.groupby("ts_code", sort=False)}
    for code, group in market.groupby("ts_code", sort=False):
        fin = fin_groups.get(str(code))
        current = group.copy()
        current["trade_dt"] = pd.to_datetime(current["trade_date"], format="%Y%m%d", errors="coerce")
        if fin is None or fin.empty:
            current[["roe", "netprofit_margin", "debt_to_assets"]] = 0.0
            current = current.drop(columns=["trade_dt"])
        else:
            joined = pd.merge_asof(
                current.sort_values("trade_dt"),
                fin[["report_dt", "roe", "netprofit_margin", "debt_to_assets"]].sort_values("report_dt"),
                left_on="trade_dt",
                right_on="report_dt",
                direction="backward",
            )
            current = joined.drop(columns=["trade_dt", "report_dt"])
            current[["roe", "netprofit_margin", "debt_to_assets"]] = current[["roe", "netprofit_margin", "debt_to_assets"]].fillna(0.0)
        out_parts.append(current)
    return pd.concat(out_parts, ignore_index=True).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def add_features(raw: pd.DataFrame, start: str, end: str, horizon: int) -> pd.DataFrame:
    df = raw.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    numeric_cols = [
        "open", "high", "low", "close", "pct_chg", "amount", "turnover_rate",
        "volume_ratio", "circ_mv", "roe", "netprofit_margin", "debt_to_assets",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    group = df.groupby("ts_code", sort=False)

    df["ret3"] = group["close"].pct_change(3)
    df["ret5"] = group["close"].pct_change(5)
    df["ret10"] = group["close"].pct_change(10)
    df["ret20"] = group["close"].pct_change(20)
    df["base_return_250"] = group["close"].pct_change(250)
    df["base_return_500"] = group["close"].pct_change(500)
    high60 = group["high"].transform(lambda s: s.rolling(60, min_periods=20).max())
    high250 = group["high"].transform(lambda s: s.rolling(250, min_periods=120).max())
    low250 = group["low"].transform(lambda s: s.rolling(250, min_periods=120).min())
    high500 = group["high"].transform(lambda s: s.rolling(500, min_periods=240).max())
    low500 = group["low"].transform(lambda s: s.rolling(500, min_periods=240).min())
    df["base_ratio_250"] = high250 / low250.replace(0, np.nan)
    df["base_ratio_500"] = high500 / low500.replace(0, np.nan)
    df["base_volatility_120"] = group["pct_chg"].transform(lambda s: s.rolling(120, min_periods=40).std())
    df["drawdown60"] = df["close"] / high60.replace(0, np.nan) - 1
    df["distance_high250"] = df["close"] / high250.replace(0, np.nan) - 1
    df["breakout_ratio250"] = df["close"] / high250.replace(0, np.nan) - 1
    amount5 = group["amount"].transform(lambda s: s.rolling(5, min_periods=2).mean())
    amount20 = group["amount"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    amount120 = group["amount"].transform(lambda s: s.rolling(120, min_periods=30).mean())
    df["amount_chg5"] = df["amount"] / amount5.replace(0, np.nan) - 1
    df["amount_chg20"] = df["amount"] / amount20.replace(0, np.nan) - 1
    df["volume_surge_120"] = df["amount"] / amount120.replace(0, np.nan)
    df["circ_mv_log"] = np.log1p(df["circ_mv"].clip(lower=0))
    df["is_limit_up"] = df.apply(lambda row: safe_float(row["pct_chg"]) >= limit_threshold(str(row["ts_code"]), str(row["name"])), axis=1)
    df["limit_up_count10"] = group["is_limit_up"].transform(lambda s: s.rolling(10, min_periods=1).sum())

    df["flat_score"] = (
        ((2.2 - df["base_ratio_500"]) / 1.2).clip(0, 1) * 0.30
        + ((2.0 - df["base_ratio_250"]) / 1.0).clip(0, 1) * 0.25
        + ((0.45 - df["base_return_500"].abs()) / 0.45).clip(0, 1) * 0.20
        + ((0.018 - df["base_volatility_120"]) / 0.018).clip(0, 1) * 0.25
    )
    df["startup_score"] = (
        (df["ret20"] / 0.45).clip(0, 1) * 0.28
        + (df["ret5"] / 0.18).clip(0, 1) * 0.22
        + ((df["volume_surge_120"] - 1.0) / 4.0).clip(0, 1) * 0.22
        + ((df["breakout_ratio250"] + 0.05) / 0.22).clip(0, 1) * 0.18
        + (df["limit_up_count10"] / 3.0).clip(0, 1) * 0.10
    )

    by_industry = df.groupby(["trade_date", "industry"], sort=False)
    industry = by_industry.agg(
        industry_ret1=("pct_chg", "mean"),
        industry_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        industry_limit_up_count=("is_limit_up", "sum"),
        industry_count=("ts_code", "count"),
    ).reset_index().sort_values(["industry", "trade_date"])
    industry_group = industry.groupby("industry", sort=False)
    industry["industry_ret5"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    industry["industry_ret20"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(20, min_periods=5).sum())
    industry["industry_limit_up_ratio"] = industry["industry_limit_up_count"] / industry["industry_count"].replace(0, np.nan)
    market = df.groupby("trade_date", sort=False).agg(
        market_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        market_limit_up_count=("is_limit_up", "sum"),
        market_count=("ts_code", "count"),
    ).reset_index()
    market["market_limit_up_ratio"] = market["market_limit_up_count"] / market["market_count"].replace(0, np.nan)
    df = df.merge(industry.drop(columns=["industry_count"]), on=["trade_date", "industry"], how="left")
    df = df.merge(market.drop(columns=["market_count"]), on="trade_date", how="left")

    next_close = group["close"].shift(-horizon)
    future_high = group["high"].transform(lambda s: s.shift(-1).iloc[::-1].rolling(horizon, min_periods=1).max().iloc[::-1])
    future_low = group["low"].transform(lambda s: s.shift(-1).iloc[::-1].rolling(horizon, min_periods=1).min().iloc[::-1])
    future_limit = group["is_limit_up"].transform(lambda s: s.shift(-1).iloc[::-1].rolling(horizon, min_periods=1).max().iloc[::-1])
    df["entry_open_1d"] = group["open"].shift(-1)
    df["entry_gap_1d"] = df["entry_open_1d"] / df["close"].replace(0, np.nan) - 1
    df["entry_pct_chg_1d"] = group["pct_chg"].shift(-1)
    df["fwd5_return"] = next_close / df["close"].replace(0, np.nan) - 1
    df["fwd5_max_return"] = future_high / df["close"].replace(0, np.nan) - 1
    df["max_drawdown_5d"] = future_low / df["close"].replace(0, np.nan) - 1
    df["hit_limit_up_5d"] = future_limit.fillna(0).astype(int)
    for hold_days in (1, 3, 5):
        df[f"exit_close_{hold_days}d"] = group["close"].shift(-hold_days)
        df[f"future_high_{hold_days}d"] = group["high"].transform(lambda s, h=hold_days: s.shift(-1).iloc[::-1].rolling(h, min_periods=1).max().iloc[::-1])
        df[f"future_low_{hold_days}d"] = group["low"].transform(lambda s, h=hold_days: s.shift(-1).iloc[::-1].rolling(h, min_periods=1).min().iloc[::-1])
        df[f"exit_close_after_confirm_{hold_days}d"] = group["close"].shift(-(hold_days + 1))
    for day in range(1, 7):
        df[f"next_high_{day}d"] = group["high"].shift(-day)
        df[f"next_low_{day}d"] = group["low"].shift(-day)

    df["label"] = (((df["fwd5_max_return"] >= 0.10) | (df["hit_limit_up_5d"] > 0)) & (df["max_drawdown_5d"] > -0.12)).astype(int)
    df["year"] = df["trade_date"].str.slice(0, 4).astype(int)
    df = df.replace([np.inf, -np.inf], np.nan)
    df[FEATURES] = df[FEATURES].fillna(0.0)
    candidate_mask = (
        (df["flat_score"] >= 0.30)
        & (df["startup_score"] >= 0.16)
        & (df["base_ratio_250"].between(1.0, 2.6))
        & (df["close"] >= 3.0)
        & (df["amount"] >= 25000)
        & (df["turnover_rate"] >= 0.25)
        & (df["trade_date"].between(start, end))
    )
    return df[candidate_mask].reset_index(drop=True)


def train_model(args: argparse.Namespace, data: pd.DataFrame) -> dict[str, Any]:
    import lightgbm as lgb
    from sklearn.metrics import average_precision_score, roc_auc_score

    min_year = max(int(data["year"].min()) + int(args.min_train_years), int(args.min_test_year or 0))
    test_years = [year for year in sorted(data["year"].unique()) if year >= min_year]
    predictions: list[pd.DataFrame] = []
    fold_metrics: list[dict[str, Any]] = []
    models: list[Any] = []
    importance = pd.Series(0.0, index=FEATURES, dtype="float64")
    x_all = data[FEATURES].astype(float)
    y_all = data["label"].astype(int)

    for year in test_years:
        train_mask = data["year"] < year
        test_mask = data["year"] == year
        if int(train_mask.sum()) < int(args.min_train_rows) or int(test_mask.sum()) == 0:
            continue
        y_train = y_all.loc[train_mask]
        pos = int(y_train.sum())
        if pos < 20:
            continue
        neg = int(len(y_train) - pos)
        model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=280,
            learning_rate=0.035,
            num_leaves=31,
            max_depth=5,
            min_child_samples=35,
            subsample=0.88,
            colsample_bytree=0.9,
            reg_alpha=0.08,
            reg_lambda=1.2,
            scale_pos_weight=max(1.0, neg / max(pos, 1)),
            random_state=20260607,
            n_jobs=int(args.threads),
            verbosity=-1,
        )
        model.fit(x_all.loc[train_mask], y_train)
        prob = model.predict_proba(x_all.loc[test_mask])[:, 1]
        fold = data.loc[test_mask].copy()
        fold["prob"] = prob.astype(float)
        fold["model_score"] = fold["prob"] * 100.0
        predictions.append(fold)
        fold_baseline = safe_float(fold["fwd5_return"].mean())
        fold_top = top_rows_by_date(fold, int(args.top_k))
        fold_metrics.append({
            "year": int(year),
            "rows": int(len(fold)),
            "train_rows": int(train_mask.sum()),
            "train_positive_rate": safe_float(y_train.mean()),
            "scale_pos_weight": safe_float(max(1.0, neg / max(pos, 1))),
            "positive_rate": safe_float(fold["label"].mean()),
            "baseline_return": fold_baseline,
            "roc_auc": safe_float(roc_auc_score(fold["label"], prob)) if fold["label"].nunique() > 1 else 0.0,
            "avg_precision": safe_float(average_precision_score(fold["label"], prob)) if fold["label"].nunique() > 1 else 0.0,
            "top_return": safe_float(fold_top["fwd5_return"].mean()),
            "top_excess_return": safe_float(fold_top["fwd5_return"].mean()) - fold_baseline,
            "top_hit_rate": safe_float(fold_top["label"].mean()),
            "top_limit_up_rate": safe_float(fold_top["hit_limit_up_5d"].mean()),
            "top_drawdown": safe_float(fold_top["max_drawdown_5d"].mean()),
            "tiers": tier_metrics_list(fold, tier_set(int(args.top_k)), fold_baseline),
        })
        importance += pd.Series(model.feature_importances_, index=FEATURES)
        models.append(model)

    if not predictions:
        raise RuntimeError("no walk-forward prediction was generated")
    pred = pd.concat(predictions, ignore_index=True).sort_values(["trade_date", "model_score"], ascending=[True, False])
    latest_date = str(data["trade_date"].max())
    latest_pool = data[data["trade_date"] == latest_date].copy()
    if models and not latest_pool.empty:
        latest_pool["prob"] = models[-1].predict_proba(latest_pool[FEATURES].astype(float))[:, 1]
        latest_pool["model_score"] = latest_pool["prob"] * 100.0
        latest_pool["is_latest"] = 1
    pred["is_latest"] = 0
    out_pred = pd.concat([pred, latest_pool], ignore_index=True, sort=False) if not latest_pool.empty else pred

    daily_slices = []
    for trade_date, group in pred.groupby("trade_date", sort=True):
        m = metrics_for_top(group, int(args.top_k))
        daily_slices.append({"trade_date": str(trade_date), "candidate_count": int(len(group)), **m})
    slices = pd.DataFrame(daily_slices)
    baseline_return = safe_float(pred["fwd5_return"].mean())
    top_rows = top_rows_by_date(pred, int(args.top_k))
    overall = {
        "rows": int(len(pred)),
        "candidate_rows": int(len(data)),
        "latest_date": latest_date,
        "latest_count": int(len(latest_pool)),
        "positive_rate": safe_float(pred["label"].mean()),
        "baseline_return": baseline_return,
        "top_return": safe_float(top_rows["fwd5_return"].mean()),
        "top_excess_return": safe_float(top_rows["fwd5_return"].mean()) - baseline_return,
        "top_hit_rate": safe_float(top_rows["label"].mean()),
        "top_limit_up_rate": safe_float(top_rows["hit_limit_up_5d"].mean()),
        "top_drawdown": safe_float(top_rows["max_drawdown_5d"].mean()),
        "rank_ic": safe_float(slices["rank_ic"].mean()) if not slices.empty else 0.0,
        "tiers": tier_metrics_list(pred, tier_set(int(args.top_k)), baseline_return),
        "folds": fold_metrics,
        "trading_validation": breakout_trading_validation(pred),
        "evaluation_quality": sample_quality_summary(
            data,
            pred,
            fold_metrics,
            universe_note="模型只评估横盘、启动、流动性达标候选池，不代表全市场无条件预测能力。",
            path_note="回踩买用逐日 high/low 判断触达；确认买按次日收盘确认后，从下一交易日开始计算持有收益；同日同时触发止盈/止损按先止损处理。",
        ),
        "test_start": str(pred["trade_date"].min()),
        "test_end": str(pred["trade_date"].max()),
        "top_k": int(args.top_k),
    }

    out_dir = Path(args.data_path) / "limit_breakout_model" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "latest_model.joblib"
    pred_path = out_dir / "predictions.parquet"
    out_pred.to_parquet(pred_path, index=False, compression="zstd")
    if models:
        joblib.dump(models[-1], model_path)
    write_results(args, overall, out_pred, slices, importance / max(len(models), 1), str(model_path))
    return overall


def write_results(args: argparse.Namespace, summary: dict[str, Any], pred: pd.DataFrame, slices: pd.DataFrame, importance: pd.Series, model_path: str) -> None:
    now = now_text()
    pred_cols = ["trade_date", "ts_code", "name", "industry", "prob", "model_score", "label", "fwd5_return", "fwd5_max_return", "max_drawdown_5d", "hit_limit_up_5d", "is_latest"]
    with write_transaction(args.db_path) as conn:
        conn.execute("DELETE FROM limit_breakout_model_features WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM limit_breakout_model_predictions WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM limit_breakout_model_tm_slices WHERE run_id = ?", (args.run_id,))
        conn.execute(
            replace_sql(
                "limit_breakout_model_runs",
                ["run_id", "start_date", "end_date", "horizon", "model_type", "feature_count", "status", "summary_json", "model_path", "created_at", "updated_at"],
                ["run_id"],
            ),
            (args.run_id, args.start, args.end, 5, "lgbm_limit_breakout", len(FEATURES), "success", json.dumps(summary, ensure_ascii=False), model_path, now, now),
        )
        conn.executemany(
            replace_sql("limit_breakout_model_features", ["run_id", "feature", "importance", "rank_no", "created_at", "updated_at"], ["run_id", "feature"]),
            [(args.run_id, str(feature), safe_float(value), int(rank), now, now) for rank, (feature, value) in enumerate(importance.sort_values(ascending=False).items(), 1)],
        )
        pred_sql = replace_sql(
            "limit_breakout_model_predictions",
            ["run_id", *pred_cols, "summary_json", "created_at", "updated_at"],
            ["run_id", "trade_date", "ts_code"],
        )
        rows = []
        for row in pred[pred_cols].itertuples(index=False):
            rows.append((
                args.run_id,
                str(row.trade_date), str(row.ts_code), str(row.name or ""), str(row.industry or ""),
                safe_float(row.prob), safe_float(row.model_score), int(row.label), safe_float(row.fwd5_return),
                safe_float(row.fwd5_max_return), safe_float(row.max_drawdown_5d), int(row.hit_limit_up_5d),
                int(row.is_latest or 0), "{}", now, now,
            ))
        conn.executemany(pred_sql, rows)
        conn.executemany(
            replace_sql(
                "limit_breakout_model_tm_slices",
                ["run_id", "trade_date", "candidate_count", "top_count", "avg_return", "avg_max_return", "hit_rate", "limit_up_hit_rate", "avg_drawdown", "rank_ic", "created_at", "updated_at"],
                ["run_id", "trade_date"],
            ),
            [
                (
                    args.run_id, str(row.trade_date), int(row.candidate_count), int(row.top_count),
                    safe_float(row.avg_return), safe_float(row.avg_max_return), safe_float(row.hit_rate),
                    safe_float(row.limit_up_hit_rate), safe_float(row.avg_drawdown), safe_float(row.rank_ic), now, now,
                )
                for row in slices.itertuples(index=False)
            ],
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--start", default="20150101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--min-train-years", type=int, default=4)
    parser.add_argument("--min-test-year", type=int, default=2020)
    parser.add_argument("--min-train-rows", type=int, default=2000)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        run_status.begin(TASK_NAME)
        run_status.progress(TASK_NAME, 1, 5, "load", "读取横盘启动训练数据")
        ensure_tables(args.db_path)
        raw = read_market_panel(Path(args.data_path), args.start, args.end)
        if raw.empty:
            raise RuntimeError("日线数据为空，无法训练横盘预警模型")
        run_status.progress(TASK_NAME, 2, 5, "features", "生成横盘、启动、行业和财务特征")
        data = add_features(raw, args.start, args.end, 5)
        if len(data) < int(args.min_train_rows):
            raise RuntimeError(f"候选样本不足: {len(data)}")
        run_status.progress(TASK_NAME, 3, 5, "train", "LightGBM walk-forward 训练")
        summary = train_model(args, data)
        run_status.progress(TASK_NAME, 5, 5, "done", "写入模型结果")
        run_status.done(TASK_NAME, f"横盘预警模型完成: Top{args.top_k}收益 {summary.get('top_return', 0):.2%}")
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
