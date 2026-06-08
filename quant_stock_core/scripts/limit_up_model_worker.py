from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
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


TASK_NAME = "limit_up_model"

FEATURES = [
    "pct_chg",
    "ret3",
    "ret5",
    "ret10",
    "ret20",
    "volatility20",
    "drawdown20",
    "distance_high20",
    "distance_high60",
    "turnover_rate",
    "volume_ratio",
    "amount_chg5",
    "amount_chg20",
    "circ_mv_log",
    "industry_ret1",
    "industry_ret3",
    "industry_ret5",
    "industry_ret20",
    "industry_up_ratio",
    "industry_limit_up_count",
    "industry_limit_up_ratio",
    "industry_amount_chg5",
    "industry_heat_score",
    "market_up_ratio",
    "market_limit_up_count",
    "market_limit_up_ratio",
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def limit_threshold(ts_code: str, name: str) -> float:
    upper_name = (name or "").upper()
    if "ST" in upper_name:
        return 4.5
    if ts_code.startswith("688") or ts_code.startswith("300"):
        return 19.0
    if ts_code.startswith("8") or ts_code.startswith("4") or ".BJ" in ts_code:
        return 28.0
    return 9.2


def ensure_tables(db_path: str | None) -> None:
    with write_transaction(db_path) as conn:
        if conn.backend == "mysql":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_up_model_runs (
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
                CREATE TABLE IF NOT EXISTS limit_up_model_features (
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
                CREATE TABLE IF NOT EXISTS limit_up_model_predictions (
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
                    KEY idx_limit_up_model_latest (run_id, is_latest, model_score),
                    KEY idx_limit_up_model_date (run_id, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS limit_up_model_tm_slices (
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
                CREATE TABLE IF NOT EXISTS limit_up_model_runs (
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
                CREATE TABLE IF NOT EXISTS limit_up_model_features (
                    run_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0,
                    rank_no INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, feature)
                );
                CREATE TABLE IF NOT EXISTS limit_up_model_predictions (
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
                CREATE TABLE IF NOT EXISTS limit_up_model_tm_slices (
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
    warmup = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=420)).strftime("%Y%m%d")
    con = duckdb.connect()
    try:
        return con.execute(
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
    finally:
        con.close()


def add_features(raw: pd.DataFrame, start: str, end: str, horizon: int) -> pd.DataFrame:
    df = raw.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    for col in ["open", "high", "low", "close", "pct_chg", "amount", "turnover_rate", "volume_ratio", "circ_mv"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    group = df.groupby("ts_code", sort=False)
    df["ret3"] = group["close"].pct_change(3)
    df["ret5"] = group["close"].pct_change(5)
    df["ret10"] = group["close"].pct_change(10)
    df["ret20"] = group["close"].pct_change(20)
    df["volatility20"] = group["pct_chg"].transform(lambda s: s.rolling(20, min_periods=8).std())
    high20 = group["high"].transform(lambda s: s.rolling(20, min_periods=5).max())
    high60 = group["high"].transform(lambda s: s.rolling(60, min_periods=20).max())
    df["drawdown20"] = df["close"] / high20.replace(0, np.nan) - 1
    df["distance_high20"] = df["close"] / high20.replace(0, np.nan) - 1
    df["distance_high60"] = df["close"] / high60.replace(0, np.nan) - 1
    amount5 = group["amount"].transform(lambda s: s.rolling(5, min_periods=2).mean())
    amount20 = group["amount"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    df["amount_chg5"] = df["amount"] / amount5.replace(0, np.nan) - 1
    df["amount_chg20"] = df["amount"] / amount20.replace(0, np.nan) - 1
    df["circ_mv_log"] = np.log1p(df["circ_mv"].clip(lower=0))
    df["is_limit_up"] = df.apply(lambda row: safe_float(row["pct_chg"]) >= limit_threshold(str(row["ts_code"]), str(row["name"])), axis=1)
    df["is_strong"] = (df["pct_chg"] >= 5.0) | df["is_limit_up"] | ((df["volume_ratio"] >= 1.8) & (df["pct_chg"] >= 3.0))

    by_industry = df.groupby(["trade_date", "industry"], sort=False)
    industry = by_industry.agg(
        industry_ret1=("pct_chg", "mean"),
        industry_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        industry_limit_up_count=("is_limit_up", "sum"),
        industry_count=("ts_code", "count"),
        industry_amount=("amount", "sum"),
    ).reset_index()
    industry = industry.sort_values(["industry", "trade_date"])
    industry_group = industry.groupby("industry", sort=False)
    industry["industry_ret3"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(3, min_periods=1).sum())
    industry["industry_ret5"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    industry["industry_ret20"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(20, min_periods=5).sum())
    industry_amount5 = industry_group["industry_amount"].transform(lambda s: s.rolling(5, min_periods=2).mean())
    industry["industry_amount_chg5"] = industry["industry_amount"] / industry_amount5.replace(0, np.nan) - 1
    industry["industry_limit_up_ratio"] = industry["industry_limit_up_count"] / industry["industry_count"].replace(0, np.nan)
    industry["industry_heat_score"] = (
        industry["industry_ret3"].rank(pct=True)
        + industry["industry_limit_up_count"].rank(pct=True)
        + industry["industry_up_ratio"].rank(pct=True)
        + industry["industry_amount_chg5"].replace([np.inf, -np.inf], np.nan).fillna(0).rank(pct=True)
    ) * 25.0

    market = df.groupby("trade_date", sort=False).agg(
        market_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        market_limit_up_count=("is_limit_up", "sum"),
        market_count=("ts_code", "count"),
    ).reset_index()
    market["market_limit_up_ratio"] = market["market_limit_up_count"] / market["market_count"].replace(0, np.nan)

    df = df.merge(industry.drop(columns=["industry_count", "industry_amount"]), on=["trade_date", "industry"], how="left")
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
    df["label"] = ((df["fwd5_max_return"] >= 0.08) & (df["max_drawdown_5d"] > -0.10)).astype(int)
    df["year"] = df["trade_date"].str.slice(0, 4).astype(int)
    df = df.replace([np.inf, -np.inf], np.nan)
    df[FEATURES] = df[FEATURES].fillna(0.0)
    tradable_mask = (
        df["is_strong"]
        & df["trade_date"].between(start, end)
        & (df["close"] >= 3.0)
        & (df["amount"] >= 30000)
        & (df["turnover_rate"] >= 0.4)
    )
    df = df[tradable_mask].reset_index(drop=True)
    return df


def metrics_for_top(group: pd.DataFrame, top_k: int) -> dict[str, float]:
    if group.empty:
        return {"top_count": 0, "avg_return": 0, "avg_max_return": 0, "hit_rate": 0, "limit_up_hit_rate": 0, "avg_drawdown": 0, "rank_ic": 0}
    top = group.sort_values("model_score", ascending=False).head(top_k)
    rank_ic = 0.0
    if group["model_score"].nunique() > 1 and group["fwd5_return"].nunique() > 1:
        rank_ic = safe_float(group["model_score"].corr(group["fwd5_return"], method="spearman"))
    return {
        "top_count": int(len(top)),
        "avg_return": safe_float(top["fwd5_return"].mean()),
        "avg_max_return": safe_float(top["fwd5_max_return"].mean()),
        "hit_rate": safe_float(top["label"].mean()),
        "limit_up_hit_rate": safe_float(top["hit_limit_up_5d"].mean()),
        "avg_drawdown": safe_float(top["max_drawdown_5d"].mean()),
        "rank_ic": rank_ic,
    }


def top_rows_by_date(frame: pd.DataFrame, top_k: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame.sort_values(["trade_date", "model_score"], ascending=[True, False]).groupby("trade_date", group_keys=False).head(int(top_k)).copy()


def tier_metrics(frame: pd.DataFrame, top_k: int, baseline_return: float | None = None) -> dict[str, Any]:
    if frame.empty:
        return {
            "top_k": int(top_k),
            "count": 0,
            "avg_return": 0.0,
            "excess_return": 0.0,
            "avg_max_return": 0.0,
            "hit_rate": 0.0,
            "limit_up_hit_rate": 0.0,
            "avg_drawdown": 0.0,
        }
    top = top_rows_by_date(frame, int(top_k))
    baseline = safe_float(frame["fwd5_return"].mean()) if baseline_return is None else safe_float(baseline_return)
    avg_return = safe_float(top["fwd5_return"].mean())
    return {
        "top_k": int(top_k),
        "count": int(len(top)),
        "avg_return": avg_return,
        "excess_return": avg_return - baseline,
        "avg_max_return": safe_float(top["fwd5_max_return"].mean()),
        "hit_rate": safe_float(top["label"].mean()),
        "limit_up_hit_rate": safe_float(top["hit_limit_up_5d"].mean()),
        "avg_drawdown": safe_float(top["max_drawdown_5d"].mean()),
    }


def tier_metrics_list(frame: pd.DataFrame, tiers: list[int], baseline_return: float | None = None) -> list[dict[str, Any]]:
    return [tier_metrics(frame, top_k, baseline_return) for top_k in tiers]


def sample_quality_summary(data: pd.DataFrame, pred: pd.DataFrame, fold_metrics: list[dict[str, Any]], *, universe_note: str, path_note: str) -> dict[str, Any]:
    years = sorted(int(year) for year in data["year"].dropna().unique()) if not data.empty and "year" in data else []
    fold_years = [int(item["year"]) for item in fold_metrics if "year" in item]
    return {
        "universe_note": universe_note,
        "path_assumption": path_note,
        "sample_rows": int(len(data)),
        "prediction_rows": int(len(pred)),
        "sample_years": years,
        "fold_years": fold_years,
        "fold_count": int(len(fold_metrics)),
        "missing_fold_years": [int(year) for year in years if year >= (min(fold_years) if fold_years else 9999) and year not in fold_years],
        "overall_positive_rate": safe_float(data["label"].mean()) if not data.empty and "label" in data else 0.0,
        "tested_positive_rate": safe_float(pred["label"].mean()) if not pred.empty and "label" in pred else 0.0,
        "min_fold_rows": int(min((int(item.get("rows", 0)) for item in fold_metrics), default=0)),
        "max_fold_rows": int(max((int(item.get("rows", 0)) for item in fold_metrics), default=0)),
    }


def simulate_trade_return(row: Any, hold_days: int, max_gap: float, take_profit: float, stop_loss: float, buy_slippage: float, sell_slippage: float, commission: float, stamp_tax: float) -> float | None:
    signal_close = safe_float(getattr(row, "close", 0))
    entry_open = safe_float(getattr(row, "entry_open_1d", 0))
    entry_gap = safe_float(getattr(row, "entry_gap_1d", 0))
    if signal_close <= 0 or entry_open <= 0:
        return None
    if entry_gap > max_gap:
        return None

    future_high = safe_float(getattr(row, f"future_high_{hold_days}d", 0))
    future_low = safe_float(getattr(row, f"future_low_{hold_days}d", 0))
    exit_close = safe_float(getattr(row, f"exit_close_{hold_days}d", 0))
    if future_high <= 0 or future_low <= 0 or exit_close <= 0:
        return None

    high_ret = future_high / entry_open - 1
    low_ret = future_low / entry_open - 1
    if low_ret <= stop_loss:
        gross = stop_loss
    elif high_ret >= take_profit:
        gross = take_profit
    else:
        gross = exit_close / entry_open - 1
    return (1 + gross) * (1 - sell_slippage - commission - stamp_tax) / (1 + buy_slippage + commission) - 1


def simulate_pullback_return(row: Any, hold_days: int, min_buy_premium: float, max_buy_premium: float, max_open_gap: float, take_profit: float, stop_loss: float, buy_slippage: float, sell_slippage: float, commission: float, stamp_tax: float) -> float | None:
    signal_close = safe_float(getattr(row, "close", 0))
    entry_open = safe_float(getattr(row, "entry_open_1d", 0))
    entry_gap = safe_float(getattr(row, "entry_gap_1d", 0))
    if signal_close <= 0 or entry_open <= 0:
        return None
    if entry_gap > max_open_gap:
        return None

    next_low = safe_float(getattr(row, "future_low_1d", 0))
    next_high = safe_float(getattr(row, "future_high_1d", 0))
    buy_price = signal_close * (1 + max_buy_premium)
    min_price = signal_close * (1 + min_buy_premium)
    if next_low <= 0 or next_high <= 0 or next_low > buy_price or next_high < min_price:
        return None
    buy_price = max(min_price, min(buy_price, next_high))

    future_high = safe_float(getattr(row, f"future_high_{hold_days}d", 0))
    future_low = safe_float(getattr(row, f"future_low_{hold_days}d", 0))
    exit_close = safe_float(getattr(row, f"exit_close_{hold_days}d", 0))
    if future_high <= 0 or future_low <= 0 or exit_close <= 0:
        return None

    high_ret = future_high / buy_price - 1
    low_ret = future_low / buy_price - 1
    if low_ret <= stop_loss:
        gross = stop_loss
    elif high_ret >= take_profit:
        gross = take_profit
    else:
        gross = exit_close / buy_price - 1
    return (1 + gross) * (1 - sell_slippage - commission - stamp_tax) / (1 + buy_slippage + commission) - 1


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


def trading_rule_metrics(pred: pd.DataFrame, top_n: int, hold_days: int, entry_mode: str = "open", max_gap: float = 0.07, take_profit: float = 0.10, stop_loss: float = -0.05, buy_slippage: float = 0.002, sell_slippage: float = 0.002, commission: float = 0.00025, stamp_tax: float = 0.0005, min_buy_premium: float = 0.0, max_buy_premium: float = 0.03) -> dict[str, Any]:
    signals = top_rows_by_date(pred, int(top_n))
    trade_returns: list[dict[str, Any]] = []
    for record in signals.to_dict("records"):
        row = SimpleNamespace(**record)
        if entry_mode == "pullback":
            ret = simulate_pullback_return(row, hold_days, min_buy_premium, max_buy_premium, max_gap, take_profit, stop_loss, buy_slippage, sell_slippage, commission, stamp_tax)
        else:
            ret = simulate_trade_return(row, hold_days, max_gap, take_profit, stop_loss, buy_slippage, sell_slippage, commission, stamp_tax)
        if ret is None:
            continue
        trade_returns.append({"trade_date": str(row.trade_date), "year": int(str(row.trade_date)[:4]), "return": safe_float(ret)})
    trades = pd.DataFrame(trade_returns)
    if trades.empty:
        return {
            "name": f"Top{top_n} / {'回落买' if entry_mode == 'pullback' else '开盘买'} / {hold_days}日",
            "entry_mode": entry_mode,
            "top_n": int(top_n),
            "hold_days": int(hold_days),
            "signal_count": int(len(signals)),
            "trade_count": 0,
            "fill_rate": 0.0,
            "avg_return": 0.0,
            "win_rate": 0.0,
            "compound_return": 0.0,
            "max_drawdown": 0.0,
            "yearly": [],
            "rule": {"entry_mode": entry_mode, "max_gap": max_gap, "take_profit": take_profit, "stop_loss": stop_loss, "buy_slippage": buy_slippage, "sell_slippage": sell_slippage, "commission": commission, "stamp_tax": stamp_tax, "min_buy_premium": min_buy_premium, "max_buy_premium": max_buy_premium, "path_assumption": "daily_ohlc_stop_first"},
        }
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
        "name": f"Top{top_n} / {'回落买' if entry_mode == 'pullback' else '开盘买'} / {hold_days}日",
        "entry_mode": entry_mode,
        "top_n": int(top_n),
        "hold_days": int(hold_days),
        "signal_count": int(len(signals)),
        "trade_count": int(len(trades)),
        "fill_rate": safe_float(len(trades) / max(len(signals), 1)),
        "avg_return": safe_float(trades["return"].mean()),
        "win_rate": safe_float((trades["return"] > 0).mean()),
        "compound_return": stats["compound_return"],
        "max_drawdown": stats["max_drawdown"],
        "yearly": yearly,
        "rule": {"entry_mode": entry_mode, "max_gap": max_gap, "take_profit": take_profit, "stop_loss": stop_loss, "buy_slippage": buy_slippage, "sell_slippage": sell_slippage, "commission": commission, "stamp_tax": stamp_tax, "min_buy_premium": min_buy_premium, "max_buy_premium": max_buy_premium, "path_assumption": "daily_ohlc_stop_first"},
    }


def trading_validation(pred: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        trading_rule_metrics(pred, top_n=3, hold_days=3, entry_mode="open"),
        trading_rule_metrics(pred, top_n=3, hold_days=5, entry_mode="open"),
        trading_rule_metrics(pred, top_n=5, hold_days=3, entry_mode="open"),
        trading_rule_metrics(pred, top_n=5, hold_days=5, entry_mode="open"),
        trading_rule_metrics(pred, top_n=3, hold_days=3, entry_mode="pullback", max_gap=0.05, take_profit=0.08, stop_loss=-0.04, min_buy_premium=0.0, max_buy_premium=0.03),
        trading_rule_metrics(pred, top_n=5, hold_days=3, entry_mode="pullback", max_gap=0.05, take_profit=0.08, stop_loss=-0.04, min_buy_premium=0.0, max_buy_premium=0.03),
    ]


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
            n_estimators=260,
            learning_rate=0.035,
            num_leaves=31,
            max_depth=5,
            min_child_samples=30,
            subsample=0.88,
            colsample_bytree=0.9,
            reg_alpha=0.05,
            reg_lambda=1.0,
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
        metric = {
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
            "tiers": tier_metrics_list(fold, [1, 3, 5, int(args.top_k)], fold_baseline),
        }
        fold_metrics.append(metric)
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
    tier_summary = tier_metrics_list(pred, [1, 3, 5, int(args.top_k)], baseline_return)
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
        "tiers": tier_summary,
        "folds": fold_metrics,
        "trading_validation": trading_validation(pred),
        "evaluation_quality": sample_quality_summary(
            data,
            pred,
            fold_metrics,
            universe_note="模型只评估强势、流动性达标、可交易候选池，不代表全市场无条件预测能力。",
            path_note="交易验证使用日线 OHLC，无法确认盘中止盈/止损先后；同日同时触发时按先止损处理。",
        ),
        "test_start": str(pred["trade_date"].min()),
        "test_end": str(pred["trade_date"].max()),
        "top_k": int(args.top_k),
    }

    out_dir = Path(args.data_path) / "limit_up_model" / args.run_id
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
        conn.execute("DELETE FROM limit_up_model_features WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM limit_up_model_predictions WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM limit_up_model_tm_slices WHERE run_id = ?", (args.run_id,))
        conn.execute(
            replace_sql(
                "limit_up_model_runs",
                ["run_id", "start_date", "end_date", "horizon", "model_type", "feature_count", "status", "summary_json", "model_path", "created_at", "updated_at"],
                ["run_id"],
            ),
            (args.run_id, args.start, args.end, 5, "lgbm_limit_up", len(FEATURES), "success", json.dumps(summary, ensure_ascii=False), model_path, now, now),
        )
        feat_sql = replace_sql("limit_up_model_features", ["run_id", "feature", "importance", "rank_no", "created_at", "updated_at"], ["run_id", "feature"])
        conn.executemany(
            feat_sql,
            [(args.run_id, str(feature), safe_float(value), int(rank), now, now) for rank, (feature, value) in enumerate(importance.sort_values(ascending=False).items(), 1)],
        )
        pred_sql = replace_sql(
            "limit_up_model_predictions",
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
        slice_sql = replace_sql(
            "limit_up_model_tm_slices",
            ["run_id", "trade_date", "candidate_count", "top_count", "avg_return", "avg_max_return", "hit_rate", "limit_up_hit_rate", "avg_drawdown", "rank_ic", "created_at", "updated_at"],
            ["run_id", "trade_date"],
        )
        conn.executemany(
            slice_sql,
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
    parser.add_argument("--min-test-year", type=int, default=2019)
    parser.add_argument("--min-train-rows", type=int, default=2000)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    try:
        run_status.begin(TASK_NAME)
        run_status.progress(TASK_NAME, 1, 5, "load", "读取日线和基础数据")
        ensure_tables(args.db_path)
        raw = read_market_panel(Path(args.data_path), args.start, args.end)
        if raw.empty:
            raise RuntimeError("日线数据为空，无法训练涨停模型")
        run_status.progress(TASK_NAME, 2, 5, "features", "生成热点与个股特征")
        data = add_features(raw, args.start, args.end, 5)
        if len(data) < int(args.min_train_rows):
            raise RuntimeError(f"候选样本不足: {len(data)}")
        run_status.progress(TASK_NAME, 3, 5, "train", "LightGBM walk-forward 训练")
        summary = train_model(args, data)
        run_status.progress(TASK_NAME, 5, 5, "done", "写入模型结果")
        run_status.done(TASK_NAME, f"涨停模型完成: Top{args.top_k}收益 {summary.get('top_return', 0):.2%}")
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
