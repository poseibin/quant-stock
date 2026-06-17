from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Sequence

import duckdb
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import add_column, replace_sql, table_columns, write_transaction
from common.utils.market import price_limit_pct_series, restricted_exclude_sql

try:
    from trading.execution.notifier import send_wechat
except Exception:
    send_wechat = None


TASK_NAME = "profit_arena_model"
PANEL_CACHE_VERSION = "profit_arena_panel_v7"
PROGRESS_FILE: Path | None = None

FEATURES = [
    "ret1",
    "ret3",
    "ret5",
    "ret10",
    "ret20",
    "ret60",
    "ret120",
    "open_to_close",
    "high_low_range",
    "gap_open",
    "limit_up_flag",
    "near_limit_up_flag",
    "limit_up_count5",
    "limit_up_count20",
    "limit_up_count10",
    "limit_up_yesterday",
    "near_limit_up_yesterday",
    "days_since_limit_up",
    "limit_up_density20",
    "near_limit_up_count5",
    "near_limit_up_count20",
    "near_limit_up_count10",
    "big_up_count5",
    "big_up_count10",
    "up_days5",
    "up_days10",
    "up_days20",
    "volatility5",
    "volatility10",
    "volatility20",
    "volatility60",
    "amount_chg3",
    "amount_chg5",
    "amount_chg20",
    "amount_chg60",
    "turnover_rate",
    "turnover_chg5",
    "volume_ratio",
    "ma5_bias",
    "ma10_bias",
    "ma20_bias",
    "ma60_bias",
    "ma120_bias",
    "distance_high20",
    "distance_high60",
    "distance_high120",
    "distance_low20",
    "distance_low60",
    "drawdown20",
    "drawdown60",
    "drawdown120",
    "close_position20",
    "close_position60",
    "breakout_high20",
    "breakout_high60",
    "momentum_accel5_20",
    "volume_price_burst5",
    "amount_breakout5",
    "amount_breakout20",
    "volatility_compress5_20",
    "amount_accel5_20",
    "turnover_accel5_20",
    "trend_quality20",
    "trend_quality60",
    "squeeze_breakout20",
    "pullback_strength20",
    "limit_momentum_quality20",
    "rs_market_accel5_20",
    "rs_industry_accel5_20",
    "industry_heat_accel5_20",
    "small_heat_accel5_20",
    "amplitude20",
    "amplitude60",
    "circ_mv_log",
    "total_mv_log",
    "size_pct_rank",
    "pb",
    "pe_ttm",
    "market_ret1",
    "market_ret5",
    "market_ret20",
    "market_up_ratio",
    "market_amount_chg5",
    "market_drawdown20",
    "market_volatility20",
    "rs_market5",
    "rs_market20",
    "small_ret1",
    "small_ret5",
    "small_ret20",
    "small_up_ratio",
    "small_limit_up_ratio",
    "small_near_limit_up_ratio",
    "small_big_up_ratio",
    "small_amount_chg5",
    "small_drawdown20",
    "small_volatility20",
    "small_breakout_high20_ratio",
    "small_breakout_high60_ratio",
    "small_high_position20_ratio",
    "small_rs_market5",
    "small_rs_market20",
    "industry_ret1",
    "industry_ret5",
    "industry_ret20",
    "industry_up_ratio",
    "industry_limit_up_ratio",
    "industry_near_limit_up_ratio",
    "industry_big_up_ratio",
    "industry_breakout_high20_ratio",
    "industry_high_position20_ratio",
    "industry_amount_chg5",
    "industry_rs_market5",
    "industry_rs_market20",
    "rs_industry5",
    "rs_industry20",
]

LEGACY53_FEATURES = [
    "ret1",
    "ret3",
    "ret5",
    "ret10",
    "ret20",
    "ret60",
    "ret120",
    "open_to_close",
    "high_low_range",
    "gap_open",
    "volatility5",
    "volatility10",
    "volatility20",
    "volatility60",
    "amount_chg3",
    "amount_chg5",
    "amount_chg20",
    "amount_chg60",
    "turnover_rate",
    "turnover_chg5",
    "volume_ratio",
    "ma5_bias",
    "ma10_bias",
    "ma20_bias",
    "ma60_bias",
    "ma120_bias",
    "distance_high20",
    "distance_high60",
    "distance_high120",
    "distance_low20",
    "distance_low60",
    "drawdown20",
    "drawdown60",
    "drawdown120",
    "amplitude20",
    "amplitude60",
    "circ_mv_log",
    "total_mv_log",
    "size_pct_rank",
    "pb",
    "pe_ttm",
    "market_ret1",
    "market_ret5",
    "market_ret20",
    "market_up_ratio",
    "market_amount_chg5",
    "market_drawdown20",
    "market_volatility20",
    "industry_ret1",
    "industry_ret5",
    "industry_ret20",
    "industry_up_ratio",
    "industry_amount_chg5",
]

ECOLOGY_FEATURES = {
    "small_ret1",
    "small_ret5",
    "small_ret20",
    "small_up_ratio",
    "small_limit_up_ratio",
    "small_near_limit_up_ratio",
    "small_big_up_ratio",
    "small_amount_chg5",
    "small_drawdown20",
    "small_volatility20",
    "small_breakout_high20_ratio",
    "small_breakout_high60_ratio",
    "small_high_position20_ratio",
    "small_rs_market5",
    "small_rs_market20",
}

V7_ADDED_FEATURES = {
    "amount_accel5_20",
    "industry_heat_accel5_20",
    "limit_momentum_quality20",
    "pullback_strength20",
    "rs_industry_accel5_20",
    "rs_market_accel5_20",
    "small_heat_accel5_20",
    "squeeze_breakout20",
    "trend_quality20",
    "trend_quality60",
    "turnover_accel5_20",
    "volatility_compress5_20",
}

V6ALL_FEATURES = [feature for feature in FEATURES if feature not in V7_ADDED_FEATURES]


def feature_columns_for_set(feature_set: str) -> list[str]:
    value = str(feature_set or "all").strip().lower()
    if value in {"v6all", "pre_v7", "champion_v100"}:
        return list(V6ALL_FEATURES)
    if value == "legacy53":
        return list(LEGACY53_FEATURES)
    if value == "core":
        return [feature for feature in FEATURES if feature not in ECOLOGY_FEATURES]
    if value == "ecology":
        return [feature for feature in FEATURES if feature in ECOLOGY_FEATURES]
    return list(FEATURES)


def progress_log(event: str, **payload: Any) -> None:
    record = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        **payload,
    }
    line = json.dumps(record, ensure_ascii=False, default=str)
    print(line, flush=True)
    if PROGRESS_FILE is not None:
        try:
            PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with PROGRESS_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass


def set_progress_file(path: Path) -> None:
    global PROGRESS_FILE
    PROGRESS_FILE = path
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text("", encoding="utf-8")


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


def threshold_key(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text.replace("-", "m").replace(".", "p")


def early_exit_column(kind: str, horizon: int, threshold: float) -> str:
    return f"{kind}_exit_date_{int(horizon)}d_{threshold_key(float(threshold))}"


def ensure_tables(db_path: str | None) -> None:
    with write_transaction(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profit_arena_runs (
                run_id VARCHAR(255) PRIMARY KEY,
                start_date VARCHAR(16) NOT NULL,
                end_date VARCHAR(16) NOT NULL,
                train_mode VARCHAR(64) NOT NULL,
                model_type VARCHAR(64) NOT NULL,
                feature_count BIGINT NOT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL,
                best_scope VARCHAR(32) NOT NULL DEFAULT '',
                best_horizon BIGINT NOT NULL DEFAULT 0,
                best_top_n BIGINT NOT NULL DEFAULT 0,
                best_compound_return DOUBLE NOT NULL DEFAULT 0,
                summary_json LONGTEXT,
                model_path VARCHAR(1024),
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profit_arena_features (
                run_id VARCHAR(255) NOT NULL,
                scope VARCHAR(32) NOT NULL,
                horizon BIGINT NOT NULL DEFAULT 0,
                feature VARCHAR(255) NOT NULL,
                importance DOUBLE NOT NULL DEFAULT 0,
                rank_no BIGINT NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(run_id, scope, horizon, feature)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profit_arena_evaluations (
                run_id VARCHAR(255) NOT NULL,
                scope VARCHAR(32) NOT NULL,
                horizon BIGINT NOT NULL DEFAULT 0,
                top_n BIGINT NOT NULL DEFAULT 0,
                min_pred_return DOUBLE NOT NULL DEFAULT -999,
                min_market_up_ratio DOUBLE NOT NULL DEFAULT -999,
                min_market_ret5 DOUBLE NOT NULL DEFAULT -999,
                min_market_ret20 DOUBLE NOT NULL DEFAULT -999,
                min_market_amount_chg5 DOUBLE NOT NULL DEFAULT -999,
                max_market_drawdown20 DOUBLE NOT NULL DEFAULT 999,
                max_market_volatility20 DOUBLE NOT NULL DEFAULT 999,
                min_industry_up_ratio DOUBLE NOT NULL DEFAULT -999,
                max_crash_prob DOUBLE NOT NULL DEFAULT 999,
                execution_stop_loss DOUBLE NOT NULL DEFAULT 0,
                execution_take_profit DOUBLE NOT NULL DEFAULT 0,
                position_weighting VARCHAR(32) NOT NULL DEFAULT 'equal',
                capital_scale_mode VARCHAR(32) NOT NULL DEFAULT 'none',
                segment VARCHAR(32) NOT NULL,
                trade_count BIGINT NOT NULL DEFAULT 0,
                trade_days BIGINT NOT NULL DEFAULT 0,
                avg_return DOUBLE NOT NULL DEFAULT 0,
                win_rate DOUBLE NOT NULL DEFAULT 0,
                compound_return DOUBLE NOT NULL DEFAULT 0,
                annual_return DOUBLE NOT NULL DEFAULT 0,
                max_drawdown DOUBLE NOT NULL DEFAULT 0,
                sharpe DOUBLE NOT NULL DEFAULT 0,
                capital_compound_return DOUBLE NOT NULL DEFAULT 0,
                capital_annual_return DOUBLE NOT NULL DEFAULT 0,
                capital_max_drawdown DOUBLE NOT NULL DEFAULT 0,
                capital_sharpe DOUBLE NOT NULL DEFAULT 0,
                capital_final_equity DOUBLE NOT NULL DEFAULT 1,
                capital_tranche_fraction DOUBLE NOT NULL DEFAULT 0,
                rank_ic DOUBLE NOT NULL DEFAULT 0,
                rank_ic_days BIGINT NOT NULL DEFAULT 0,
                summary_json LONGTEXT,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(run_id, scope, horizon, top_n, min_pred_return, min_market_up_ratio, min_market_ret5, min_market_ret20, min_market_amount_chg5, max_market_drawdown20, max_market_volatility20, min_industry_up_ratio, max_crash_prob, execution_stop_loss, execution_take_profit, position_weighting, capital_scale_mode, segment, capital_tranche_fraction)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        columns = table_columns(conn, "profit_arena_evaluations")
        if "min_pred_return" not in columns:
            add_column(conn, "profit_arena_evaluations", "min_pred_return", "DOUBLE NOT NULL DEFAULT -999")
        for column in ("min_market_up_ratio", "min_market_ret5", "min_market_ret20", "min_market_amount_chg5", "min_industry_up_ratio"):
            if column not in columns:
                add_column(conn, "profit_arena_evaluations", column, "DOUBLE NOT NULL DEFAULT -999")
        for column in ("max_market_drawdown20", "max_market_volatility20"):
            if column not in columns:
                add_column(conn, "profit_arena_evaluations", column, "DOUBLE NOT NULL DEFAULT 999")
        if "max_crash_prob" not in columns:
            add_column(conn, "profit_arena_evaluations", "max_crash_prob", "DOUBLE NOT NULL DEFAULT 999")
        for column in ("execution_stop_loss", "execution_take_profit"):
            if column not in columns:
                add_column(conn, "profit_arena_evaluations", column, "DOUBLE NOT NULL DEFAULT 0")
        if "position_weighting" not in columns:
            add_column(conn, "profit_arena_evaluations", "position_weighting", "VARCHAR(32) NOT NULL DEFAULT 'equal'")
        if "capital_scale_mode" not in columns:
            add_column(conn, "profit_arena_evaluations", "capital_scale_mode", "VARCHAR(32) NOT NULL DEFAULT 'none'")
        for column, definition in (
            ("capital_compound_return", "DOUBLE NOT NULL DEFAULT 0"),
            ("capital_annual_return", "DOUBLE NOT NULL DEFAULT 0"),
            ("capital_max_drawdown", "DOUBLE NOT NULL DEFAULT 0"),
            ("capital_sharpe", "DOUBLE NOT NULL DEFAULT 0"),
            ("capital_final_equity", "DOUBLE NOT NULL DEFAULT 1"),
            ("capital_tranche_fraction", "DOUBLE NOT NULL DEFAULT 0"),
            ("rank_ic", "DOUBLE NOT NULL DEFAULT 0"),
            ("rank_ic_days", "BIGINT NOT NULL DEFAULT 0"),
        ):
            if column not in columns:
                add_column(conn, "profit_arena_evaluations", column, definition)
        try:
            conn.execute(
                """
                ALTER TABLE profit_arena_evaluations
                DROP PRIMARY KEY,
                ADD PRIMARY KEY(run_id, scope, horizon, top_n, min_pred_return, min_market_up_ratio, min_market_ret5, min_market_ret20, min_market_amount_chg5, max_market_drawdown20, max_market_volatility20, min_industry_up_ratio, max_crash_prob, execution_stop_loss, execution_take_profit, position_weighting, capital_scale_mode, segment, capital_tranche_fraction)
                """
            )
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profit_arena_predictions (
                run_id VARCHAR(255) NOT NULL,
                scope VARCHAR(32) NOT NULL,
                horizon BIGINT NOT NULL DEFAULT 0,
                trade_date VARCHAR(16) NOT NULL,
                ts_code VARCHAR(32) NOT NULL,
                name VARCHAR(255) NOT NULL DEFAULT '',
                industry VARCHAR(255) NOT NULL DEFAULT '',
                size_bucket VARCHAR(32) NOT NULL DEFAULT '',
                price DOUBLE NOT NULL DEFAULT 0,
                pred_return DOUBLE NOT NULL DEFAULT 0,
                model_score DOUBLE NOT NULL DEFAULT 0,
                realized_return DOUBLE NOT NULL DEFAULT 0,
                future_return DOUBLE NOT NULL DEFAULT 0,
                future_max_return DOUBLE NOT NULL DEFAULT 0,
                future_drawdown DOUBLE NOT NULL DEFAULT 0,
                crash_prob DOUBLE NOT NULL DEFAULT 0,
                exit_date VARCHAR(16) NOT NULL DEFAULT '',
                is_latest BIGINT NOT NULL DEFAULT 0,
                summary_json LONGTEXT,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(run_id, scope, horizon, trade_date, ts_code),
                KEY idx_profit_arena_latest (run_id, scope, horizon, is_latest, model_score),
                KEY idx_profit_arena_date (run_id, scope, horizon, trade_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        columns = table_columns(conn, "profit_arena_predictions")
        if "exit_date" not in columns:
            add_column(conn, "profit_arena_predictions", "exit_date", "VARCHAR(16) NOT NULL DEFAULT ''")
        if "crash_prob" not in columns:
            add_column(conn, "profit_arena_predictions", "crash_prob", "DOUBLE NOT NULL DEFAULT 0")
        if "price" not in columns:
            add_column(conn, "profit_arena_predictions", "price", "DOUBLE NOT NULL DEFAULT 0")


def read_market_panel(data_path: Path, start: str, end: str, warmup_days: int) -> pd.DataFrame:
    raw = data_path / "raw"
    warmup = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=warmup_days)).strftime("%Y%m%d")
    con = duckdb.connect()
    try:
        frame = con.execute(
            f"""
            SELECT d.ts_code, d.trade_date,
                   d.open * COALESCE(a.adj_factor, 1) AS open,
                   d.high * COALESCE(a.adj_factor, 1) AS high,
                   d.low * COALESCE(a.adj_factor, 1) AS low,
                   d.close * COALESCE(a.adj_factor, 1) AS close,
                   d.pre_close * COALESCE(a.adj_factor, 1) AS pre_close,
                   d.close AS raw_close,
                   COALESCE(a.adj_factor, 1) AS adj_factor,
                   d.pct_chg, d.vol, d.amount,
                   COALESCE(b.turnover_rate, 0) AS turnover_rate,
                   COALESCE(b.volume_ratio, 0) AS volume_ratio,
                   COALESCE(b.total_mv, 0) AS total_mv,
                   COALESCE(b.circ_mv, 0) AS circ_mv,
                   COALESCE(b.pb, 0) AS pb,
                   COALESCE(b.pe_ttm, 0) AS pe_ttm,
                   COALESCE(s.name, '') AS name,
                   COALESCE(NULLIF(s.industry, ''), '未分类') AS industry,
                   COALESCE(s.exchange, '') AS exchange,
                   COALESCE(s.market, '') AS market,
                   COALESCE(s.list_date, '') AS list_date,
                   COALESCE(s.list_status, 'L') AS list_status
            FROM read_parquet('{raw / "daily" / "*.parquet"}') d
            LEFT JOIN read_parquet('{raw / "adj_factor" / "*.parquet"}') a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            LEFT JOIN read_parquet('{raw / "daily_basic" / "*.parquet"}') b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            LEFT JOIN read_parquet('{raw / "stock_basic" / "data.parquet"}') s
              ON d.ts_code = s.ts_code
            WHERE d.trade_date BETWEEN '{warmup}' AND '{end}'
              AND d.close IS NOT NULL
              AND d.close > 0
              AND d.pct_chg IS NOT NULL
              AND COALESCE(s.list_status, 'L') = 'L'
              AND COALESCE(s.name, '') NOT LIKE '%ST%'
              AND COALESCE(s.name, '') NOT LIKE '退市%'
              AND {restricted_exclude_sql('s')}
            ORDER BY d.ts_code, d.trade_date
            """
        ).fetch_df()
    finally:
        con.close()
    return frame


def assign_size_bucket(df: pd.DataFrame) -> pd.Series:
    rank = df.groupby("trade_date")["circ_mv"].rank(pct=True, method="first")
    return pd.cut(
        rank,
        bins=[0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0],
        labels=["small", "mid", "large"],
        include_lowest=True,
    ).astype(str)


def add_features(
    raw: pd.DataFrame,
    start: str,
    end: str,
    horizons: Sequence[int],
    buy_slippage: float,
    sell_slippage: float,
    commission: float,
    stamp_tax: float,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    execution_stop_losses: Sequence[float] = (),
    execution_take_profits: Sequence[float] = (),
) -> pd.DataFrame:
    df = raw.copy()
    df["trade_date"] = df["trade_date"].astype(str)
    numeric_cols = [
        "open", "high", "low", "close", "pre_close", "raw_close", "adj_factor", "pct_chg", "vol", "amount",
        "turnover_rate", "volume_ratio", "total_mv", "circ_mv", "pb", "pe_ttm",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    group = df.groupby("ts_code", sort=False)
    price_limit_pct = price_limit_pct_series(df)

    for window in (1, 3, 5, 10, 20, 60, 120):
        df[f"ret{window}"] = group["close"].pct_change(window)
    df["open_to_close"] = df["close"] / df["open"].replace(0, np.nan) - 1
    df["high_low_range"] = df["high"] / df["low"].replace(0, np.nan) - 1
    df["gap_open"] = df["open"] / group["close"].shift(1).replace(0, np.nan) - 1
    intraday_high_pct = (df["high"] / df["pre_close"].replace(0, np.nan) - 1) * 100.0
    df["limit_up_flag"] = (df["pct_chg"] >= price_limit_pct - 0.2).astype("float64")
    df["near_limit_up_flag"] = (intraday_high_pct >= price_limit_pct - 0.5).astype("float64")
    for window in (5, 10, 20):
        df[f"limit_up_count{window}"] = group["limit_up_flag"].transform(lambda s, w=window: s.rolling(w, min_periods=1).sum())
        df[f"near_limit_up_count{window}"] = group["near_limit_up_flag"].transform(lambda s, w=window: s.rolling(w, min_periods=1).sum())
    df["limit_up_yesterday"] = group["limit_up_flag"].shift(1).fillna(0.0)
    df["near_limit_up_yesterday"] = group["near_limit_up_flag"].shift(1).fillna(0.0)
    df["limit_up_density20"] = group["limit_up_flag"].transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum() / 20.0)
    df["days_since_limit_up"] = group["limit_up_flag"].transform(
        lambda s: pd.Series(
            np.arange(len(s)) - pd.Series(
                np.where(s.shift(1).fillna(0.0).eq(1.0), np.arange(len(s)), np.nan),
                index=s.index,
            ).ffill().to_numpy(),
            index=s.index,
        ).fillna(60.0).clip(lower=0.0, upper=60.0)
    )
    df["big_up_count5"] = group["pct_chg"].transform(lambda s: (s >= 5.0).astype("float64").rolling(5, min_periods=1).sum())
    df["big_up_count10"] = group["pct_chg"].transform(lambda s: (s >= 5.0).astype("float64").rolling(10, min_periods=1).sum())
    df["up_days5"] = group["pct_chg"].transform(lambda s: (s > 0.0).astype("float64").rolling(5, min_periods=1).sum())
    df["up_days10"] = group["pct_chg"].transform(lambda s: (s > 0.0).astype("float64").rolling(10, min_periods=1).sum())
    df["up_days20"] = group["pct_chg"].transform(lambda s: (s > 0.0).astype("float64").rolling(20, min_periods=1).sum())
    for window in (5, 10, 20, 60):
        df[f"volatility{window}"] = group["pct_chg"].transform(lambda s, w=window: s.rolling(w, min_periods=max(3, w // 3)).std())
    for window in (3, 5, 20, 60):
        avg_amount = group["amount"].transform(lambda s, w=window: s.rolling(w, min_periods=max(2, w // 3)).mean())
        df[f"amount_chg{window}"] = df["amount"] / avg_amount.replace(0, np.nan) - 1
    turnover5 = group["turnover_rate"].transform(lambda s: s.rolling(5, min_periods=2).mean())
    df["turnover_chg5"] = df["turnover_rate"] / turnover5.replace(0, np.nan) - 1
    for window in (5, 10, 20, 60, 120):
        ma = group["close"].transform(lambda s, w=window: s.rolling(w, min_periods=max(3, w // 3)).mean())
        df[f"ma{window}_bias"] = df["close"] / ma.replace(0, np.nan) - 1
    for window in (20, 60, 120):
        high = group["high"].transform(lambda s, w=window: s.rolling(w, min_periods=max(5, w // 3)).max())
        low = group["low"].transform(lambda s, w=window: s.rolling(w, min_periods=max(5, w // 3)).min())
        df[f"distance_high{window}"] = df["close"] / high.replace(0, np.nan) - 1
        df[f"distance_low{window}"] = df["close"] / low.replace(0, np.nan) - 1
        df[f"drawdown{window}"] = df[f"distance_high{window}"]
    high20 = group["high"].transform(lambda s: s.rolling(20, min_periods=8).max())
    low20 = group["low"].transform(lambda s: s.rolling(20, min_periods=8).min())
    high60 = group["high"].transform(lambda s: s.rolling(60, min_periods=20).max())
    low60 = group["low"].transform(lambda s: s.rolling(60, min_periods=20).min())
    df["amplitude20"] = high20 / low20.replace(0, np.nan) - 1
    df["amplitude60"] = high60 / low60.replace(0, np.nan) - 1
    df["close_position20"] = (df["close"] - low20) / (high20 - low20).replace(0, np.nan)
    df["close_position60"] = (df["close"] - low60) / (high60 - low60).replace(0, np.nan)
    prev_high20 = group["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=8).max())
    prev_high60 = group["high"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df["breakout_high20"] = (df["close"] > prev_high20).astype("float64")
    df["breakout_high60"] = (df["close"] > prev_high60).astype("float64")
    df["momentum_accel5_20"] = df["ret5"] - df["ret20"] / 4.0
    df["volume_price_burst5"] = df["ret5"] * df["amount_chg5"]
    df["amount_breakout5"] = (df["amount_chg5"] >= 0.5).astype("float64")
    df["amount_breakout20"] = (df["amount_chg20"] >= 1.0).astype("float64")
    df["volatility_compress5_20"] = df["volatility5"] / df["volatility20"].replace(0, np.nan) - 1
    df["amount_accel5_20"] = df["amount_chg5"] - df["amount_chg20"]
    turnover20 = group["turnover_rate"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    df["turnover_accel5_20"] = turnover5 / turnover20.replace(0, np.nan) - 1
    df["trend_quality20"] = df["ret20"] / df["volatility20"].replace(0, np.nan)
    df["trend_quality60"] = df["ret60"] / df["volatility60"].replace(0, np.nan)
    df["squeeze_breakout20"] = df["close_position20"] * df["amount_chg20"] / df["amplitude20"].replace(0, np.nan)
    df["pullback_strength20"] = df["ret20"] - df["drawdown20"].abs()
    df["limit_momentum_quality20"] = (df["limit_up_count20"] + 0.5 * df["near_limit_up_count20"]) / df["volatility20"].replace(0, np.nan)
    df["circ_mv_log"] = np.log1p(df["circ_mv"].clip(lower=0))
    df["total_mv_log"] = np.log1p(df["total_mv"].clip(lower=0))
    df["size_bucket"] = assign_size_bucket(df)
    df["size_pct_rank"] = df.groupby("trade_date")["circ_mv"].rank(pct=True, method="first")

    market = df.groupby("trade_date", sort=False).agg(
        market_ret1=("pct_chg", "mean"),
        market_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        market_amount=("amount", "sum"),
    ).reset_index().sort_values("trade_date")
    market["market_ret5"] = market["market_ret1"].rolling(5, min_periods=1).sum()
    market["market_ret20"] = market["market_ret1"].rolling(20, min_periods=5).sum()
    market["market_amount_chg5"] = market["market_amount"] / market["market_amount"].rolling(5, min_periods=2).mean().replace(0, np.nan) - 1
    market_equity = (1 + market["market_ret1"].fillna(0.0) / 100.0).cumprod()
    market_peak20 = market_equity.rolling(20, min_periods=5).max()
    market["market_drawdown20"] = market_equity / market_peak20.replace(0, np.nan) - 1
    market["market_volatility20"] = market["market_ret1"].rolling(20, min_periods=5).std() / 100.0

    small_source = df[df["size_bucket"] == "small"].copy()
    small = small_source.groupby("trade_date", sort=False).agg(
        small_ret1=("pct_chg", "mean"),
        small_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        small_limit_up_ratio=("limit_up_flag", "mean"),
        small_near_limit_up_ratio=("near_limit_up_flag", "mean"),
        small_big_up_ratio=("pct_chg", lambda s: float((s >= 5.0).mean())),
        small_amount=("amount", "sum"),
        small_breakout_high20_ratio=("breakout_high20", "mean"),
        small_breakout_high60_ratio=("breakout_high60", "mean"),
        small_high_position20_ratio=("close_position20", lambda s: float((s >= 0.8).mean())),
    ).reset_index().sort_values("trade_date")
    small["small_ret5"] = small["small_ret1"].rolling(5, min_periods=1).sum()
    small["small_ret20"] = small["small_ret1"].rolling(20, min_periods=5).sum()
    small["small_amount_chg5"] = small["small_amount"] / small["small_amount"].rolling(5, min_periods=2).mean().replace(0, np.nan) - 1
    small_equity = (1 + small["small_ret1"].fillna(0.0) / 100.0).cumprod()
    small_peak20 = small_equity.rolling(20, min_periods=5).max()
    small["small_drawdown20"] = small_equity / small_peak20.replace(0, np.nan) - 1
    small["small_volatility20"] = small["small_ret1"].rolling(20, min_periods=5).std() / 100.0

    industry = df.groupby(["trade_date", "industry"], sort=False).agg(
        industry_ret1=("pct_chg", "mean"),
        industry_up_ratio=("pct_chg", lambda s: float((s > 0).mean())),
        industry_limit_up_ratio=("limit_up_flag", "mean"),
        industry_near_limit_up_ratio=("near_limit_up_flag", "mean"),
        industry_big_up_ratio=("pct_chg", lambda s: float((s >= 5.0).mean())),
        industry_breakout_high20_ratio=("breakout_high20", "mean"),
        industry_high_position20_ratio=("close_position20", lambda s: float((s >= 0.8).mean())),
        industry_amount=("amount", "sum"),
    ).reset_index().sort_values(["industry", "trade_date"])
    industry_group = industry.groupby("industry", sort=False)
    industry["industry_ret5"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    industry["industry_ret20"] = industry_group["industry_ret1"].transform(lambda s: s.rolling(20, min_periods=5).sum())
    industry["industry_amount_chg5"] = industry_group["industry_amount"].transform(lambda s: s / s.rolling(5, min_periods=2).mean().replace(0, np.nan) - 1)
    df = df.merge(market.drop(columns=["market_amount"]), on="trade_date", how="left")
    df = df.merge(small.drop(columns=["small_amount"]), on="trade_date", how="left")
    df = df.merge(industry.drop(columns=["industry_amount"]), on=["trade_date", "industry"], how="left")
    relative_feature_cols = {
        "rs_market5": df["ret5"] - df["market_ret5"] / 100.0,
        "rs_market20": df["ret20"] - df["market_ret20"] / 100.0,
        "small_rs_market5": df["small_ret5"] / 100.0 - df["market_ret5"] / 100.0,
        "small_rs_market20": df["small_ret20"] / 100.0 - df["market_ret20"] / 100.0,
        "industry_rs_market5": df["industry_ret5"] / 100.0 - df["market_ret5"] / 100.0,
        "industry_rs_market20": df["industry_ret20"] / 100.0 - df["market_ret20"] / 100.0,
        "rs_industry5": df["ret5"] - df["industry_ret5"] / 100.0,
        "rs_industry20": df["ret20"] - df["industry_ret20"] / 100.0,
    }
    relative_feature_cols["rs_market_accel5_20"] = relative_feature_cols["rs_market5"] - relative_feature_cols["rs_market20"] / 4.0
    relative_feature_cols["rs_industry_accel5_20"] = relative_feature_cols["rs_industry5"] - relative_feature_cols["rs_industry20"] / 4.0
    relative_feature_cols["industry_heat_accel5_20"] = df["industry_ret5"] / 100.0 - df["industry_ret20"] / 400.0
    relative_feature_cols["small_heat_accel5_20"] = df["small_ret5"] / 100.0 - df["small_ret20"] / 400.0

    trade_dt = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    list_dt = pd.to_datetime(df.get("list_date", ""), format="%Y%m%d", errors="coerce")
    relative_feature_cols["listed_days"] = (trade_dt - list_dt).dt.days.fillna(9999).astype(int)
    df = pd.concat([df, pd.DataFrame(relative_feature_cols, index=df.index)], axis=1).copy()

    next_open = group["open"].shift(-1)
    next_pct = group["pct_chg"].shift(-1)
    can_buy_next_open = next_open.gt(0) & (next_pct < (price_limit_pct - 0.2))
    future_cols: dict[str, Any] = {}
    execution_stop_values = sorted({float(value) for value in execution_stop_losses if float(value) > 0})
    execution_take_values = sorted({float(value) for value in execution_take_profits if float(value) > 0})
    for horizon in sorted({int(h) for h in horizons if int(h) > 0}):
        exit_shift = horizon + 1
        exit_date = group["trade_date"].shift(-exit_shift)
        exit_close = group["close"].shift(-exit_shift)
        future_high = group["high"].transform(lambda s, h=exit_shift: s.shift(-1).iloc[::-1].rolling(h, min_periods=1).max().iloc[::-1])
        future_low = group["low"].transform(lambda s, h=exit_shift: s.shift(-1).iloc[::-1].rolling(h, min_periods=1).min().iloc[::-1])
        gross = exit_close / next_open.replace(0, np.nan) - 1
        net = (1 + gross) * (1 - sell_slippage - commission - stamp_tax) / (1 + buy_slippage + commission) - 1
        future_drawdown = future_low / next_open.replace(0, np.nan) - 1
        future_max_return = future_high / next_open.replace(0, np.nan) - 1
        if take_profit > 0:
            take_profit_net = (1 + float(take_profit)) * (1 - sell_slippage - commission - stamp_tax) / (1 + buy_slippage + commission) - 1
            net = np.where(future_max_return >= float(take_profit), take_profit_net, net)
        if stop_loss > 0:
            stop_net = (1 - float(stop_loss)) * (1 - sell_slippage - commission - stamp_tax) / (1 + buy_slippage + commission) - 1
            net = np.where(future_drawdown <= -float(stop_loss), stop_net, net)
        future_cols[f"exit_date_{horizon}d"] = exit_date
        future_cols[f"future_return_{horizon}d"] = gross
        future_cols[f"net_return_{horizon}d"] = np.where(can_buy_next_open, net, np.nan)
        future_cols[f"future_max_return_{horizon}d"] = future_max_return
        future_cols[f"future_drawdown_{horizon}d"] = future_drawdown
        for value in execution_take_values:
            col = early_exit_column("tp", horizon, value)
            hit_date = pd.Series("", index=df.index, dtype="object")
            for step in range(1, exit_shift + 1):
                step_high = group["high"].shift(-step)
                step_date = group["trade_date"].shift(-step).fillna("")
                hit = hit_date.eq("") & can_buy_next_open & ((step_high / next_open.replace(0, np.nan) - 1) >= value)
                hit_date = hit_date.mask(hit, step_date)
            future_cols[col] = hit_date
        for value in execution_stop_values:
            col = early_exit_column("sl", horizon, value)
            hit_date = pd.Series("", index=df.index, dtype="object")
            for step in range(1, exit_shift + 1):
                step_low = group["low"].shift(-step)
                step_date = group["trade_date"].shift(-step).fillna("")
                hit = hit_date.eq("") & can_buy_next_open & ((step_low / next_open.replace(0, np.nan) - 1) <= -value)
                hit_date = hit_date.mask(hit, step_date)
            future_cols[col] = hit_date
    if future_cols:
        df = pd.concat([df, pd.DataFrame(future_cols, index=df.index)], axis=1)

    numeric_for_cleanup = df.select_dtypes(include=[np.number]).columns
    df[numeric_for_cleanup] = df[numeric_for_cleanup].replace([np.inf, -np.inf], np.nan)
    df[FEATURES] = df[FEATURES].fillna(0.0)
    mask = (
        df["trade_date"].between(start, end)
        & (df["raw_close"] >= 2.5)
        & (df["amount"] >= 20000)
        & df["circ_mv"].gt(0)
        & (df["listed_days"] >= 120)
    )
    return df.loc[mask].reset_index(drop=True)


def equity_stats(daily_returns: pd.Series) -> dict[str, float]:
    if daily_returns.empty:
        return {"compound_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
    daily_returns = daily_returns.fillna(0.0).sort_index()
    equity = (1 + daily_returns).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak.replace(0, np.nan) - 1
    n_days = max(len(daily_returns), 1)
    compound = safe_float(equity.iloc[-1] - 1)
    annual = safe_float(equity.iloc[-1] ** (252.0 / n_days) - 1) if equity.iloc[-1] > 0 else -1.0
    sharpe = safe_float(daily_returns.mean() / daily_returns.std(ddof=0) * math.sqrt(252)) if daily_returns.std(ddof=0) > 0 else 0.0
    return {
        "compound_return": compound,
        "annual_return": annual,
        "max_drawdown": safe_float(drawdown.min()),
        "sharpe": sharpe,
    }


def capital_curve_stats(equity_by_date: pd.Series) -> dict[str, float]:
    if equity_by_date.empty:
        return {
            "capital_compound_return": 0.0,
            "capital_annual_return": 0.0,
            "capital_max_drawdown": 0.0,
            "capital_sharpe": 0.0,
            "capital_final_equity": 1.0,
        }
    equity = equity_by_date.astype(float).sort_index()
    peak = equity.cummax()
    drawdown = equity / peak.replace(0, np.nan) - 1
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    start_dt = pd.to_datetime(str(equity.index.min()), format="%Y%m%d", errors="coerce")
    end_dt = pd.to_datetime(str(equity.index.max()), format="%Y%m%d", errors="coerce")
    if pd.notna(start_dt) and pd.notna(end_dt):
        years = max((end_dt - start_dt).days / 365.25, 1.0 / 365.25)
    else:
        years = max(len(equity) / 252.0, 1.0 / 252.0)
    final_equity = safe_float(equity.iloc[-1], 1.0)
    return {
        "capital_compound_return": safe_float(final_equity - 1.0),
        "capital_annual_return": safe_float(final_equity ** (1.0 / years) - 1.0) if final_equity > 0 else -1.0,
        "capital_max_drawdown": safe_float(drawdown.min()),
        "capital_sharpe": safe_float(returns.mean() / returns.std(ddof=0) * math.sqrt(252)) if returns.std(ddof=0) > 0 else 0.0,
        "capital_final_equity": final_equity,
    }


def simulate_capital_curve(trades: pd.DataFrame, horizon: int, tranche_fraction: float = 0.0, all_dates: Sequence[str] | None = None) -> dict[str, float]:
    if trades.empty or "exit_date" not in trades.columns:
        return capital_curve_stats(pd.Series(dtype="float64"))
    current = trades.dropna(subset=["trade_date", "exit_date", "realized_return"]).copy()
    current["trade_date"] = current["trade_date"].astype(str)
    current["exit_date"] = current["exit_date"].astype(str)
    current = current[current["exit_date"].str.len() > 0]
    if current.empty:
        return capital_curve_stats(pd.Series(dtype="float64"))

    fraction = float(tranche_fraction)
    if fraction <= 0:
        fraction = 1.0 / max(int(horizon), 1)
    fraction = min(max(fraction, 0.0), 1.0)

    entries = {date: group.copy() for date, group in current.groupby("trade_date", sort=True)}
    event_dates = sorted(set(current["trade_date"]).union(set(current["exit_date"])))
    if all_dates is not None:
        event_dates = sorted(set(event_dates).union({str(date) for date in all_dates}))
    scheduled_exits: dict[str, list[float]] = {}
    equity = 1.0
    curve: dict[str, float] = {}
    for date in event_dates:
        exits = scheduled_exits.pop(date, [])
        if exits:
            equity = max(0.0, equity + float(np.sum(exits)))
        if date in entries and equity > 0:
            group = entries[date]
            per_trade_notional = equity * fraction / max(len(group), 1)
            for row in group.itertuples(index=False):
                pnl = per_trade_notional * safe_float(getattr(row, "realized_return", 0.0))
                exit_date = str(getattr(row, "exit_date", ""))
                scheduled_exits.setdefault(exit_date, []).append(pnl)
        curve[date] = equity
    return capital_curve_stats(pd.Series(curve, dtype="float64"))


def capital_scale_series(trades: pd.DataFrame, mode: str = "none") -> pd.Series:
    if trades.empty:
        return pd.Series(dtype="float64")
    mode = str(mode or "none").strip().lower()
    scale = pd.Series(1.0, index=trades.index, dtype="float64")
    if mode in {"none", "off", "full"}:
        return scale

    def col(name: str, default: float = 0.0) -> pd.Series:
        if name not in trades.columns:
            return pd.Series(default, index=trades.index, dtype="float64")
        return pd.to_numeric(trades[name], errors="coerce").fillna(default).astype(float)

    market_ret20 = col("market_ret20")
    market_drawdown20 = col("market_drawdown20")
    market_volatility20 = col("market_volatility20")
    market_scale = pd.Series(0.80, index=trades.index, dtype="float64")
    market_scale = market_scale.mask((market_ret20 < -5) | (market_drawdown20 <= -0.10) | (market_volatility20 > 0.025), 0.35)
    market_scale = market_scale.mask(((market_ret20 < 0) | (market_drawdown20 <= -0.08)) & (market_scale > 0.35), 0.55)
    market_scale = market_scale.mask((market_ret20 > 5) & (market_drawdown20 > -0.05) & (market_volatility20 <= 0.025), 1.0)
    market_soft = pd.Series(0.90, index=trades.index, dtype="float64")
    market_soft = market_soft.mask((market_ret20 < -5) | (market_drawdown20 <= -0.10) | (market_volatility20 > 0.028), 0.45)
    market_soft = market_soft.mask(((market_ret20 < 0) | (market_drawdown20 <= -0.08)) & (market_soft > 0.45), 0.65)
    market_soft = market_soft.mask((market_ret20 > 4) & (market_drawdown20 > -0.06) & (market_volatility20 <= 0.030), 1.0)
    market_guarded = pd.Series(0.72, index=trades.index, dtype="float64")
    market_guarded = market_guarded.mask((market_ret20 < -4) | (market_drawdown20 <= -0.09) | (market_volatility20 > 0.024), 0.15)
    market_guarded = market_guarded.mask(((market_ret20 < 1) | (market_drawdown20 <= -0.06)) & (market_guarded > 0.15), 0.45)
    market_guarded = market_guarded.mask((market_ret20 > 6) & (market_drawdown20 > -0.04) & (market_volatility20 <= 0.024), 1.0)
    market_pulse = pd.Series(0.65, index=trades.index, dtype="float64")
    market_pulse = market_pulse.mask((market_ret20 < -3) | (market_drawdown20 <= -0.08) | (market_volatility20 > 0.026), 0.20)
    market_pulse = market_pulse.mask(((market_ret20 >= 0) & (market_ret20 <= 4) & (market_drawdown20 > -0.08)), 0.75)
    market_pulse = market_pulse.mask((market_ret20 > 4) & (market_drawdown20 > -0.06) & (market_volatility20 <= 0.028), 1.0)
    market_brake = pd.Series(0.72, index=trades.index, dtype="float64")
    market_brake = market_brake.mask((market_ret20 < -4) | (market_drawdown20 <= -0.11) | (market_volatility20 > 0.030), 0.05)
    market_brake = market_brake.mask(((market_ret20 < -1) | (market_drawdown20 <= -0.075) | (market_volatility20 > 0.026)) & (market_brake > 0.05), 0.32)
    market_brake = market_brake.mask(((market_ret20 >= -1) & (market_ret20 <= 4) & (market_drawdown20 > -0.075)) & (market_brake > 0.32), 0.58)
    market_brake = market_brake.mask((market_ret20 > 4) & (market_drawdown20 > -0.05) & (market_volatility20 <= 0.026), 1.0)
    market_tail_guard = pd.Series(0.85, index=trades.index, dtype="float64")
    tail_risk = ((market_ret20 < -2) & (market_drawdown20 <= -0.10)) | (market_volatility20 > 0.034)
    market_tail_guard = market_tail_guard.mask(tail_risk, 0.18)
    market_tail_guard = market_tail_guard.mask(((market_ret20 < 0) | (market_drawdown20 <= -0.08) | (market_volatility20 > 0.028)) & (~tail_risk), 0.55)
    market_tail_guard = market_tail_guard.mask((market_ret20 > 4) & (market_drawdown20 > -0.05) & (market_volatility20 <= 0.028), 1.0)

    small_up_ratio = col("small_up_ratio", 0.5)
    small_rs_market20 = col("small_rs_market20")
    small_ret20 = col("small_ret20")
    small_drawdown20 = col("small_drawdown20")
    small_limit_up_ratio = col("small_limit_up_ratio")
    small_breakout_high20_ratio = col("small_breakout_high20_ratio")
    small_scale = pd.Series(0.85, index=trades.index, dtype="float64")
    small_scale = small_scale.mask((small_up_ratio < 0.42) | (small_rs_market20 < -0.03), 0.40)
    small_scale = small_scale.mask(((small_up_ratio < 0.48) | (small_rs_market20 < 0.0)) & (small_scale > 0.40), 0.65)
    small_scale = small_scale.mask((small_up_ratio > 0.52) & ((small_limit_up_ratio > 0.018) | (small_breakout_high20_ratio > 0.06)), 1.0)
    small_brake = pd.Series(0.70, index=trades.index, dtype="float64")
    small_brake = small_brake.mask((small_up_ratio < 0.40) | (small_rs_market20 < -0.04), 0.05)
    small_brake = small_brake.mask(((small_up_ratio < 0.47) | (small_rs_market20 < -0.01)) & (small_brake > 0.05), 0.35)
    small_brake = small_brake.mask(((small_up_ratio >= 0.47) & (small_up_ratio <= 0.54) & (small_rs_market20 >= -0.01)) & (small_brake > 0.35), 0.65)
    small_brake = small_brake.mask((small_up_ratio > 0.54) & (small_rs_market20 > 0.0) & ((small_limit_up_ratio > 0.018) | (small_breakout_high20_ratio > 0.06)), 1.0)
    small_tail_guard = pd.Series(0.88, index=trades.index, dtype="float64")
    small_tail_risk = (small_up_ratio < 0.40) & (small_rs_market20 < -0.03)
    small_tail_guard = small_tail_guard.mask(small_tail_risk, 0.20)
    small_tail_guard = small_tail_guard.mask(((small_up_ratio < 0.47) | (small_rs_market20 < -0.01)) & (~small_tail_risk), 0.58)
    small_tail_guard = small_tail_guard.mask((small_up_ratio > 0.53) & (small_rs_market20 > 0.0) & ((small_limit_up_ratio > 0.018) | (small_breakout_high20_ratio > 0.06)), 1.0)
    pred_return = col("pred_return")
    crash_prob = col("crash_prob")
    breakout_prob = col("breakout_prob")
    signal_quality = pd.Series(0.65, index=trades.index, dtype="float64")
    signal_quality = signal_quality.mask((pred_return >= 0.08) & (crash_prob <= 0.12), 0.82)
    signal_quality = signal_quality.mask((pred_return >= 0.10) & (breakout_prob >= 0.30) & (crash_prob <= 0.10), 1.0)
    signal_quality = signal_quality.mask((pred_return < 0.06) | (crash_prob > 0.18), 0.35)
    signal_quality = signal_quality.mask(crash_prob > 0.30, 0.15)
    light_tail_guard = pd.Series(1.0, index=trades.index, dtype="float64")
    light_hard_tail = (
        ((market_drawdown20 <= -0.11) | (market_volatility20 > 0.034))
        & ((small_up_ratio < 0.45) | (small_rs_market20 < -0.02))
    )
    light_soft_tail = (
        ((market_ret20 < -1) | (market_drawdown20 <= -0.085) | (small_rs_market20 < -0.015))
        & (~light_hard_tail)
    )
    light_tail_guard = light_tail_guard.mask(light_hard_tail, 0.45)
    light_tail_guard = light_tail_guard.mask(light_soft_tail, 0.78)
    light_signal_guard = light_tail_guard.copy()
    light_signal_guard = light_signal_guard.mask((pred_return < 0.06) & (crash_prob > 0.10), np.minimum(light_signal_guard.to_numpy(dtype="float64"), 0.70))
    light_signal_guard = light_signal_guard.mask((pred_return >= 0.10) & (breakout_prob >= 0.25) & (crash_prob <= 0.10), 1.0)
    overheat = ((market_ret20 >= 14) | (small_ret20 >= 18)) & (market_drawdown20 > -0.12) & (small_drawdown20 > -0.12)
    late_overheat = ((market_ret20 >= 10) & (small_ret20 >= 12) & ((market_drawdown20 <= -0.02) | (small_drawdown20 <= -0.02)))
    overheat_soft = pd.Series(1.0, index=trades.index, dtype="float64")
    overheat_soft = overheat_soft.mask(overheat, 0.78)
    overheat_soft = overheat_soft.mask(late_overheat, np.minimum(overheat_soft.to_numpy(dtype="float64"), 0.70))
    overheat_guard = pd.Series(1.0, index=trades.index, dtype="float64")
    overheat_guard = overheat_guard.mask(overheat, 0.62)
    overheat_guard = overheat_guard.mask(late_overheat, np.minimum(overheat_guard.to_numpy(dtype="float64"), 0.50))
    overheat_signal_guard = overheat_soft.copy()
    overheat_signal_guard = overheat_signal_guard.mask(overheat & (crash_prob >= 0.10), np.minimum(overheat_signal_guard.to_numpy(dtype="float64"), 0.48))
    overheat_signal_guard = overheat_signal_guard.mask(late_overheat & (crash_prob >= 0.09), np.minimum(overheat_signal_guard.to_numpy(dtype="float64"), 0.40))
    overheat_signal_guard = overheat_signal_guard.mask(overheat & (pred_return >= 0.16) & (breakout_prob >= 0.30) & (crash_prob <= 0.085), 0.90)

    if mode == "market":
        scale = market_scale
    elif mode == "market_soft":
        scale = market_soft
    elif mode == "market_guarded":
        scale = market_guarded
    elif mode == "market_pulse":
        scale = market_pulse
    elif mode == "market_brake":
        scale = market_brake
    elif mode == "market_tail_guard":
        scale = market_tail_guard
    elif mode == "small_ecology":
        scale = small_scale
    elif mode == "small_brake":
        scale = small_brake
    elif mode == "small_tail_guard":
        scale = small_tail_guard
    elif mode == "signal_quality":
        scale = signal_quality
    elif mode == "light_tail_guard":
        scale = light_tail_guard
    elif mode == "light_signal_guard":
        scale = light_signal_guard
    elif mode == "overheat_soft":
        scale = overheat_soft
    elif mode == "overheat_guard":
        scale = overheat_guard
    elif mode == "overheat_signal_guard":
        scale = overheat_signal_guard
    elif mode == "signal_tail_guard":
        base = np.minimum(signal_quality.to_numpy(dtype="float64"), small_tail_guard.to_numpy(dtype="float64"))
        scale = pd.Series(base, index=trades.index, dtype="float64")
        hard_tail = ((market_drawdown20 <= -0.10) | (market_volatility20 > 0.032) | (small_up_ratio < 0.42)) & (crash_prob > 0.10)
        scale = scale.mask(hard_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.25))
    elif mode == "attack_signal_guard":
        base = np.maximum(signal_quality.to_numpy(dtype="float64"), small_tail_guard.to_numpy(dtype="float64"))
        scale = pd.Series(base, index=trades.index, dtype="float64")
        hard_tail = ((market_drawdown20 <= -0.11) | (market_volatility20 > 0.034) | (small_up_ratio < 0.40)) & (crash_prob > 0.12)
        soft_tail = ((market_ret20 < -1) | (small_rs_market20 < -0.02)) & (crash_prob > 0.12) & (~hard_tail)
        scale = scale.mask(hard_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.35))
        scale = scale.mask(soft_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.65))
    elif mode == "hybrid_ecology":
        scale = np.minimum(market_scale.to_numpy(dtype="float64"), small_scale.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    elif mode == "hybrid_brake":
        scale = np.minimum(market_brake.to_numpy(dtype="float64"), small_brake.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    elif mode == "attack_brake":
        scale = np.maximum(market_brake.to_numpy(dtype="float64"), small_brake.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    elif mode == "hybrid_tail_guard":
        scale = np.minimum(market_tail_guard.to_numpy(dtype="float64"), small_tail_guard.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    elif mode == "hybrid_tail_guard_plus":
        base = np.minimum(market_tail_guard.to_numpy(dtype="float64"), small_tail_guard.to_numpy(dtype="float64"))
        scale = pd.Series(base, index=trades.index, dtype="float64")
        hard_tail = ((market_drawdown20 <= -0.10) | (market_volatility20 > 0.032)) & ((small_up_ratio < 0.45) | (small_rs_market20 < -0.015))
        soft_tail = ((market_ret20 < 0) | (market_drawdown20 <= -0.08) | (small_up_ratio < 0.47) | (small_rs_market20 < -0.01)) & (~hard_tail)
        scale = scale.mask(hard_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.18))
        scale = scale.mask(soft_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.52))
        pulse = (market_ret20 > 4) & (market_drawdown20 > -0.05) & (small_up_ratio > 0.53) & (small_rs_market20 > 0.0)
        scale = scale.mask(pulse, np.maximum(scale.to_numpy(dtype="float64"), 0.92))
    elif mode == "attack_tail_guard":
        scale = np.maximum(market_tail_guard.to_numpy(dtype="float64"), small_tail_guard.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    elif mode == "attack_tail_guard_plus":
        base = np.maximum(market_tail_guard.to_numpy(dtype="float64"), small_tail_guard.to_numpy(dtype="float64"))
        scale = pd.Series(base, index=trades.index, dtype="float64")
        hard_tail = ((market_drawdown20 <= -0.11) | (market_volatility20 > 0.034)) & ((small_up_ratio < 0.43) | (small_rs_market20 < -0.025))
        soft_tail = ((market_ret20 < -1) | (market_drawdown20 <= -0.085) | (small_up_ratio < 0.46) | (small_rs_market20 < -0.015)) & (~hard_tail)
        scale = scale.mask(hard_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.25))
        scale = scale.mask(soft_tail, np.minimum(scale.to_numpy(dtype="float64"), 0.62))
        pulse = (market_ret20 > 4) & (market_drawdown20 > -0.055) & (small_up_ratio > 0.52) & ((small_limit_up_ratio > 0.018) | (small_breakout_high20_ratio > 0.06))
        scale = scale.mask(pulse, 1.0)
    elif mode == "attack_ecology":
        scale = np.maximum(market_scale.to_numpy(dtype="float64"), small_scale.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    elif mode == "risk_off_market":
        scale = pd.Series(0.60, index=trades.index, dtype="float64")
        scale = scale.mask((market_ret20 < -5) | (market_drawdown20 <= -0.10) | (market_volatility20 > 0.025), 0.0)
        scale = scale.mask(((market_ret20 < 0) | (market_drawdown20 <= -0.08)) & (scale > 0.0), 0.25)
        scale = scale.mask((market_ret20 > 5) & (market_drawdown20 > -0.05) & (market_volatility20 <= 0.025), 1.0)
    elif mode == "risk_off_hybrid":
        market_risk_off = pd.Series(0.60, index=trades.index, dtype="float64")
        market_risk_off = market_risk_off.mask((market_ret20 < -5) | (market_drawdown20 <= -0.10) | (market_volatility20 > 0.025), 0.0)
        market_risk_off = market_risk_off.mask(((market_ret20 < 0) | (market_drawdown20 <= -0.08)) & (market_risk_off > 0.0), 0.25)
        market_risk_off = market_risk_off.mask((market_ret20 > 5) & (market_drawdown20 > -0.05) & (market_volatility20 <= 0.025), 1.0)
        small_risk_off = pd.Series(0.70, index=trades.index, dtype="float64")
        small_risk_off = small_risk_off.mask((small_up_ratio < 0.40) | (small_rs_market20 < -0.04), 0.0)
        small_risk_off = small_risk_off.mask(((small_up_ratio < 0.47) | (small_rs_market20 < -0.01)) & (small_risk_off > 0.0), 0.30)
        small_risk_off = small_risk_off.mask((small_up_ratio > 0.53) & ((small_limit_up_ratio > 0.018) | (small_breakout_high20_ratio > 0.06)), 1.0)
        scale = np.minimum(market_risk_off.to_numpy(dtype="float64"), small_risk_off.to_numpy(dtype="float64"))
        scale = pd.Series(scale, index=trades.index, dtype="float64")
    return scale.clip(lower=0.0, upper=1.0).fillna(1.0)


def simulate_capital_curves_many(
    trades: pd.DataFrame,
    horizon: int,
    tranche_fractions: Sequence[float],
    all_dates: Sequence[str] | None = None,
    max_gross_exposure: float = 1.0,
) -> list[dict[str, float]]:
    fractions = [float(value) for value in tranche_fractions] or [0.0]
    normalized = []
    for value in fractions:
        fraction = value if value > 0 else 1.0 / max(int(horizon), 1)
        normalized.append(min(max(float(fraction), 0.0), 1.0))
    if trades.empty or "exit_date" not in trades.columns:
        empty = capital_curve_stats(pd.Series(dtype="float64"))
        return [empty.copy() for _ in normalized]

    current = trades.dropna(subset=["trade_date", "exit_date", "realized_return"]).copy()
    current["trade_date"] = current["trade_date"].astype(str)
    current["exit_date"] = current["exit_date"].astype(str)
    current = current[current["exit_date"].str.len() > 0]
    if current.empty:
        empty = capital_curve_stats(pd.Series(dtype="float64"))
        return [empty.copy() for _ in normalized]

    fraction_arr = np.array(normalized, dtype="float64")
    equity = np.ones(len(fraction_arr), dtype="float64")
    active_notional = np.zeros(len(fraction_arr), dtype="float64")
    max_exposure = max(float(max_gross_exposure or 1.0), 0.0)
    if "position_weight" not in current.columns:
        current["position_weight"] = current.groupby("trade_date")["trade_date"].transform(lambda s: 1.0 / max(len(s), 1))
    current["position_weight"] = pd.to_numeric(current["position_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if "capital_scale" not in current.columns:
        current["capital_scale"] = 1.0
    current["capital_scale"] = pd.to_numeric(current["capital_scale"], errors="coerce").fillna(1.0).clip(lower=0.0, upper=1.0)
    weight_sum = current.groupby("trade_date")["position_weight"].transform("sum").replace(0, np.nan)
    current["position_weight"] = (current["position_weight"] / weight_sum).fillna(0.0)
    entries = {date: group[["exit_date", "realized_return", "position_weight", "capital_scale"]].copy() for date, group in current.groupby("trade_date", sort=True)}
    event_dates = sorted(set(current["trade_date"]).union(set(current["exit_date"])))
    if all_dates is not None:
        event_dates = sorted(set(event_dates).union({str(date) for date in all_dates}))
    scheduled_exits: dict[str, list[np.ndarray]] = {}
    curves = [[] for _ in normalized]
    curve_dates: list[str] = []
    for date in event_dates:
        exits = scheduled_exits.pop(date, [])
        if exits:
            exit_frame = np.stack(exits)
            active_notional = np.maximum(0.0, active_notional - exit_frame[:, 0, :].sum(axis=0))
            equity = np.maximum(0.0, equity + exit_frame[:, 1, :].sum(axis=0))
        if date in entries and np.any(equity > 0):
            group = entries[date]
            entry_scale = safe_float(group["capital_scale"].median(), 1.0)
            target_notional = equity * fraction_arr * min(max(entry_scale, 0.0), 1.0)
            capacity = np.maximum(0.0, equity * max_exposure - active_notional)
            total_notional = np.minimum(target_notional, capacity)
            active_notional += total_notional
            for row in group.itertuples(index=False):
                base_notional = total_notional * safe_float(getattr(row, "position_weight", 0.0))
                pnl = base_notional * safe_float(getattr(row, "realized_return", 0.0))
                scheduled_exits.setdefault(str(getattr(row, "exit_date", "")), []).append(np.stack([base_notional, pnl]))
        curve_dates.append(date)
        for idx, value in enumerate(equity):
            curves[idx].append(float(value))
    return [
        capital_curve_stats(pd.Series(values, index=curve_dates, dtype="float64"))
        for values in curves
    ]


def apply_execution_rules(trades: pd.DataFrame, horizon: int, execution_stop_loss: float = 0.0, execution_take_profit: float = 0.0) -> pd.DataFrame:
    if trades.empty:
        return trades
    current = trades.copy()
    realized = current["realized_return"].astype(float).copy()
    take_profit = float(execution_take_profit or 0.0)
    stop_loss = float(execution_stop_loss or 0.0)
    exit_date = current["exit_date"].astype(str).copy() if "exit_date" in current.columns else pd.Series("", index=current.index, dtype="object")
    if take_profit > 0 and "future_max_return" in current.columns:
        tp_hit = current["future_max_return"].astype(float) >= take_profit
        realized = realized.mask(tp_hit, take_profit)
        tp_col = early_exit_column("tp", horizon, take_profit)
        if tp_col in current.columns:
            tp_date = current[tp_col].fillna("").astype(str)
            exit_date = exit_date.mask(tp_hit & tp_date.str.len().gt(0), tp_date)
    if stop_loss > 0 and "future_drawdown" in current.columns:
        sl_hit = current["future_drawdown"].astype(float) <= -stop_loss
        sl_col = early_exit_column("sl", horizon, stop_loss)
        if sl_col in current.columns:
            sl_date = current[sl_col].fillna("").astype(str)
            current_exit_dt = pd.to_datetime(exit_date, format="%Y%m%d", errors="coerce")
            sl_dt = pd.to_datetime(sl_date, format="%Y%m%d", errors="coerce")
            use_sl = sl_hit & sl_date.str.len().gt(0) & (current_exit_dt.isna() | sl_dt.le(current_exit_dt))
            realized = realized.mask(use_sl, -stop_loss)
            exit_date = exit_date.mask(use_sl, sl_date)
        else:
            realized = realized.mask(sl_hit, -stop_loss)
    current["realized_return"] = realized
    current["exit_date"] = exit_date
    return current


def capped_position_weights(weights: pd.Series, cap: float) -> pd.Series:
    values = weights.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0).to_numpy(dtype="float64")
    n = len(values)
    if n == 0:
        return weights.astype(float)
    if values.sum() <= 0:
        values = np.full(n, 1.0 / n, dtype="float64")
    else:
        values = values / values.sum()
    cap = max(float(cap or 0.0), 1.0 / n)
    cap = min(cap, 1.0)
    out = np.zeros(n, dtype="float64")
    remaining = np.ones(n, dtype=bool)
    remaining_mass = 1.0
    for _ in range(n + 1):
        idx = np.flatnonzero(remaining)
        if len(idx) == 0:
            break
        base_sum = values[idx].sum()
        if base_sum <= 0:
            trial = np.full(len(idx), remaining_mass / len(idx), dtype="float64")
        else:
            trial = values[idx] / base_sum * remaining_mass
        over = trial > cap + 1e-12
        if not over.any():
            out[idx] = trial
            break
        over_idx = idx[over]
        out[over_idx] = cap
        remaining[over_idx] = False
        remaining_mass = max(0.0, 1.0 - out[~remaining].sum())
    total = out.sum()
    if total <= 0:
        out = np.full(n, 1.0 / n, dtype="float64")
    elif abs(total - 1.0) > 1e-9:
        out = out / total
    return pd.Series(out, index=weights.index, dtype="float64")


def apply_position_weighting(trades: pd.DataFrame, mode: str = "equal") -> pd.DataFrame:
    if trades.empty:
        return trades
    current = trades.copy()
    mode = str(mode or "equal").strip().lower()
    cap_by_mode = {
        "score_cap50": 0.50,
        "score_cap40": 0.40,
        "score_cap34": 0.34,
        "pred_cap50": 0.50,
        "pred_cap40": 0.40,
        "breakout_cap50": 0.50,
    }
    base_mode = mode
    cap = cap_by_mode.get(mode)
    if cap is not None:
        if mode.startswith("score"):
            base_mode = "score"
        elif mode.startswith("pred"):
            base_mode = "pred"
        elif mode.startswith("breakout"):
            base_mode = "breakout"
    if base_mode == "breakout" and "breakout_prob" in current.columns:
        raw = current["breakout_prob"].astype(float).clip(lower=0.0)
    elif base_mode == "pred":
        raw = current["pred_return"].astype(float)
        raw = raw - raw.groupby(current["trade_date"]).transform("min") + 1e-6
    elif base_mode == "score":
        score_col = "model_score" if "model_score" in current.columns else "pred_return"
        raw = current[score_col].astype(float)
        raw = raw - raw.groupby(current["trade_date"]).transform("min") + 1e-6
    else:
        raw = pd.Series(1.0, index=current.index, dtype="float64")
    raw = raw.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    denom = raw.groupby(current["trade_date"]).transform("sum").replace(0, np.nan)
    fallback = current.groupby("trade_date")["trade_date"].transform(lambda s: 1.0 / max(len(s), 1))
    current["position_weight"] = (raw / denom).fillna(fallback).astype(float)
    if cap is not None:
        current["position_weight"] = current.groupby("trade_date", group_keys=False)["position_weight"].apply(
            lambda s: capped_position_weights(s, float(cap))
        )
    return current


def selected_trades_for_candidate(pred: pd.DataFrame, candidate: dict[str, Any]) -> pd.DataFrame:
    horizon = int(candidate.get("horizon", 20) or 20)
    top_n = int(candidate.get("top_n", 1) or 1)
    pool = filtered_pool(
        pred,
        top_n,
        str(candidate.get("segment", "all") or "all"),
        safe_float(candidate.get("min_pred_return"), -999.0),
        safe_float(candidate.get("min_market_up_ratio"), -999.0),
        safe_float(candidate.get("min_market_ret5"), -999.0),
        safe_float(candidate.get("min_market_ret20"), -999.0),
        safe_float(candidate.get("min_market_amount_chg5"), -999.0),
        safe_float(candidate.get("min_market_volatility20"), -999.0),
        safe_float(candidate.get("max_market_drawdown20"), 999.0),
        safe_float(candidate.get("max_market_volatility20"), 999.0),
        safe_float(candidate.get("min_turnover_rate"), -999.0),
        safe_float(candidate.get("min_industry_up_ratio"), -999.0),
        safe_float(candidate.get("min_small_up_ratio"), -999.0),
        safe_float(candidate.get("min_small_limit_up_ratio"), -999.0),
        safe_float(candidate.get("min_small_near_limit_up_ratio"), -999.0),
        safe_float(candidate.get("min_small_amount_chg5"), -999.0),
        safe_float(candidate.get("min_small_rs_market20"), -999.0),
        safe_float(candidate.get("min_small_breakout_high20_ratio"), -999.0),
        safe_float(candidate.get("max_crash_prob"), 999.0),
        safe_float(candidate.get("min_daily_top_score"), -999.0),
        safe_float(candidate.get("min_daily_top_pred_return"), -999.0),
        safe_float(candidate.get("max_daily_top_crash_prob"), 999.0),
    )
    trades = top_rows_by_date(pool, top_n)
    trades = apply_execution_rules(
        trades,
        horizon,
        safe_float(candidate.get("execution_stop_loss"), 0.0),
        safe_float(candidate.get("execution_take_profit"), 0.0),
    )
    trades = apply_position_weighting(trades, str(candidate.get("position_weighting", "equal") or "equal"))
    trades["capital_scale"] = capital_scale_series(trades, str(candidate.get("capital_scale_mode", "none") or "none"))
    return trades


def champion_validation_report(args: argparse.Namespace, pred: pd.DataFrame, candidate: dict[str, Any]) -> dict[str, Any]:
    trades = selected_trades_for_candidate(pred, candidate)
    capital_fraction = safe_float(candidate.get("capital_tranche_fraction"), 1.0)
    report: dict[str, Any] = {
        "status": "ok",
        "checks": {
            "yearly_shortfalls": {},
            "single_name_loss": {},
            "execution_realism": {},
        },
    }
    if trades.empty:
        report["status"] = "no_trades"
        return report

    current = trades.copy()
    current["year"] = current["trade_date"].astype(str).str.slice(0, 4).astype(int)
    all_trade_dates = sorted({str(value) for value in pred.get("trade_date", pd.Series(dtype="object")).dropna().astype(str).unique()})
    yearly_rows: list[dict[str, Any]] = []
    short_years: list[dict[str, Any]] = []
    for year, group in current.groupby("year", sort=True):
        daily = group.groupby("trade_date")["realized_return"].mean()
        stats = equity_stats(daily)
        year_dates = [date for date in all_trade_dates if str(date).startswith(str(year))]
        capital_stats = simulate_capital_curves_many(
            group,
            int(candidate.get("horizon", 20) or 20),
            [capital_fraction],
            year_dates,
            float(getattr(args, "max_gross_exposure", 1.0) or 1.0),
        )[0]
        row = {
            "year": int(year),
            "trade_count": int(len(group)),
            "trade_days": int(group["trade_date"].nunique()),
            "avg_return": safe_float(group["realized_return"].mean()),
            "win_rate": safe_float((group["realized_return"] > 0).mean()),
            **stats,
            "capital_compound_return": capital_stats.get("capital_compound_return", 0.0),
            "capital_annual_return": capital_stats.get("capital_annual_return", 0.0),
            "capital_max_drawdown": capital_stats.get("capital_max_drawdown", 0.0),
            "capital_sharpe": capital_stats.get("capital_sharpe", 0.0),
        }
        yearly_rows.append(row)
        if (
            row["capital_compound_return"] < 0.0
            or row["capital_max_drawdown"] < -0.25
            or row["max_drawdown"] < -0.25
            or row["trade_count"] < 20
            or row["trade_days"] < 5
        ):
            short_years.append(row)
    report["checks"]["yearly_shortfalls"] = {
        "status": "pass" if not short_years else "warn",
        "criteria": "短板年定义：年度资金复利<0，或年度资金最大回撤<-25%，或信号年度最大回撤<-25%，或年度交易数<20，或交易日<5。",
        "annual_return_note": "稀疏年份的年化容易失真，复验主看年度资金复利、年度回撤和样本数。",
        "shortfall_count": len(short_years),
        "shortfall_years": short_years,
        "yearly": yearly_rows,
    }

    current["portfolio_weight_estimate"] = (
        pd.to_numeric(current.get("position_weight", 0.0), errors="coerce").fillna(0.0)
        * capital_fraction
        * pd.to_numeric(current.get("capital_scale", 1.0), errors="coerce").fillna(1.0)
    )
    current["portfolio_return_contribution_estimate"] = current["portfolio_weight_estimate"] * current["realized_return"].astype(float)
    loss_cols = [
        "trade_date",
        "exit_date",
        "ts_code",
        "name",
        "industry",
        "size_bucket",
        "pred_return",
        "model_score",
        "realized_return",
        "position_weight",
        "capital_scale",
        "portfolio_weight_estimate",
        "portfolio_return_contribution_estimate",
    ]
    available_loss_cols = [col for col in loss_cols if col in current.columns]
    worst_by_trade = current.sort_values("realized_return", ascending=True).head(10)
    worst_by_contribution = current.sort_values("portfolio_return_contribution_estimate", ascending=True).head(10)

    def rows_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for row in frame[available_loss_cols].to_dict("records"):
            records.append({key: (safe_float(value) if isinstance(value, (float, int, np.floating, np.integer)) else value) for key, value in row.items()})
        return records

    worst_single = worst_by_trade.iloc[0].to_dict() if not worst_by_trade.empty else {}
    worst_contrib = worst_by_contribution.iloc[0].to_dict() if not worst_by_contribution.empty else {}
    report["checks"]["single_name_loss"] = {
        "status": "pass" if safe_float(worst_contrib.get("portfolio_return_contribution_estimate")) > -0.05 else "warn",
        "capital_tranche_fraction": capital_fraction,
        "max_single_trade_loss": safe_float(worst_single.get("realized_return")),
        "max_single_trade_loss_stock": {
            key: worst_single.get(key)
            for key in ["trade_date", "exit_date", "ts_code", "name", "industry", "size_bucket"]
            if key in worst_single
        },
        "max_portfolio_contribution_loss": safe_float(worst_contrib.get("portfolio_return_contribution_estimate")),
        "max_portfolio_contribution_loss_stock": {
            key: worst_contrib.get(key)
            for key in ["trade_date", "exit_date", "ts_code", "name", "industry", "size_bucket"]
            if key in worst_contrib
        },
        "worst_trades_by_return": rows_to_records(worst_by_trade),
        "worst_trades_by_portfolio_contribution": rows_to_records(worst_by_contribution),
    }

    report["checks"]["execution_realism"] = {
        "status": "warn",
        "handled": [
            {
                "item": "交易成本",
                "evidence": f"net_return 标签已扣 buy_slippage={args.buy_slippage}, sell_slippage={args.sell_slippage}, commission={args.commission}, stamp_tax={args.stamp_tax}。",
            },
            {
                "item": "买入涨停/不可买过滤",
                "evidence": "样本构造要求 next_open>0 且 next_pct < price_limit_pct-0.2，否则 net_return 置 NaN，无法进入可交易收益标签。",
            },
            {
                "item": "基础流动性过滤",
                "evidence": "股票池要求价格>=2.5、成交额>=20000、上市满120天、排除 ST/退市/创业板/科创板/北交所。",
            },
        ],
        "approximate": [
            {
                "item": "止盈/止损触发",
                "evidence": "execution_take_profit/execution_stop_loss 使用未来区间 high/low 和首个触发日期近似，不是逐笔撮合；同日触发时 stop_loss 优先。",
            },
            {
                "item": "买入成交价",
                "evidence": "默认按次日开盘价叠加滑点/手续费估算，没有盘口冲击模型。",
            },
        ],
        "missing_or_weak": [
            {
                "item": "卖出跌停/停牌不可卖",
                "evidence": "当前 exit_close/日内 high-low 近似未显式模拟卖出日跌停无法成交或持仓停牌顺延。",
            },
            {
                "item": "冲击成本",
                "evidence": "当前只用固定滑点和手续费，没有按成交额/持仓规模动态冲击成本。",
            },
        ],
    }
    return report


def top_rows_by_date(
    frame: pd.DataFrame,
    top_n: int,
    segment: str = "all",
    min_pred_return: float = -999.0,
    min_market_up_ratio: float = -999.0,
    min_market_ret5: float = -999.0,
    min_market_ret20: float = -999.0,
    min_market_amount_chg5: float = -999.0,
    min_market_volatility20: float = -999.0,
    max_market_drawdown20: float = 999.0,
    max_market_volatility20: float = 999.0,
    min_turnover_rate: float = -999.0,
    min_industry_up_ratio: float = -999.0,
    min_small_up_ratio: float = -999.0,
    min_small_limit_up_ratio: float = -999.0,
    min_small_near_limit_up_ratio: float = -999.0,
    min_small_amount_chg5: float = -999.0,
    min_small_rs_market20: float = -999.0,
    min_small_breakout_high20_ratio: float = -999.0,
    max_crash_prob: float = 999.0,
) -> pd.DataFrame:
    current = frame if segment == "all" else frame[frame["size_bucket"] == segment]
    if min_pred_return > -900:
        current = current[current["pred_return"] >= float(min_pred_return)]
    if min_market_up_ratio > -900:
        current = current[current["market_up_ratio"] >= float(min_market_up_ratio)]
    if min_market_ret5 > -900:
        current = current[current["market_ret5"] >= float(min_market_ret5)]
    if min_market_ret20 > -900:
        current = current[current["market_ret20"] >= float(min_market_ret20)]
    if min_market_amount_chg5 > -900:
        current = current[current["market_amount_chg5"] >= float(min_market_amount_chg5)]
    if min_market_volatility20 > -900:
        current = current[current["market_volatility20"] >= float(min_market_volatility20)]
    if max_market_drawdown20 < 900:
        current = current[current["market_drawdown20"] >= -abs(float(max_market_drawdown20))]
    if max_market_volatility20 < 900:
        current = current[current["market_volatility20"] <= float(max_market_volatility20)]
    if min_turnover_rate > -900:
        current = current[current["turnover_rate"] >= float(min_turnover_rate)]
    if min_industry_up_ratio > -900:
        current = current[current["industry_up_ratio"] >= float(min_industry_up_ratio)]
    if min_small_up_ratio > -900:
        current = current[current["small_up_ratio"] >= float(min_small_up_ratio)]
    if min_small_limit_up_ratio > -900:
        current = current[current["small_limit_up_ratio"] >= float(min_small_limit_up_ratio)]
    if min_small_near_limit_up_ratio > -900:
        current = current[current["small_near_limit_up_ratio"] >= float(min_small_near_limit_up_ratio)]
    if min_small_amount_chg5 > -900:
        current = current[current["small_amount_chg5"] >= float(min_small_amount_chg5)]
    if min_small_rs_market20 > -900:
        current = current[current["small_rs_market20"] >= float(min_small_rs_market20)]
    if min_small_breakout_high20_ratio > -900:
        current = current[current["small_breakout_high20_ratio"] >= float(min_small_breakout_high20_ratio)]
    if max_crash_prob < 900 and "crash_prob" in current.columns:
        current = current[current["crash_prob"] <= float(max_crash_prob)]
    if current.empty:
        return current.copy()
    sort_col = "model_score" if "model_score" in current.columns else "pred_return"
    return current.sort_values(["trade_date", sort_col], ascending=[True, False]).groupby("trade_date", sort=False).head(top_n).copy()


def filtered_pool(
    frame: pd.DataFrame,
    top_n: int,
    segment: str = "all",
    min_pred_return: float = -999.0,
    min_market_up_ratio: float = -999.0,
    min_market_ret5: float = -999.0,
    min_market_ret20: float = -999.0,
    min_market_amount_chg5: float = -999.0,
    min_market_volatility20: float = -999.0,
    max_market_drawdown20: float = 999.0,
    max_market_volatility20: float = 999.0,
    min_turnover_rate: float = -999.0,
    min_industry_up_ratio: float = -999.0,
    min_small_up_ratio: float = -999.0,
    min_small_limit_up_ratio: float = -999.0,
    min_small_near_limit_up_ratio: float = -999.0,
    min_small_amount_chg5: float = -999.0,
    min_small_rs_market20: float = -999.0,
    min_small_breakout_high20_ratio: float = -999.0,
    max_crash_prob: float = 999.0,
    min_daily_top_score: float = -999.0,
    min_daily_top_pred_return: float = -999.0,
    max_daily_top_crash_prob: float = 999.0,
) -> pd.DataFrame:
    current = frame if segment == "all" else frame[frame["size_bucket"] == segment]
    if min_pred_return > -900:
        current = current[current["pred_return"] >= float(min_pred_return)]
    if min_market_up_ratio > -900:
        current = current[current["market_up_ratio"] >= float(min_market_up_ratio)]
    if min_market_ret5 > -900:
        current = current[current["market_ret5"] >= float(min_market_ret5)]
    if min_market_ret20 > -900:
        current = current[current["market_ret20"] >= float(min_market_ret20)]
    if min_market_amount_chg5 > -900:
        current = current[current["market_amount_chg5"] >= float(min_market_amount_chg5)]
    if min_market_volatility20 > -900:
        current = current[current["market_volatility20"] >= float(min_market_volatility20)]
    if max_market_drawdown20 < 900:
        current = current[current["market_drawdown20"] >= -abs(float(max_market_drawdown20))]
    if max_market_volatility20 < 900:
        current = current[current["market_volatility20"] <= float(max_market_volatility20)]
    if min_turnover_rate > -900:
        current = current[current["turnover_rate"] >= float(min_turnover_rate)]
    if min_industry_up_ratio > -900:
        current = current[current["industry_up_ratio"] >= float(min_industry_up_ratio)]
    if min_small_up_ratio > -900:
        current = current[current["small_up_ratio"] >= float(min_small_up_ratio)]
    if min_small_limit_up_ratio > -900:
        current = current[current["small_limit_up_ratio"] >= float(min_small_limit_up_ratio)]
    if min_small_near_limit_up_ratio > -900:
        current = current[current["small_near_limit_up_ratio"] >= float(min_small_near_limit_up_ratio)]
    if min_small_amount_chg5 > -900:
        current = current[current["small_amount_chg5"] >= float(min_small_amount_chg5)]
    if min_small_rs_market20 > -900:
        current = current[current["small_rs_market20"] >= float(min_small_rs_market20)]
    if min_small_breakout_high20_ratio > -900:
        current = current[current["small_breakout_high20_ratio"] >= float(min_small_breakout_high20_ratio)]
    if max_crash_prob < 900 and "crash_prob" in current.columns:
        current = current[current["crash_prob"] <= float(max_crash_prob)]
    return apply_daily_signal_filter(
        current,
        top_n,
        min_daily_top_score,
        min_daily_top_pred_return,
        max_daily_top_crash_prob,
    )


def apply_daily_signal_filter(
    current: pd.DataFrame,
    top_n: int,
    min_daily_top_score: float = -999.0,
    min_daily_top_pred_return: float = -999.0,
    max_daily_top_crash_prob: float = 999.0,
) -> pd.DataFrame:
    if current.empty:
        return current
    if min_daily_top_score > -900 or min_daily_top_pred_return > -900 or max_daily_top_crash_prob < 900:
        sort_col = "model_score" if "model_score" in current.columns else "pred_return"
        top = current.sort_values(["trade_date", sort_col], ascending=[True, False]).groupby("trade_date", sort=False).head(int(top_n))
        daily = top.groupby("trade_date", sort=False).agg(
            daily_top_score=(sort_col, "mean"),
            daily_top_pred_return=("pred_return", "mean"),
            daily_top_crash_prob=("crash_prob", "mean") if "crash_prob" in top.columns else (sort_col, lambda _: 0.0),
        )
        keep = pd.Series(True, index=daily.index)
        if min_daily_top_score > -900:
            keep &= daily["daily_top_score"] >= float(min_daily_top_score)
        if min_daily_top_pred_return > -900:
            keep &= daily["daily_top_pred_return"] >= float(min_daily_top_pred_return)
        if max_daily_top_crash_prob < 900:
            keep &= daily["daily_top_crash_prob"] <= float(max_daily_top_crash_prob)
        current = current[current["trade_date"].isin(keep[keep].index)]
    return current


def rank_ic_stats(pool: pd.DataFrame, min_names: int = 20) -> dict[str, float | int]:
    if pool.empty:
        return {"rank_ic": 0.0, "rank_ic_days": 0}
    score_col = "model_score" if "model_score" in pool.columns else "pred_return"
    daily: list[float] = []
    for _, group in pool.groupby("trade_date", sort=False):
        if len(group) < int(min_names):
            continue
        score = group[score_col]
        realized = group["realized_return"]
        if score.nunique(dropna=True) < 2 or realized.nunique(dropna=True) < 2:
            continue
        corr = score.corr(realized, method="spearman")
        if pd.notna(corr) and math.isfinite(float(corr)):
            daily.append(float(corr))
    if not daily:
        return {"rank_ic": 0.0, "rank_ic_days": 0}
    return {"rank_ic": safe_float(np.mean(daily)), "rank_ic_days": int(len(daily))}


def evaluate_predictions(
    pred: pd.DataFrame,
    top_n: int,
    horizon: int,
    segment: str,
    min_pred_return: float = -999.0,
    min_market_up_ratio: float = -999.0,
    min_market_ret5: float = -999.0,
    min_market_ret20: float = -999.0,
    min_market_amount_chg5: float = -999.0,
    min_market_volatility20: float = -999.0,
    max_market_drawdown20: float = 999.0,
    max_market_volatility20: float = 999.0,
    min_turnover_rate: float = -999.0,
    min_industry_up_ratio: float = -999.0,
    min_small_up_ratio: float = -999.0,
    min_small_limit_up_ratio: float = -999.0,
    min_small_near_limit_up_ratio: float = -999.0,
    min_small_amount_chg5: float = -999.0,
    min_small_rs_market20: float = -999.0,
    min_small_breakout_high20_ratio: float = -999.0,
    max_crash_prob: float = 999.0,
    min_daily_top_score: float = -999.0,
    min_daily_top_pred_return: float = -999.0,
    max_daily_top_crash_prob: float = 999.0,
    execution_stop_loss: float = 0.0,
    execution_take_profit: float = 0.0,
    position_weighting: str = "equal",
    capital_scale_mode: str = "none",
    capital_tranche_fraction: float = 0.0,
    max_gross_exposure: float = 1.0,
    all_dates: Sequence[str] | None = None,
) -> dict[str, Any]:
    return evaluate_predictions_many_capital(
        pred,
        top_n,
        horizon,
        segment,
        min_pred_return,
        min_market_up_ratio,
        min_market_ret5,
        min_market_ret20,
        min_market_amount_chg5,
        min_market_volatility20,
        max_market_drawdown20,
        max_market_volatility20,
        min_turnover_rate,
        min_industry_up_ratio,
        min_small_up_ratio,
        min_small_limit_up_ratio,
        min_small_near_limit_up_ratio,
        min_small_amount_chg5,
        min_small_rs_market20,
        min_small_breakout_high20_ratio,
        max_crash_prob,
        min_daily_top_score,
        min_daily_top_pred_return,
        max_daily_top_crash_prob,
        execution_stop_loss,
        execution_take_profit,
        position_weighting,
        capital_scale_mode,
        [capital_tranche_fraction],
        max_gross_exposure,
        all_dates,
    )[0]


def evaluate_predictions_many_capital(
    pred: pd.DataFrame,
    top_n: int,
    horizon: int,
    segment: str,
    min_pred_return: float = -999.0,
    min_market_up_ratio: float = -999.0,
    min_market_ret5: float = -999.0,
    min_market_ret20: float = -999.0,
    min_market_amount_chg5: float = -999.0,
    min_market_volatility20: float = -999.0,
    max_market_drawdown20: float = 999.0,
    max_market_volatility20: float = 999.0,
    min_turnover_rate: float = -999.0,
    min_industry_up_ratio: float = -999.0,
    min_small_up_ratio: float = -999.0,
    min_small_limit_up_ratio: float = -999.0,
    min_small_near_limit_up_ratio: float = -999.0,
    min_small_amount_chg5: float = -999.0,
    min_small_rs_market20: float = -999.0,
    min_small_breakout_high20_ratio: float = -999.0,
    max_crash_prob: float = 999.0,
    min_daily_top_score: float = -999.0,
    min_daily_top_pred_return: float = -999.0,
    max_daily_top_crash_prob: float = 999.0,
    execution_stop_loss: float = 0.0,
    execution_take_profit: float = 0.0,
    position_weighting: str = "equal",
    capital_scale_mode: str = "none",
    capital_tranche_fractions: Sequence[float] = (0.0,),
    max_gross_exposure: float = 1.0,
    all_dates: Sequence[str] | None = None,
    min_rank_ic: float = 0.0,
    min_rank_ic_days: int = 0,
) -> list[dict[str, Any]]:
    pool = filtered_pool(
        pred,
        top_n,
        segment,
        min_pred_return,
        min_market_up_ratio,
        min_market_ret5,
        min_market_ret20,
        min_market_amount_chg5,
        min_market_volatility20,
        max_market_drawdown20,
        max_market_volatility20,
        min_turnover_rate,
        min_industry_up_ratio,
        min_small_up_ratio,
        min_small_limit_up_ratio,
        min_small_near_limit_up_ratio,
        min_small_amount_chg5,
        min_small_rs_market20,
        min_small_breakout_high20_ratio,
        max_crash_prob,
        min_daily_top_score,
        min_daily_top_pred_return,
        max_daily_top_crash_prob,
    )
    trades = top_rows_by_date(pool, top_n)
    ic_stats = rank_ic_stats(pool)
    return evaluate_trades_many_capital(
        pred,
        trades,
        ic_stats,
        top_n,
        horizon,
        segment,
        min_pred_return,
        min_market_up_ratio,
        min_market_ret5,
        min_market_ret20,
        min_market_amount_chg5,
        min_market_volatility20,
        max_market_drawdown20,
        max_market_volatility20,
        min_turnover_rate,
        min_industry_up_ratio,
        min_small_up_ratio,
        min_small_limit_up_ratio,
        min_small_near_limit_up_ratio,
        min_small_amount_chg5,
        min_small_rs_market20,
        min_small_breakout_high20_ratio,
        max_crash_prob,
        min_daily_top_score,
        min_daily_top_pred_return,
        max_daily_top_crash_prob,
        execution_stop_loss,
        execution_take_profit,
        position_weighting,
        capital_scale_mode,
        capital_tranche_fractions,
        max_gross_exposure,
        all_dates,
    )


def evaluate_trades_many_capital(
    pred: pd.DataFrame,
    trades: pd.DataFrame,
    ic_stats: dict[str, float | int],
    top_n: int,
    horizon: int,
    segment: str,
    min_pred_return: float = -999.0,
    min_market_up_ratio: float = -999.0,
    min_market_ret5: float = -999.0,
    min_market_ret20: float = -999.0,
    min_market_amount_chg5: float = -999.0,
    min_market_volatility20: float = -999.0,
    max_market_drawdown20: float = 999.0,
    max_market_volatility20: float = 999.0,
    min_turnover_rate: float = -999.0,
    min_industry_up_ratio: float = -999.0,
    min_small_up_ratio: float = -999.0,
    min_small_limit_up_ratio: float = -999.0,
    min_small_near_limit_up_ratio: float = -999.0,
    min_small_amount_chg5: float = -999.0,
    min_small_rs_market20: float = -999.0,
    min_small_breakout_high20_ratio: float = -999.0,
    max_crash_prob: float = 999.0,
    min_daily_top_score: float = -999.0,
    min_daily_top_pred_return: float = -999.0,
    max_daily_top_crash_prob: float = 999.0,
    execution_stop_loss: float = 0.0,
    execution_take_profit: float = 0.0,
    position_weighting: str = "equal",
    capital_scale_mode: str = "none",
    capital_tranche_fractions: Sequence[float] = (0.0,),
    max_gross_exposure: float = 1.0,
    all_dates: Sequence[str] | None = None,
    min_rank_ic: float = 0.0,
    min_rank_ic_days: int = 0,
) -> list[dict[str, Any]]:
    base = {
        "horizon": int(horizon),
        "top_n": int(top_n),
        "min_pred_return": safe_float(min_pred_return),
        "min_market_up_ratio": safe_float(min_market_up_ratio),
        "min_market_ret5": safe_float(min_market_ret5),
        "min_market_ret20": safe_float(min_market_ret20),
        "min_market_amount_chg5": safe_float(min_market_amount_chg5),
        "min_market_volatility20": safe_float(min_market_volatility20),
        "max_market_drawdown20": safe_float(max_market_drawdown20),
        "max_market_volatility20": safe_float(max_market_volatility20),
        "min_turnover_rate": safe_float(min_turnover_rate),
        "min_industry_up_ratio": safe_float(min_industry_up_ratio),
        "min_small_up_ratio": safe_float(min_small_up_ratio),
        "min_small_limit_up_ratio": safe_float(min_small_limit_up_ratio),
        "min_small_near_limit_up_ratio": safe_float(min_small_near_limit_up_ratio),
        "min_small_amount_chg5": safe_float(min_small_amount_chg5),
        "min_small_rs_market20": safe_float(min_small_rs_market20),
        "min_small_breakout_high20_ratio": safe_float(min_small_breakout_high20_ratio),
        "max_crash_prob": safe_float(max_crash_prob),
        "min_daily_top_score": safe_float(min_daily_top_score),
        "min_daily_top_pred_return": safe_float(min_daily_top_pred_return),
        "max_daily_top_crash_prob": safe_float(max_daily_top_crash_prob),
        "execution_stop_loss": safe_float(execution_stop_loss),
        "execution_take_profit": safe_float(execution_take_profit),
        "position_weighting": str(position_weighting or "equal"),
        "capital_scale_mode": str(capital_scale_mode or "none"),
        "segment": segment,
        "trade_count": int(len(trades)),
        "trade_days": int(trades["trade_date"].nunique()) if not trades.empty else 0,
        "trade_years": int(trades["trade_date"].astype(str).str.slice(0, 4).nunique()) if not trades.empty else 0,
    }
    if trades.empty:
        empty_capital = capital_curve_stats(pd.Series(dtype="float64"))
        return [
            {
                **base,
                "capital_tranche_fraction": safe_float(capital_fraction),
                "avg_return": 0.0,
                "win_rate": 0.0,
                "compound_return": 0.0,
                "annual_return": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
                **ic_stats,
                **empty_capital,
                "yearly": [],
            }
            for capital_fraction in capital_tranche_fractions
        ]
    trades = apply_execution_rules(trades, horizon, execution_stop_loss, execution_take_profit)
    trades = apply_position_weighting(trades, position_weighting)
    trades["capital_scale"] = capital_scale_series(trades, capital_scale_mode)
    daily_returns = trades.groupby("trade_date")["realized_return"].mean()
    stats = equity_stats(daily_returns)
    if all_dates is None:
        all_dates = pred["trade_date"].astype(str).unique().tolist()
    yearly: list[dict[str, Any]] = []
    trades = trades.copy()
    trades["year"] = trades["trade_date"].astype(str).str.slice(0, 4).astype(int)
    for year, group in trades.groupby("year", sort=True):
        year_daily = group.groupby("trade_date")["realized_return"].mean()
        year_stats = equity_stats(year_daily)
        yearly.append({
            "year": int(year),
            "trade_count": int(len(group)),
            "avg_return": safe_float(group["realized_return"].mean()),
            "win_rate": safe_float((group["realized_return"] > 0).mean()),
            **year_stats,
        })
    common = {
        **base,
        "avg_return": safe_float(trades["realized_return"].mean()),
        "win_rate": safe_float((trades["realized_return"] > 0).mean()),
        **stats,
        **ic_stats,
        "yearly": yearly,
    }
    capital_stats = simulate_capital_curves_many(trades, horizon, capital_tranche_fractions, all_dates, max_gross_exposure)
    return [
        {
            **common,
            "capital_tranche_fraction": safe_float(capital_fraction),
            **stats_for_fraction,
        }
        for capital_fraction, stats_for_fraction in zip(capital_tranche_fractions, capital_stats)
    ]


def evaluate_pool_many_top_capital(
    pred: pd.DataFrame,
    top_n_values: Sequence[int],
    horizon: int,
    segment: str,
    min_pred_return: float = -999.0,
    min_market_up_ratio: float = -999.0,
    min_market_ret5: float = -999.0,
    min_market_ret20: float = -999.0,
    min_market_amount_chg5: float = -999.0,
    min_market_volatility20: float = -999.0,
    max_market_drawdown20: float = 999.0,
    max_market_volatility20: float = 999.0,
    min_turnover_rate: float = -999.0,
    min_industry_up_ratio: float = -999.0,
    min_small_up_ratio: float = -999.0,
    min_small_limit_up_ratio: float = -999.0,
    min_small_near_limit_up_ratio: float = -999.0,
    min_small_amount_chg5: float = -999.0,
    min_small_rs_market20: float = -999.0,
    min_small_breakout_high20_ratio: float = -999.0,
    max_crash_prob: float = 999.0,
    min_daily_top_score: float = -999.0,
    min_daily_top_pred_return: float = -999.0,
    max_daily_top_crash_prob: float = 999.0,
    execution_stop_loss: float = 0.0,
    execution_take_profit: float = 0.0,
    position_weighting: str = "equal",
    capital_scale_mode: str = "none",
    capital_tranche_fractions: Sequence[float] = (0.0,),
    max_gross_exposure: float = 1.0,
    all_dates: Sequence[str] | None = None,
    min_rank_ic: float = 0.0,
    min_rank_ic_days: int = 0,
) -> list[dict[str, Any]]:
    max_top_n = max(int(value) for value in top_n_values) if top_n_values else 0
    pool = filtered_pool(
        pred,
        max_top_n,
        segment,
        min_pred_return,
        min_market_up_ratio,
        min_market_ret5,
        min_market_ret20,
        min_market_amount_chg5,
        min_market_volatility20,
        max_market_drawdown20,
        max_market_volatility20,
        min_turnover_rate,
        min_industry_up_ratio,
        min_small_up_ratio,
        min_small_limit_up_ratio,
        min_small_near_limit_up_ratio,
        min_small_amount_chg5,
        min_small_rs_market20,
        min_small_breakout_high20_ratio,
        max_crash_prob,
    )

    evaluations: list[dict[str, Any]] = []
    for top_n in top_n_values:
        top_pool = apply_daily_signal_filter(
            pool,
            int(top_n),
            min_daily_top_score,
            min_daily_top_pred_return,
            max_daily_top_crash_prob,
        )
        ic_stats = rank_ic_stats(top_pool)
        if (float(min_rank_ic or 0.0) > 0 and safe_float(ic_stats.get("rank_ic")) < float(min_rank_ic)) or (
            int(min_rank_ic_days or 0) > 0 and int(ic_stats.get("rank_ic_days", 0) or 0) < int(min_rank_ic_days)
        ):
            continue
        if top_pool.empty or max_top_n <= 0:
            trades = top_pool.copy()
        else:
            sort_col = "model_score" if "model_score" in top_pool.columns else "pred_return"
            trades = top_pool.sort_values(["trade_date", sort_col], ascending=[True, False]).groupby("trade_date", sort=False).head(int(top_n)).copy()
        evaluations.extend(evaluate_trades_many_capital(
            pred,
            trades,
            ic_stats,
            int(top_n),
            horizon,
            segment,
            min_pred_return,
            min_market_up_ratio,
            min_market_ret5,
            min_market_ret20,
            min_market_amount_chg5,
            min_market_volatility20,
            max_market_drawdown20,
            max_market_volatility20,
            min_turnover_rate,
            min_industry_up_ratio,
            min_small_up_ratio,
            min_small_limit_up_ratio,
            min_small_near_limit_up_ratio,
            min_small_amount_chg5,
            min_small_rs_market20,
            min_small_breakout_high20_ratio,
            max_crash_prob,
            min_daily_top_score,
            min_daily_top_pred_return,
            max_daily_top_crash_prob,
            execution_stop_loss,
            execution_take_profit,
            position_weighting,
            capital_scale_mode,
            capital_tranche_fractions,
            max_gross_exposure,
            all_dates,
        ))
    return evaluations


def train_scope_horizon(args: argparse.Namespace, data: pd.DataFrame, scope: str, horizon: int) -> dict[str, Any]:
    import lightgbm as lgb

    train_target = f"net_return_{horizon}d"
    target_mode = str(getattr(args, "target_mode", "net_return") or "net_return").strip().lower()
    if target_mode == "future_max_return":
        train_target = f"future_max_return_{horizon}d"
    eval_target = f"net_return_{horizon}d"
    source_data = data
    if target_mode == "drawdown_penalized":
        drawdown_col = f"future_drawdown_{horizon}d"
        source_data = data.copy()
        penalty = float(getattr(args, "drawdown_penalty_weight", 0.5) or 0.0)
        source_data["drawdown_penalized_target"] = (
            source_data[eval_target].astype(float)
            - penalty * source_data[drawdown_col].astype(float).clip(upper=0.0).abs()
        )
        train_target = "drawdown_penalized_target"
    progress_log(
        "scope_horizon_start",
        run_id=args.run_id,
        scope=scope,
        horizon=horizon,
        target=train_target,
        eval_target=eval_target,
        target_mode=target_mode,
        drawdown_penalty_weight=getattr(args, "drawdown_penalty_weight", None),
    )
    sample = source_data.dropna(subset=[train_target, eval_target]).copy()
    if scope != "all":
        sample = sample[sample["size_bucket"] == scope].copy()
    sample = sample.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    if len(sample) < int(args.min_train_rows):
        progress_log("scope_horizon_skipped", run_id=args.run_id, scope=scope, horizon=horizon, rows=len(sample), reason="min_train_rows")
        return {"scope": scope, "horizon": horizon, "status": "skipped", "reason": f"sample rows {len(sample)} < {args.min_train_rows}"}
    sample["year"] = sample["trade_date"].astype(str).str.slice(0, 4).astype(int)
    min_year = max(int(sample["year"].min()) + int(args.min_train_years), int(args.min_test_year))
    test_years = [int(year) for year in sorted(sample["year"].unique()) if int(year) >= min_year]
    if not test_years:
        progress_log("scope_horizon_skipped", run_id=args.run_id, scope=scope, horizon=horizon, rows=len(sample), reason="no_test_years")
        return {"scope": scope, "horizon": horizon, "status": "skipped", "reason": "no test years"}

    predictions: list[pd.DataFrame] = []
    fold_metrics: list[dict[str, Any]] = []
    feature_cols = list(getattr(args, "feature_columns", FEATURES))
    importance = pd.Series(0.0, index=feature_cols, dtype="float64")
    models: list[Any] = []
    crash_models: list[Any] = []
    breakout_models: list[Any] = []
    x_all = sample[feature_cols].astype(float)
    y_all = sample[train_target].astype(float)
    rank_y_all = rank_labels_by_date(sample, train_target) if args.model_kind in {"ranker", "hybrid"} else None
    crash_y_all = None
    if args.crash_filter != "none":
        crash_y_all = (
            (sample[eval_target].astype(float) <= float(args.crash_return_threshold))
            | (sample[f"future_drawdown_{horizon}d"].astype(float) <= float(args.crash_drawdown_threshold))
        ).astype("int8")
    breakout_y_all = None
    if args.breakout_filter != "none":
        breakout_y_all = breakout_labels_by_date(sample, train_target, args.breakout_quantile)

    progress_log(
        "walk_forward_start",
        run_id=args.run_id,
        scope=scope,
        horizon=horizon,
        rows=len(sample),
        test_years=test_years,
        model_kind=args.model_kind,
    )
    for fold_no, year in enumerate(test_years, 1):
        train_mask = sample["year"] < year
        if int(args.train_window_years) > 0:
            train_mask = train_mask & (sample["year"] >= year - int(args.train_window_years))
        test_mask = sample["year"] == year
        if int(train_mask.sum()) < int(args.min_train_rows) or int(test_mask.sum()) == 0:
            progress_log(
                "fold_skipped",
                run_id=args.run_id,
                scope=scope,
                horizon=horizon,
                year=year,
                fold=fold_no,
                total_folds=len(test_years),
                train_rows=int(train_mask.sum()),
                test_rows=int(test_mask.sum()),
            )
            continue
        train_idx = sample.index[train_mask]
        if int(args.train_sample_per_year) > 0:
            train_idx = (
                sample.loc[train_mask]
                .groupby("year", group_keys=False)
                .apply(lambda part: part.sample(n=min(len(part), int(args.train_sample_per_year)), random_state=20260613 + int(year) + int(horizon)))
                .index
            )
        if len(train_idx) < int(args.min_train_rows):
            progress_log(
                "fold_skipped",
                run_id=args.run_id,
                scope=scope,
                horizon=horizon,
                year=year,
                fold=fold_no,
                total_folds=len(test_years),
                train_rows=len(train_idx),
                reason="sampled_train_rows",
            )
            continue
        progress_log(
            "fold_train_start",
            run_id=args.run_id,
            scope=scope,
            horizon=horizon,
            year=year,
            fold=fold_no,
            total_folds=len(test_years),
            train_rows=len(train_idx),
            test_rows=int(test_mask.sum()),
        )
        if args.model_kind in {"ranker", "hybrid"}:
            train_frame = sample.loc[train_idx].sort_values(["trade_date", "ts_code"])
            train_idx = train_frame.index
            ranker_model = lgb.LGBMRanker(
                objective="lambdarank",
                metric="ndcg",
                label_gain=[0, 1, 2, 4, 8],
                n_estimators=int(args.n_estimators),
                learning_rate=float(args.learning_rate),
                num_leaves=int(args.num_leaves),
                max_depth=int(args.max_depth),
                min_child_samples=int(args.min_child_samples),
                subsample=float(args.subsample),
                colsample_bytree=float(args.colsample_bytree),
                reg_alpha=float(args.reg_alpha),
                reg_lambda=float(args.reg_lambda),
                random_state=20260613 + year + horizon,
                n_jobs=int(args.threads),
                verbosity=-1,
            )
            ranker_model.fit(x_all.loc[train_idx], rank_y_all.loc[train_idx], group=ranker_groups(train_frame))
            model = ranker_model
        if args.model_kind in {"regressor", "hybrid"}:
            regressor_model = lgb.LGBMRegressor(
                objective="regression_l1" if args.objective == "l1" else "regression",
                n_estimators=int(args.n_estimators),
                learning_rate=float(args.learning_rate),
                num_leaves=int(args.num_leaves),
                max_depth=int(args.max_depth),
                min_child_samples=int(args.min_child_samples),
                subsample=float(args.subsample),
                colsample_bytree=float(args.colsample_bytree),
                reg_alpha=float(args.reg_alpha),
                reg_lambda=float(args.reg_lambda),
                random_state=20260613 + year + horizon,
                n_jobs=int(args.threads),
                verbosity=-1,
            )
            regressor_model.fit(x_all.loc[train_idx], y_all.loc[train_idx])
            model = regressor_model if args.model_kind == "regressor" else {"ranker": ranker_model, "regressor": regressor_model}
        crash_model = None
        if args.crash_filter != "none" and crash_y_all is not None:
            crash_train_y = crash_y_all.loc[train_idx]
            if crash_train_y.nunique(dropna=True) >= 2:
                crash_model = lgb.LGBMClassifier(
                    objective="binary",
                    n_estimators=int(args.crash_n_estimators),
                    learning_rate=float(args.learning_rate),
                    num_leaves=int(args.num_leaves),
                    max_depth=int(args.max_depth),
                    min_child_samples=int(args.min_child_samples),
                    subsample=float(args.subsample),
                    colsample_bytree=float(args.colsample_bytree),
                    reg_alpha=float(args.reg_alpha),
                    reg_lambda=float(args.reg_lambda),
                    random_state=20260701 + year + horizon,
                    n_jobs=int(args.threads),
                    verbosity=-1,
                )
                crash_model.fit(x_all.loc[train_idx], crash_train_y)
        breakout_model = None
        if args.breakout_filter != "none" and breakout_y_all is not None:
            breakout_train_y = breakout_y_all.loc[train_idx]
            if breakout_train_y.nunique(dropna=True) >= 2:
                breakout_model = lgb.LGBMClassifier(
                    objective="binary",
                    n_estimators=int(args.breakout_n_estimators),
                    learning_rate=float(args.learning_rate),
                    num_leaves=int(args.num_leaves),
                    max_depth=int(args.max_depth),
                    min_child_samples=int(args.min_child_samples),
                    subsample=float(args.subsample),
                    colsample_bytree=float(args.colsample_bytree),
                    reg_alpha=float(args.reg_alpha),
                    reg_lambda=float(args.reg_lambda),
                    random_state=20260801 + year + horizon,
                    n_jobs=int(args.threads),
                    verbosity=-1,
                )
                breakout_model.fit(x_all.loc[train_idx], breakout_train_y)
        fold = sample.loc[test_mask].copy()
        if args.model_kind == "hybrid":
            pred_return = model["regressor"].predict(x_all.loc[test_mask]).astype(float)
            rank_score = model["ranker"].predict(x_all.loc[test_mask]).astype(float)
        else:
            pred_return = model.predict(x_all.loc[test_mask]).astype(float)
            rank_score = pred_return
        fold["pred_return"] = pred_return
        fold["rank_score_raw"] = rank_score if args.model_kind in {"ranker", "hybrid"} else pred_return * 100.0
        fold["model_score"] = fold["rank_score_raw"]
        fold["realized_return"] = fold[eval_target].astype(float)
        fold["future_return"] = fold[f"future_return_{horizon}d"].astype(float)
        fold["future_max_return"] = fold[f"future_max_return_{horizon}d"].astype(float)
        fold["future_drawdown"] = fold[f"future_drawdown_{horizon}d"].astype(float)
        fold["exit_date"] = fold[f"exit_date_{horizon}d"].fillna("").astype(str)
        if crash_model is not None:
            fold["crash_prob"] = crash_model.predict_proba(x_all.loc[test_mask])[:, 1].astype(float)
        else:
            fold["crash_prob"] = 0.0
        if breakout_model is not None:
            fold["breakout_prob"] = breakout_model.predict_proba(x_all.loc[test_mask])[:, 1].astype(float)
        else:
            fold["breakout_prob"] = 0.0
        if args.score_mode == "blended":
            fold["model_score"] = blend_model_score(fold, args)
        predictions.append(fold)
        fold_dates = fold["trade_date"].astype(str).unique().tolist()
        year_evals = [
            evaluate_predictions(fold, top_n, horizon, "all", threshold, capital_tranche_fraction=args.capital_tranche_fraction, all_dates=fold_dates)
            for top_n in args.top_n_values
            for threshold in args.min_pred_return_values
        ]
        fold_metrics.append({
            "year": int(year),
            "rows": int(len(fold)),
            "train_rows": int(len(train_idx)),
            "target_mean": safe_float(y_all.loc[train_idx].mean()),
            "baseline_return": safe_float(fold["realized_return"].mean()),
            "best_top_n": max(year_evals, key=lambda item: item["compound_return"]),
        })
        progress_log(
            "fold_done",
            run_id=args.run_id,
            scope=scope,
            horizon=horizon,
            year=year,
            fold=fold_no,
            total_folds=len(test_years),
            rows=len(fold),
            best_compound_return=fold_metrics[-1]["best_top_n"].get("compound_return"),
            best_avg_return=fold_metrics[-1]["best_top_n"].get("avg_return"),
        )
        importance_model = model["ranker"] if isinstance(model, dict) else model
        importance += pd.Series(importance_model.feature_importances_, index=feature_cols)
        models.append(model)
        if crash_model is not None:
            crash_models.append(crash_model)
        if breakout_model is not None:
            breakout_models.append(breakout_model)

    if not predictions:
        progress_log("scope_horizon_skipped", run_id=args.run_id, scope=scope, horizon=horizon, reason="no_walk_forward_predictions")
        return {"scope": scope, "horizon": horizon, "status": "skipped", "reason": "no walk-forward predictions"}

    progress_log("predictions_concat_start", run_id=args.run_id, scope=scope, horizon=horizon, folds=len(predictions))
    pred = pd.concat(predictions, ignore_index=True).sort_values(["trade_date", "model_score"], ascending=[True, False])
    latest_date = str(sample["trade_date"].max())
    latest_pool = sample[sample["trade_date"] == latest_date].copy()
    if models and not latest_pool.empty:
        latest_model = models[-1]
        latest_x = latest_pool[feature_cols].astype(float)
        if isinstance(latest_model, dict):
            latest_pool["pred_return"] = latest_model["regressor"].predict(latest_x).astype(float)
            latest_pool["rank_score_raw"] = latest_model["ranker"].predict(latest_x).astype(float)
        else:
            latest_pool["pred_return"] = latest_model.predict(latest_x).astype(float)
            latest_pool["rank_score_raw"] = latest_pool["pred_return"] if args.model_kind == "ranker" else latest_pool["pred_return"] * 100.0
        latest_pool["model_score"] = latest_pool["rank_score_raw"]
        if crash_models:
            latest_pool["crash_prob"] = crash_models[-1].predict_proba(latest_x)[:, 1].astype(float)
        else:
            latest_pool["crash_prob"] = 0.0
        if breakout_models:
            latest_pool["breakout_prob"] = breakout_models[-1].predict_proba(latest_x)[:, 1].astype(float)
        else:
            latest_pool["breakout_prob"] = 0.0
        if args.score_mode == "blended":
            latest_pool["model_score"] = blend_model_score(latest_pool, args)
        latest_pool["realized_return"] = latest_pool[eval_target].fillna(0.0).astype(float)
        latest_pool["future_return"] = latest_pool[f"future_return_{horizon}d"].fillna(0.0).astype(float)
        latest_pool["future_max_return"] = latest_pool[f"future_max_return_{horizon}d"].fillna(0.0).astype(float)
        latest_pool["future_drawdown"] = latest_pool[f"future_drawdown_{horizon}d"].fillna(0.0).astype(float)
        latest_pool["exit_date"] = latest_pool[f"exit_date_{horizon}d"].fillna("").astype(str)
        latest_pool["is_latest"] = 1
    pred["is_latest"] = 0
    out_pred = pd.concat([pred, latest_pool], ignore_index=True, sort=False) if not latest_pool.empty else pred
    all_eval_dates = pred["trade_date"].astype(str).unique().tolist()
    model_ic_stats = rank_ic_stats(pred)
    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)
    if (min_rank_ic > 0 and safe_float(model_ic_stats.get("rank_ic")) < min_rank_ic) or (
        min_rank_ic_days > 0 and int(model_ic_stats.get("rank_ic_days", 0) or 0) < min_rank_ic_days
    ):
        progress_log(
            "evaluation_skipped_by_rank_ic_gate",
            run_id=args.run_id,
            scope=scope,
            horizon=horizon,
            rank_ic=model_ic_stats.get("rank_ic"),
            rank_ic_days=model_ic_stats.get("rank_ic_days"),
            min_rank_ic=min_rank_ic,
            min_rank_ic_days=min_rank_ic_days,
        )
        return {
            "scope": scope,
            "horizon": int(horizon),
            "status": "skipped",
            "reason": "rank_ic_gate",
            "rows": int(len(sample)),
            "test_rows": int(len(pred)),
            "test_start": str(pred["trade_date"].min()),
            "test_end": str(pred["trade_date"].max()),
            "latest_date": latest_date,
            "latest_count": int(len(latest_pool)),
            "folds": fold_metrics,
            "evaluations": [],
            "best_eval": model_ic_stats,
            "gate_pass_count": 0,
            "predictions": out_pred,
            "importance": importance / max(len(models), 1),
            "model": None,
        }
    evaluations = []
    eval_segments = evaluation_segments_for_scope(scope)
    eval_base_total = (
        len(args.min_pred_return_values)
        * len(args.min_market_up_ratio_values)
        * len(args.min_market_ret5_values)
        * len(args.min_market_ret20_values)
        * len(args.min_market_amount_chg5_values)
        * len(args.min_market_volatility20_values)
        * len(args.max_market_drawdown20_values)
        * len(args.max_market_volatility20_values)
        * len(args.min_turnover_rate_values)
        * len(args.min_industry_up_ratio_values)
        * len(args.min_small_up_ratio_values)
        * len(args.min_small_limit_up_ratio_values)
        * len(args.min_small_near_limit_up_ratio_values)
        * len(args.min_small_amount_chg5_values)
        * len(args.min_small_rs_market20_values)
        * len(args.min_small_breakout_high20_ratio_values)
        * len(args.max_crash_prob_values)
        * len(args.min_daily_top_score_values)
        * len(args.min_daily_top_pred_return_values)
        * len(args.max_daily_top_crash_prob_values)
        * len(args.execution_stop_loss_values)
        * len(args.execution_take_profit_values)
        * len(args.position_weighting_values)
        * len(args.capital_scale_mode_values)
        * len(eval_segments)
    )
    eval_record_total = eval_base_total * len(args.top_n_values) * len(args.capital_tranche_fraction_values)
    eval_started_at = time.monotonic()
    progress_log(
        "evaluation_start",
        run_id=args.run_id,
        scope=scope,
        horizon=horizon,
        pred_rows=len(pred),
        dates=len(all_eval_dates),
        base_combinations=eval_base_total,
        evaluation_records=eval_record_total,
        segments=eval_segments,
        capital_fractions=args.capital_tranche_fraction_values,
        max_crash_prob=args.max_crash_prob_values,
        position_weighting=args.position_weighting_values,
        capital_scale_modes=args.capital_scale_mode_values,
        min_daily_top_score=args.min_daily_top_score_values,
        min_daily_top_pred_return=args.min_daily_top_pred_return_values,
        max_daily_top_crash_prob=args.max_daily_top_crash_prob_values,
    )
    eval_base_done = 0
    gate_pass_so_far = 0
    eval_grid = product(
        args.min_pred_return_values,
        args.min_market_up_ratio_values,
        args.min_market_ret5_values,
        args.min_market_ret20_values,
        args.min_market_amount_chg5_values,
        args.min_market_volatility20_values,
        args.max_market_drawdown20_values,
        args.max_market_volatility20_values,
        args.min_turnover_rate_values,
        args.min_industry_up_ratio_values,
        args.min_small_up_ratio_values,
        args.min_small_limit_up_ratio_values,
        args.min_small_near_limit_up_ratio_values,
        args.min_small_amount_chg5_values,
        args.min_small_rs_market20_values,
        args.min_small_breakout_high20_ratio_values,
        args.max_crash_prob_values,
        args.min_daily_top_score_values,
        args.min_daily_top_pred_return_values,
        args.max_daily_top_crash_prob_values,
        args.execution_stop_loss_values,
        args.execution_take_profit_values,
        args.position_weighting_values,
        args.capital_scale_mode_values,
        eval_segments,
    )
    for (
        threshold,
        market_up_threshold,
        market_ret5_threshold,
        market_ret20_threshold,
        market_amount_threshold,
        min_market_volatility_threshold,
        market_drawdown_threshold,
        market_volatility_threshold,
        min_turnover_threshold,
        industry_up_threshold,
        small_up_threshold,
        small_limit_threshold,
        small_near_limit_threshold,
        small_amount_threshold,
        small_rs_threshold,
        small_breakout_threshold,
        crash_threshold,
        daily_score_threshold,
        daily_pred_threshold,
        daily_crash_threshold,
        execution_stop_loss,
        execution_take_profit,
        position_weighting,
        capital_scale_mode,
        segment,
    ) in eval_grid:
        batch = evaluate_pool_many_top_capital(
            pred,
            args.top_n_values,
            horizon,
            segment,
            threshold,
            market_up_threshold,
            market_ret5_threshold,
            market_ret20_threshold,
            market_amount_threshold,
            min_market_volatility_threshold,
            market_drawdown_threshold,
            market_volatility_threshold,
            min_turnover_threshold,
            industry_up_threshold,
            small_up_threshold,
            small_limit_threshold,
            small_near_limit_threshold,
            small_amount_threshold,
            small_rs_threshold,
            small_breakout_threshold,
            crash_threshold,
            daily_score_threshold,
            daily_pred_threshold,
            daily_crash_threshold,
            execution_stop_loss,
            execution_take_profit,
            position_weighting,
            capital_scale_mode,
            args.capital_tranche_fraction_values,
            args.max_gross_exposure,
            all_eval_dates,
            min_rank_ic=args.min_rank_ic,
            min_rank_ic_days=args.min_rank_ic_days,
        )
        evaluations.extend(batch)
        gate_pass_so_far += sum(1 for item in batch if evaluation_gate_ok(item, args))
        eval_base_done += 1
        if eval_base_done == 1 or eval_base_done == eval_base_total or eval_base_done % int(args.progress_every_evals) == 0:
            elapsed = max(time.monotonic() - eval_started_at, 0.001)
            bases_per_sec = eval_base_done / elapsed
            eta_seconds = (eval_base_total - eval_base_done) / bases_per_sec if bases_per_sec > 0 else None
            progress_best = select_best_challenger(evaluations, args)
            progress_score = arena_score_components(progress_best, args) if progress_best else {}
            progress_log(
                "evaluation_progress",
                run_id=args.run_id,
                scope=scope,
                horizon=horizon,
                done=eval_base_done,
                total=eval_base_total,
                records_done=eval_base_done * len(args.top_n_values) * len(args.capital_tranche_fraction_values),
                records_total=eval_record_total,
                elapsed_seconds=round(elapsed, 1),
                eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
                bases_per_sec=round(bases_per_sec, 3),
                gate_pass_so_far=gate_pass_so_far,
                best_capital_annual_return=progress_best.get("capital_annual_return"),
                best_capital_max_drawdown=progress_best.get("capital_max_drawdown"),
                best_capital_sharpe=progress_best.get("capital_sharpe"),
                best_rank_ic=progress_best.get("rank_ic"),
                best_rank_ic_days=progress_best.get("rank_ic_days"),
                best_challenger_score=progress_score.get("score"),
                best_challenger=champion_payload(progress_best),
            )
    if not evaluations:
        progress_log(
            "evaluation_skipped_by_rank_ic_gate",
            run_id=args.run_id,
            scope=scope,
            horizon=horizon,
            min_rank_ic=args.min_rank_ic,
            min_rank_ic_days=args.min_rank_ic_days,
        )
        return {
            "scope": scope,
            "horizon": int(horizon),
            "status": "skipped",
            "reason": "rank_ic_gate",
            "rows": int(len(sample)),
            "test_rows": int(len(pred)),
            "test_start": str(pred["trade_date"].min()),
            "test_end": str(pred["trade_date"].max()),
            "latest_date": latest_date,
            "latest_count": int(len(latest_pool)),
            "folds": fold_metrics,
            "evaluations": [],
            "best_eval": {},
            "gate_pass_count": 0,
            "predictions": out_pred,
            "importance": importance / max(len(models), 1),
            "model": None,
        }
    best_eval = select_best_challenger(evaluations, args)
    best_score = arena_score_components(best_eval, args)
    gate_pass_count = sum(1 for item in evaluations if evaluation_gate_ok(item, args))
    progress_log(
        "evaluation_done",
        run_id=args.run_id,
        scope=scope,
        horizon=horizon,
        evaluations=len(evaluations),
        gate_pass_count=gate_pass_count,
        best_capital_annual_return=best_eval.get("capital_annual_return"),
        best_capital_max_drawdown=best_eval.get("capital_max_drawdown"),
        best_rank_ic=best_eval.get("rank_ic"),
        best_rank_ic_days=best_eval.get("rank_ic_days"),
        best_challenger_score=best_score.get("score"),
        best_challenger=champion_payload(best_eval),
    )
    return {
        "scope": scope,
        "horizon": int(horizon),
        "status": "success",
        "rows": int(len(sample)),
        "test_rows": int(len(pred)),
        "test_start": str(pred["trade_date"].min()),
        "test_end": str(pred["trade_date"].max()),
        "latest_date": latest_date,
        "latest_count": int(len(latest_pool)),
        "folds": fold_metrics,
        "evaluations": evaluations,
        "best_eval": best_eval,
        "gate_pass_count": gate_pass_count,
        "predictions": out_pred,
        "importance": importance / max(len(models), 1),
        "model": {
            "main": models[-1] if models else None,
            "crash": crash_models[-1] if crash_models else None,
            "breakout": breakout_models[-1] if breakout_models else None,
        } if (crash_models or breakout_models) else (models[-1] if models else None),
    }


def parse_int_list(text: str) -> list[int]:
    out: list[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part)
        if value > 0 and value not in out:
            out.append(value)
    return out


def parse_float_list(text: str) -> list[float]:
    out: list[float] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        value = float(part)
        if value not in out:
            out.append(value)
    return out or [-999.0]


def parse_str_list(text: str) -> list[str]:
    allowed = {"all", "small", "mid", "large"}
    out: list[str] = []
    for part in str(text).split(","):
        value = part.strip()
        if value in allowed and value not in out:
            out.append(value)
    return out or ["all"]


def parse_position_weighting_list(text: str) -> list[str]:
    allowed = {
        "equal",
        "score",
        "breakout",
        "pred",
        "score_cap50",
        "score_cap40",
        "score_cap34",
        "pred_cap50",
        "pred_cap40",
        "breakout_cap50",
    }
    out: list[str] = []
    for part in str(text or "equal").split(","):
        value = part.strip().lower()
        if value in allowed and value not in out:
            out.append(value)
    return out or ["equal"]


def parse_capital_scale_mode_list(text: str) -> list[str]:
    allowed = {
        "none",
        "market",
        "market_soft",
        "market_guarded",
        "market_pulse",
        "market_brake",
        "market_tail_guard",
        "small_ecology",
        "small_brake",
        "small_tail_guard",
        "signal_quality",
        "light_tail_guard",
        "light_signal_guard",
        "overheat_soft",
        "overheat_guard",
        "overheat_signal_guard",
        "signal_tail_guard",
        "attack_signal_guard",
        "hybrid_ecology",
        "hybrid_brake",
        "hybrid_tail_guard",
        "hybrid_tail_guard_plus",
        "attack_ecology",
        "attack_brake",
        "attack_tail_guard",
        "attack_tail_guard_plus",
        "risk_off_market",
        "risk_off_hybrid",
    }
    out: list[str] = []
    for part in str(text or "none").split(","):
        value = part.strip().lower()
        if value in allowed and value not in out:
            out.append(value)
    return out or ["none"]


def evaluation_segments_for_scope(scope: str) -> list[str]:
    if scope == "all":
        return ["all", "small", "mid", "large"]
    return ["all"]


def panel_cache_path(args: argparse.Namespace, horizons: Sequence[int]) -> Path:
    execution_stop_losses = parse_float_list(getattr(args, "execution_stop_loss", "0"))
    execution_take_profits = parse_float_list(getattr(args, "execution_take_profit", "0"))
    payload = {
        "version": PANEL_CACHE_VERSION,
        "start": args.start,
        "end": args.end,
        "horizons": sorted(int(h) for h in horizons),
        "buy_slippage": float(args.buy_slippage),
        "sell_slippage": float(args.sell_slippage),
        "commission": float(args.commission),
        "stamp_tax": float(args.stamp_tax),
        "stop_loss": float(getattr(args, "stop_loss", 0.0) or 0.0),
        "take_profit": float(getattr(args, "take_profit", 0.0) or 0.0),
        "execution_stop_losses": execution_stop_losses,
        "execution_take_profits": execution_take_profits,
        "warmup_days": 260,
        "universe": "main_board_non_st_listed120_amount20000_price250",
        "features": FEATURES,
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    horizon_text = "-".join(str(int(h)) for h in sorted(horizons))
    return Path(args.data_path) / "profit_arena" / "cache" / f"panel_{args.start}_{args.end}_h{horizon_text}_{digest}.parquet"


def load_or_build_panel(args: argparse.Namespace, horizons: Sequence[int]) -> pd.DataFrame:
    cache_path = panel_cache_path(args, horizons)
    if not bool(getattr(args, "no_panel_cache", False)) and cache_path.exists():
        progress_log("panel_cache_hit", run_id=args.run_id, path=str(cache_path))
        return pd.read_parquet(cache_path)
    progress_log("panel_cache_miss", run_id=args.run_id, path=str(cache_path))
    raw = read_market_panel(Path(args.data_path), args.start, args.end, warmup_days=260)
    if raw.empty:
        raise RuntimeError("日线数据为空，无法训练收益擂台模型")
    progress_log("raw_panel_loaded", run_id=args.run_id, rows=len(raw), columns=len(raw.columns))
    data = add_features(
        raw,
        args.start,
        args.end,
        horizons,
        args.buy_slippage,
        args.sell_slippage,
        args.commission,
        args.stamp_tax,
        args.stop_loss,
        args.take_profit,
        parse_float_list(getattr(args, "execution_stop_loss", "0")),
        parse_float_list(getattr(args, "execution_take_profit", "0")),
    )
    if not bool(getattr(args, "no_panel_cache", False)):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        progress_log("panel_cache_write_start", run_id=args.run_id, path=str(cache_path), rows=len(data))
        data.to_parquet(cache_path, index=False, compression="zstd")
        progress_log("panel_cache_write_done", run_id=args.run_id, path=str(cache_path), rows=len(data))
    return data


def rank_labels_by_date(frame: pd.DataFrame, target: str) -> pd.Series:
    pct = frame.groupby("trade_date", sort=False)[target].rank(pct=True, method="first")
    labels = np.select(
        [
            pct <= 0.05,
            pct <= 0.20,
            pct >= 0.95,
            pct >= 0.80,
        ],
        [0, 1, 4, 3],
        default=2,
    )
    return pd.Series(labels, index=frame.index, dtype="int32")


def breakout_labels_by_date(frame: pd.DataFrame, target: str, quantile: float = 0.95) -> pd.Series:
    threshold = float(quantile)
    threshold = min(max(threshold, 0.50), 0.995)
    pct = frame.groupby("trade_date", sort=False)[target].rank(pct=True, method="first")
    return (pct >= threshold).astype("int8")


def blend_model_score(frame: pd.DataFrame, args: argparse.Namespace) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64", index=frame.index)
    base = frame.groupby("trade_date", sort=False)["model_score"].rank(pct=True, method="first")
    pred = frame.groupby("trade_date", sort=False)["pred_return"].rank(pct=True, method="first")
    score = (
        base.astype(float) * float(getattr(args, "rank_score_weight", 1.0))
        + pred.astype(float) * float(getattr(args, "pred_score_weight", 0.25))
    )
    if "breakout_prob" in frame.columns:
        score = score + frame["breakout_prob"].astype(float) * float(getattr(args, "breakout_score_weight", 0.0))
    if "crash_prob" in frame.columns:
        score = score - frame["crash_prob"].astype(float) * float(getattr(args, "crash_score_weight", 0.0))
    return score.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def build_horizon_fusion_result(args: argparse.Namespace, results: list[dict[str, Any]], scope: str, eval_horizon: int) -> dict[str, Any]:
    by_horizon = {
        int(item.get("horizon")): item
        for item in results
        if item.get("status") == "success" and item.get("scope") == scope and isinstance(item.get("predictions"), pd.DataFrame)
    }
    fusion_horizons = [int(value) for value in parse_int_list(getattr(args, "fusion_horizons", "")) if int(value) in by_horizon]
    if int(eval_horizon) not in by_horizon or len(fusion_horizons) < 2:
        return {"scope": scope, "horizon": eval_horizon, "status": "skipped", "reason": "fusion requires eval horizon and at least two trained horizons"}

    base = by_horizon[int(eval_horizon)]["predictions"].copy()
    base = base[base["is_latest"].fillna(0).astype(int) == 0].copy()
    if base.empty:
        return {"scope": scope, "horizon": eval_horizon, "status": "skipped", "reason": "fusion base predictions empty"}
    base = base.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    score_parts: list[pd.Series] = []
    pred_parts: list[pd.Series] = []
    crash_parts: list[pd.Series] = []
    breakout_parts: list[pd.Series] = []
    for horizon in fusion_horizons:
        pred = by_horizon[horizon]["predictions"].copy()
        pred = pred[pred["is_latest"].fillna(0).astype(int) == 0].copy()
        if pred.empty:
            continue
        pred = pred[["trade_date", "ts_code", "model_score", "pred_return", "crash_prob", "breakout_prob"]].rename(columns={
            "model_score": f"model_score_{horizon}d",
            "pred_return": f"pred_return_{horizon}d",
            "crash_prob": f"crash_prob_{horizon}d",
            "breakout_prob": f"breakout_prob_{horizon}d",
        })
        base = base.merge(pred, on=["trade_date", "ts_code"], how="left")
        score_col = f"model_score_{horizon}d"
        pred_col = f"pred_return_{horizon}d"
        crash_col = f"crash_prob_{horizon}d"
        breakout_col = f"breakout_prob_{horizon}d"
        score_parts.append(base.groupby("trade_date", sort=False)[score_col].rank(pct=True, method="first").fillna(0.5))
        pred_parts.append(base.groupby("trade_date", sort=False)[pred_col].rank(pct=True, method="first").fillna(0.5))
        crash_parts.append(pd.to_numeric(base[crash_col], errors="coerce").fillna(0.0))
        breakout_parts.append(pd.to_numeric(base[breakout_col], errors="coerce").fillna(0.0))

    if len(score_parts) < 2:
        return {"scope": scope, "horizon": eval_horizon, "status": "skipped", "reason": "fusion matched fewer than two score parts"}

    score = sum(score_parts) / len(score_parts)
    pred_rank = sum(pred_parts) / len(pred_parts)
    breakout = sum(breakout_parts) / len(breakout_parts)
    crash = pd.concat(crash_parts, axis=1).max(axis=1)
    score = (
        score
        + pred_rank * float(getattr(args, "fusion_pred_score_weight", 0.15))
        + breakout * float(getattr(args, "fusion_breakout_score_weight", 0.25))
        - crash * float(getattr(args, "fusion_crash_score_weight", 0.35))
    )
    pred_cols = [f"pred_return_{h}d" for h in fusion_horizons if f"pred_return_{h}d" in base.columns]
    if pred_cols:
        base["pred_return"] = base[pred_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).mean(axis=1)
    base["breakout_prob"] = breakout
    base["crash_prob"] = crash
    base["model_score"] = score.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    base["is_latest"] = 0

    all_eval_dates = base["trade_date"].astype(str).unique().tolist()
    evaluations: list[dict[str, Any]] = []
    eval_segments = evaluation_segments_for_scope(scope)
    progress_log(
        "fusion_evaluation_start",
        run_id=args.run_id,
        scope=scope,
        eval_horizon=eval_horizon,
        fusion_horizons=fusion_horizons,
        rows=len(base),
        dates=len(all_eval_dates),
    )
    for threshold in args.min_pred_return_values:
        for crash_threshold in args.max_crash_prob_values:
            for execution_take_profit in args.execution_take_profit_values:
                for position_weighting in args.position_weighting_values:
                    for capital_scale_mode in args.capital_scale_mode_values:
                        for segment in eval_segments:
                            evaluations.extend(evaluate_pool_many_top_capital(
                                base,
                                args.top_n_values,
                                int(eval_horizon),
                                segment,
                                threshold,
                                max_crash_prob=crash_threshold,
                                execution_take_profit=execution_take_profit,
                                position_weighting=position_weighting,
                                capital_scale_mode=capital_scale_mode,
                                capital_tranche_fractions=args.capital_tranche_fraction_values,
                                max_gross_exposure=args.max_gross_exposure,
                                all_dates=all_eval_dates,
                                min_rank_ic=args.min_rank_ic,
                                min_rank_ic_days=args.min_rank_ic_days,
                            ))
    if not evaluations:
        return {"scope": scope, "horizon": eval_horizon, "status": "skipped", "reason": "fusion produced no evaluations"}
    best_eval = select_best_challenger(evaluations, args)
    gate_pass_count = sum(1 for item in evaluations if evaluation_gate_ok(item, args))
    progress_log(
        "fusion_evaluation_done",
        run_id=args.run_id,
        scope=scope,
        eval_horizon=eval_horizon,
        evaluations=len(evaluations),
        gate_pass_count=gate_pass_count,
        best_capital_annual_return=best_eval.get("capital_annual_return"),
        best_capital_max_drawdown=best_eval.get("capital_max_drawdown"),
        best_capital_sharpe=best_eval.get("capital_sharpe"),
        best_rank_ic=best_eval.get("rank_ic"),
        best_rank_ic_days=best_eval.get("rank_ic_days"),
    )
    return {
        "scope": scope,
        "horizon": int(eval_horizon),
        "status": "success",
        "rows": int(len(base)),
        "test_rows": int(len(base)),
        "fold_metrics": [],
        "evaluations": evaluations,
        "best_eval": best_eval,
        "gate_pass_count": gate_pass_count,
        "predictions": base,
        "importance": pd.Series(dtype="float64"),
        "model": None,
        "fusion_horizons": fusion_horizons,
    }


def evaluate_prediction_grid(args: argparse.Namespace, pred_input: pd.DataFrame, scope: str, horizon: int) -> dict[str, Any]:
    pred = pred_input.copy()
    if bool(getattr(args, "eval_only_reblend_score", False)) and "rank_score_raw" in pred.columns:
        pred["model_score"] = pd.to_numeric(pred["rank_score_raw"], errors="coerce").fillna(0.0)
        if str(getattr(args, "score_mode", "raw") or "raw").lower() == "blended":
            pred["model_score"] = blend_model_score(pred, args)
        progress_log(
            "eval_only_score_reblended",
            run_id=args.run_id,
            score_mode=getattr(args, "score_mode", "raw"),
            rank_score_weight=getattr(args, "rank_score_weight", None),
            pred_score_weight=getattr(args, "pred_score_weight", None),
            breakout_score_weight=getattr(args, "breakout_score_weight", None),
            crash_score_weight=getattr(args, "crash_score_weight", None),
        )
    if "is_latest" not in pred.columns:
        pred["is_latest"] = 0
    pred["is_latest"] = pd.to_numeric(pred["is_latest"], errors="coerce").fillna(0).astype(int)
    eval_pred = pred[pred["is_latest"] != 1].copy()
    if eval_pred.empty:
        eval_pred = pred.copy()
    eval_pred["trade_date"] = eval_pred["trade_date"].astype(str)
    sort_col = "model_score" if "model_score" in eval_pred.columns else "pred_return"
    eval_pred = eval_pred.sort_values(["trade_date", sort_col], ascending=[True, False]).reset_index(drop=True)
    out_pred = pred.copy()
    out_pred["trade_date"] = out_pred["trade_date"].astype(str)
    latest_rows = out_pred[out_pred["is_latest"] == 1]
    latest_date = str(latest_rows["trade_date"].max()) if not latest_rows.empty else str(eval_pred["trade_date"].max())
    all_eval_dates = eval_pred["trade_date"].astype(str).unique().tolist()
    model_ic_stats = rank_ic_stats(eval_pred)
    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)
    zero_importance = pd.Series(0.0, index=getattr(args, "feature_columns", FEATURES), dtype="float64")
    if (min_rank_ic > 0 and safe_float(model_ic_stats.get("rank_ic")) < min_rank_ic) or (
        min_rank_ic_days > 0 and int(model_ic_stats.get("rank_ic_days", 0) or 0) < min_rank_ic_days
    ):
        progress_log(
            "evaluation_skipped_by_rank_ic_gate",
            run_id=args.run_id,
            scope=scope,
            horizon=horizon,
            rank_ic=model_ic_stats.get("rank_ic"),
            rank_ic_days=model_ic_stats.get("rank_ic_days"),
            min_rank_ic=min_rank_ic,
            min_rank_ic_days=min_rank_ic_days,
        )
        return {
            "scope": scope,
            "horizon": int(horizon),
            "status": "skipped",
            "reason": "rank_ic_gate",
            "rows": int(len(out_pred)),
            "test_rows": int(len(eval_pred)),
            "test_start": str(eval_pred["trade_date"].min()),
            "test_end": str(eval_pred["trade_date"].max()),
            "latest_date": latest_date,
            "latest_count": int(len(latest_rows)),
            "folds": [],
            "evaluations": [],
            "best_eval": model_ic_stats,
            "gate_pass_count": 0,
            "predictions": out_pred,
            "importance": zero_importance,
            "model": None,
        }

    evaluations: list[dict[str, Any]] = []
    eval_segments = evaluation_segments_for_scope(scope)
    eval_base_total = (
        len(args.min_pred_return_values)
        * len(args.min_market_up_ratio_values)
        * len(args.min_market_ret5_values)
        * len(args.min_market_ret20_values)
        * len(args.min_market_amount_chg5_values)
        * len(args.min_market_volatility20_values)
        * len(args.max_market_drawdown20_values)
        * len(args.max_market_volatility20_values)
        * len(args.min_turnover_rate_values)
        * len(args.min_industry_up_ratio_values)
        * len(args.min_small_up_ratio_values)
        * len(args.min_small_limit_up_ratio_values)
        * len(args.min_small_near_limit_up_ratio_values)
        * len(args.min_small_amount_chg5_values)
        * len(args.min_small_rs_market20_values)
        * len(args.min_small_breakout_high20_ratio_values)
        * len(args.max_crash_prob_values)
        * len(args.min_daily_top_score_values)
        * len(args.min_daily_top_pred_return_values)
        * len(args.max_daily_top_crash_prob_values)
        * len(args.execution_stop_loss_values)
        * len(args.execution_take_profit_values)
        * len(args.position_weighting_values)
        * len(args.capital_scale_mode_values)
        * len(eval_segments)
    )
    eval_record_total = eval_base_total * len(args.top_n_values) * len(args.capital_tranche_fraction_values)
    eval_started_at = time.monotonic()
    progress_log(
        "evaluation_start",
        run_id=args.run_id,
        scope=scope,
        horizon=horizon,
        pred_rows=len(eval_pred),
        dates=len(all_eval_dates),
        base_combinations=eval_base_total,
        evaluation_records=eval_record_total,
        segments=eval_segments,
        capital_fractions=args.capital_tranche_fraction_values,
        max_crash_prob=args.max_crash_prob_values,
        position_weighting=args.position_weighting_values,
        capital_scale_modes=args.capital_scale_mode_values,
        min_daily_top_score=args.min_daily_top_score_values,
        min_daily_top_pred_return=args.min_daily_top_pred_return_values,
        max_daily_top_crash_prob=args.max_daily_top_crash_prob_values,
    )
    eval_base_done = 0
    gate_pass_so_far = 0
    eval_grid = product(
        args.min_pred_return_values,
        args.min_market_up_ratio_values,
        args.min_market_ret5_values,
        args.min_market_ret20_values,
        args.min_market_amount_chg5_values,
        args.min_market_volatility20_values,
        args.max_market_drawdown20_values,
        args.max_market_volatility20_values,
        args.min_turnover_rate_values,
        args.min_industry_up_ratio_values,
        args.min_small_up_ratio_values,
        args.min_small_limit_up_ratio_values,
        args.min_small_near_limit_up_ratio_values,
        args.min_small_amount_chg5_values,
        args.min_small_rs_market20_values,
        args.min_small_breakout_high20_ratio_values,
        args.max_crash_prob_values,
        args.min_daily_top_score_values,
        args.min_daily_top_pred_return_values,
        args.max_daily_top_crash_prob_values,
        args.execution_stop_loss_values,
        args.execution_take_profit_values,
        args.position_weighting_values,
        args.capital_scale_mode_values,
        eval_segments,
    )
    for (
        threshold,
        market_up_threshold,
        market_ret5_threshold,
        market_ret20_threshold,
        market_amount_threshold,
        min_market_volatility_threshold,
        market_drawdown_threshold,
        market_volatility_threshold,
        min_turnover_threshold,
        industry_up_threshold,
        small_up_threshold,
        small_limit_threshold,
        small_near_limit_threshold,
        small_amount_threshold,
        small_rs_threshold,
        small_breakout_threshold,
        crash_threshold,
        daily_score_threshold,
        daily_pred_threshold,
        daily_crash_threshold,
        execution_stop_loss,
        execution_take_profit,
        position_weighting,
        capital_scale_mode,
        segment,
    ) in eval_grid:
        batch = evaluate_pool_many_top_capital(
            eval_pred,
            args.top_n_values,
            horizon,
            segment,
            threshold,
            market_up_threshold,
            market_ret5_threshold,
            market_ret20_threshold,
            market_amount_threshold,
            min_market_volatility_threshold,
            market_drawdown_threshold,
            market_volatility_threshold,
            min_turnover_threshold,
            industry_up_threshold,
            small_up_threshold,
            small_limit_threshold,
            small_near_limit_threshold,
            small_amount_threshold,
            small_rs_threshold,
            small_breakout_threshold,
            crash_threshold,
            daily_score_threshold,
            daily_pred_threshold,
            daily_crash_threshold,
            execution_stop_loss,
            execution_take_profit,
            position_weighting,
            capital_scale_mode,
            args.capital_tranche_fraction_values,
            args.max_gross_exposure,
            all_eval_dates,
            min_rank_ic=args.min_rank_ic,
            min_rank_ic_days=args.min_rank_ic_days,
        )
        evaluations.extend(batch)
        gate_pass_so_far += sum(1 for item in batch if evaluation_gate_ok(item, args))
        eval_base_done += 1
        if eval_base_done == 1 or eval_base_done == eval_base_total or eval_base_done % int(args.progress_every_evals) == 0:
            elapsed = max(time.monotonic() - eval_started_at, 0.001)
            bases_per_sec = eval_base_done / elapsed
            eta_seconds = (eval_base_total - eval_base_done) / bases_per_sec if bases_per_sec > 0 else None
            progress_best = select_best_challenger(evaluations, args)
            progress_score = arena_score_components(progress_best, args) if progress_best else {}
            progress_log(
                "evaluation_progress",
                run_id=args.run_id,
                scope=scope,
                horizon=horizon,
                done=eval_base_done,
                total=eval_base_total,
                records_done=eval_base_done * len(args.top_n_values) * len(args.capital_tranche_fraction_values),
                records_total=eval_record_total,
                elapsed_seconds=round(elapsed, 1),
                eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
                bases_per_sec=round(bases_per_sec, 3),
                gate_pass_so_far=gate_pass_so_far,
                best_capital_annual_return=progress_best.get("capital_annual_return"),
                best_capital_max_drawdown=progress_best.get("capital_max_drawdown"),
                best_capital_sharpe=progress_best.get("capital_sharpe"),
                best_rank_ic=progress_best.get("rank_ic"),
                best_rank_ic_days=progress_best.get("rank_ic_days"),
                best_challenger_score=progress_score.get("score"),
                best_challenger=champion_payload(progress_best),
            )
    if not evaluations:
        progress_log(
            "evaluation_skipped_by_rank_ic_gate",
            run_id=args.run_id,
            scope=scope,
            horizon=horizon,
            min_rank_ic=args.min_rank_ic,
            min_rank_ic_days=args.min_rank_ic_days,
        )
        return {
            "scope": scope,
            "horizon": int(horizon),
            "status": "skipped",
            "reason": "rank_ic_gate",
            "rows": int(len(out_pred)),
            "test_rows": int(len(eval_pred)),
            "test_start": str(eval_pred["trade_date"].min()),
            "test_end": str(eval_pred["trade_date"].max()),
            "latest_date": latest_date,
            "latest_count": int(len(latest_rows)),
            "folds": [],
            "evaluations": [],
            "best_eval": {},
            "gate_pass_count": 0,
            "predictions": out_pred,
            "importance": zero_importance,
            "model": None,
        }
    best_eval = select_best_challenger(evaluations, args)
    best_score = arena_score_components(best_eval, args)
    gate_pass_count = sum(1 for item in evaluations if evaluation_gate_ok(item, args))
    progress_log(
        "evaluation_done",
        run_id=args.run_id,
        scope=scope,
        horizon=horizon,
        evaluations=len(evaluations),
        gate_pass_count=gate_pass_count,
        best_capital_annual_return=best_eval.get("capital_annual_return"),
        best_capital_max_drawdown=best_eval.get("capital_max_drawdown"),
        best_rank_ic=best_eval.get("rank_ic"),
        best_rank_ic_days=best_eval.get("rank_ic_days"),
        best_challenger_score=best_score.get("score"),
        best_challenger=champion_payload(best_eval),
    )
    return {
        "scope": scope,
        "horizon": int(horizon),
        "status": "success",
        "rows": int(len(out_pred)),
        "test_rows": int(len(eval_pred)),
        "test_start": str(eval_pred["trade_date"].min()),
        "test_end": str(eval_pred["trade_date"].max()),
        "latest_date": latest_date,
        "latest_count": int(len(latest_rows)),
        "folds": [],
        "evaluations": evaluations,
        "best_eval": best_eval,
        "gate_pass_count": gate_pass_count,
        "predictions": out_pred,
        "importance": zero_importance,
        "model": None,
    }


def ranker_groups(frame: pd.DataFrame) -> list[int]:
    return [int(size) for size in frame.groupby("trade_date", sort=False).size().tolist()]


def evaluation_gate_ok(item: dict[str, Any], args: argparse.Namespace) -> bool:
    min_trades = int(getattr(args, "selection_min_trades", 0) or 0)
    if min_trades > 0 and int(item.get("trade_count", 0) or 0) < min_trades:
        return False
    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    if min_rank_ic > 0 and safe_float(item.get("rank_ic")) < min_rank_ic:
        return False
    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)
    if min_rank_ic_days > 0 and int(item.get("rank_ic_days", 0) or 0) < min_rank_ic_days:
        return False
    min_trade_years = int(getattr(args, "selection_min_trade_years", 0) or 0)
    if min_trade_years > 0 and int(item.get("trade_years", 0) or 0) < min_trade_years:
        return False
    min_capital_annual_return = float(getattr(args, "min_capital_annual_return", 0.0) or 0.0)
    if min_capital_annual_return > 0 and safe_float(item.get("capital_annual_return")) < min_capital_annual_return:
        return False
    min_capital_sharpe = float(getattr(args, "min_capital_sharpe", 0.0) or 0.0)
    if min_capital_sharpe > 0 and safe_float(item.get("capital_sharpe")) < min_capital_sharpe:
        return False
    max_capital_drawdown = float(getattr(args, "max_capital_drawdown", 0.0) or 0.0)
    if max_capital_drawdown < 0 and safe_float(item.get("capital_max_drawdown")) < max_capital_drawdown:
        return False
    return True


def hard_gate_failures(item: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []
    min_trades = int(getattr(args, "selection_min_trades", 0) or 0)
    if min_trades > 0 and int(item.get("trade_count", 0) or 0) < min_trades:
        failures.append("min_trades")
    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    if min_rank_ic > 0 and safe_float(item.get("rank_ic")) < min_rank_ic:
        failures.append("min_rank_ic")
    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)
    if min_rank_ic_days > 0 and int(item.get("rank_ic_days", 0) or 0) < min_rank_ic_days:
        failures.append("min_rank_ic_days")
    min_trade_years = int(getattr(args, "selection_min_trade_years", 0) or 0)
    if min_trade_years > 0 and int(item.get("trade_years", 0) or 0) < min_trade_years:
        failures.append("min_trade_years")
    min_capital_annual_return = float(getattr(args, "min_capital_annual_return", 0.0) or 0.0)
    if min_capital_annual_return > 0 and safe_float(item.get("capital_annual_return")) < min_capital_annual_return:
        failures.append("min_capital_annual_return")
    min_capital_sharpe = float(getattr(args, "min_capital_sharpe", 0.0) or 0.0)
    if min_capital_sharpe > 0 and safe_float(item.get("capital_sharpe")) < min_capital_sharpe:
        failures.append("min_capital_sharpe")
    max_capital_drawdown = float(getattr(args, "max_capital_drawdown", 0.0) or 0.0)
    if max_capital_drawdown < 0 and safe_float(item.get("capital_max_drawdown")) < max_capital_drawdown:
        failures.append("max_capital_drawdown")
    return failures


def annual_return_bucket_score(annual: float) -> float:
    if annual < 0.05:
        return 0.0
    if annual < 0.10:
        return 20.0
    if annual < 0.15:
        return 40.0
    if annual < 0.20:
        return 60.0
    if annual < 0.30:
        return 80.0
    if annual < 0.40:
        return 90.0
    if annual <= 0.60:
        return 95.0
    return 100.0


def calmar_bucket_score(calmar: float) -> float:
    if calmar < 0.5:
        return 0.0
    if calmar < 1.0:
        return 30.0
    if calmar < 1.5:
        return 60.0
    if calmar < 2.0:
        return 80.0
    if calmar < 2.5:
        return 90.0
    if calmar < 3.0:
        return 95.0
    return 100.0


def rank_ic_bucket_score(rank_ic: float) -> float:
    if rank_ic < 0.01:
        return 0.0
    if rank_ic < 0.03:
        return 30.0
    if rank_ic < 0.05:
        return 50.0
    if rank_ic < 0.08:
        return 70.0
    if rank_ic < 0.10:
        return 85.0
    if rank_ic < 0.12:
        return 95.0
    return 100.0


def sharpe_bucket_score(sharpe: float) -> float:
    if sharpe < 0.5:
        return 0.0
    if sharpe < 0.8:
        return 40.0
    if sharpe < 1.0:
        return 40.0
    if sharpe < 1.2:
        return 60.0
    if sharpe < 1.5:
        return 75.0
    if sharpe < 2.0:
        return 90.0
    return 100.0


def arena_score_components(item: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    annual = safe_float(item.get("capital_annual_return"))
    drawdown = safe_float(item.get("capital_max_drawdown"))
    sharpe = safe_float(item.get("capital_sharpe"))
    rank_ic = safe_float(item.get("rank_ic"))
    trade_years = int(item.get("trade_years", 0) or 0)
    trade_count = int(item.get("trade_count", 0) or 0)
    rank_ic_days = int(item.get("rank_ic_days", 0) or 0)
    yearly_items = [year for year in (item.get("yearly") or []) if isinstance(year, dict)]
    yearly_trade_years = len(yearly_items)
    positive_years = sum(1 for year in yearly_items if safe_float(year.get("avg_return")) > 0)
    negative_years = sum(1 for year in yearly_items if safe_float(year.get("avg_return")) < 0)
    sparse_years = sum(1 for year in yearly_items if int(year.get("trade_count", 0) or 0) < 20)
    worst_year_drawdown = min((safe_float(year.get("max_drawdown")) for year in yearly_items), default=0.0)
    worst_year_avg_return = min((safe_float(year.get("avg_return")) for year in yearly_items), default=0.0)
    yearly_compounds = [max(safe_float(year.get("compound_return")), 0.0) for year in yearly_items]
    total_positive_compound = sum(yearly_compounds)
    top_year_compound_share = max(yearly_compounds, default=0.0) / total_positive_compound if total_positive_compound > 0 else 0.0

    target_annual = max(float(getattr(args, "min_capital_annual_return", 0.0) or 0.0), 0.50)
    if target_annual <= 0:
        target_annual = 0.50
    target_sharpe = max(float(getattr(args, "min_capital_sharpe", 0.0) or 0.0), 1.50)
    if target_sharpe <= 0:
        target_sharpe = 1.50
    target_rank_ic = max(float(getattr(args, "min_rank_ic", 0.0) or 0.0), 0.08)
    if target_rank_ic <= 0:
        target_rank_ic = 0.08
    target_drawdown = abs(float(getattr(args, "max_capital_drawdown", 0.0) or 0.20))
    if target_drawdown <= 0:
        target_drawdown = 0.20
    calmar = annual / abs(drawdown) if drawdown < 0 else (annual / 1e-9 if annual > 0 else 0.0)
    target_calmar = target_annual / target_drawdown

    annual_score = annual_return_bucket_score(annual)
    calmar_score = calmar_bucket_score(calmar)
    rank_ic_score = rank_ic_bucket_score(rank_ic)
    sharpe_score = sharpe_bucket_score(sharpe)
    score = annual_score * 0.40 + calmar_score * 0.30 + rank_ic_score * 0.20 + sharpe_score * 0.10
    penalties: dict[str, float] = {}
    gate_names = [
        "min_capital_annual_return",
        "min_capital_sharpe",
        "max_capital_drawdown",
        "min_rank_ic",
        "min_rank_ic_days",
        "min_trade_years",
        "min_trades",
    ]

    min_capital_annual_return = float(getattr(args, "min_capital_annual_return", 0.0) or 0.0)
    if min_capital_annual_return > 0 and annual < min_capital_annual_return:
        penalties["min_capital_annual_return"] = 0.0

    min_capital_sharpe = float(getattr(args, "min_capital_sharpe", 0.0) or 0.0)
    if min_capital_sharpe > 0 and sharpe < min_capital_sharpe:
        penalties["min_capital_sharpe"] = 0.0

    max_capital_drawdown = float(getattr(args, "max_capital_drawdown", 0.0) or 0.0)
    if max_capital_drawdown < 0 and drawdown < max_capital_drawdown:
        penalties["max_capital_drawdown"] = 0.0

    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    if min_rank_ic > 0 and rank_ic < min_rank_ic:
        penalties["min_rank_ic"] = 0.0

    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)
    if min_rank_ic_days > 0 and rank_ic_days < min_rank_ic_days:
        penalties["min_rank_ic_days"] = 0.0

    min_trade_years = int(getattr(args, "selection_min_trade_years", 0) or 0)
    if min_trade_years > 0 and trade_years < min_trade_years:
        penalties["min_trade_years"] = 0.0

    min_trades = int(getattr(args, "selection_min_trades", 0) or 0)
    if min_trades > 0 and trade_count < min_trades:
        penalties["min_trades"] = 0.0

    passed_gates = [name for name in gate_names if name not in penalties]
    failures = hard_gate_failures(item, args)
    if not failures:
        arena_tier = 3
        arena_tier_name = "strict_champion"
    elif set(failures) == {"min_capital_annual_return"}:
        arena_tier = 2
        arena_tier_name = "strict_risk_incumbent"
    elif (
        annual >= 0.30
        and drawdown >= -0.35
        and trade_years >= int(getattr(args, "selection_min_trade_years", 0) or 0)
        and trade_count >= int(getattr(args, "selection_min_trades", 0) or 0)
    ):
        arena_tier = 1
        arena_tier_name = "attack_watchlist"
    else:
        arena_tier = 0
        arena_tier_name = "rejected"
    return {
        "score": safe_float(score),
        "arena_tier": arena_tier,
        "arena_tier_name": arena_tier_name,
        "raw": {
            "capital_annual_return": annual,
            "capital_max_drawdown": drawdown,
            "capital_sharpe": sharpe,
            "rank_ic": rank_ic,
            "trade_years": trade_years,
            "trade_count": trade_count,
            "rank_ic_days": rank_ic_days,
            "calmar": safe_float(calmar),
        },
        "score_formula": {
            "name": "weighted_annual_bucket_calmar_rankic_sharpe",
            "score": "40% * annual_bucket_score + 30% * calmar_bucket_score + 20% * rank_ic_bucket_score + 10% * sharpe_bucket_score",
            "annual_score_method": "<5%=0, 5%-10%=20, 10%-15%=40, 15%-20%=60, 20%-30%=80, 30%-40%=90, 40%-60%=95, >60%=100",
            "calmar_score_method": "<0.5=0, 0.5-1.0=30, 1.0-1.5=60, 1.5-2.0=80, 2.0-2.5=90, 2.5-3.0=95, >=3.0=100",
            "rank_ic_score_method": "<0.01=0, 0.01-0.03=30, 0.03-0.05=50, 0.05-0.08=70, 0.08-0.10=85, 0.10-0.12=95, >=0.12=100",
            "sharpe_score_method": "<0.5=0, 0.5-1.0=40, 1.0-1.2=60, 1.2-1.5=75, 1.5-2.0=90, >=2.0=100",
            "annual_score": safe_float(annual_score),
            "calmar_score": safe_float(calmar_score),
            "rank_ic_score": safe_float(rank_ic_score),
            "sharpe_score": safe_float(sharpe_score),
            "weights": {
                "annual": 0.40,
                "calmar": 0.30,
                "rank_ic": 0.20,
                "sharpe": 0.10,
            },
            "targets": {
                "annual": safe_float(target_annual),
                "max_drawdown_abs": safe_float(target_drawdown),
                "calmar": safe_float(target_calmar),
                "rank_ic": safe_float(target_rank_ic),
                "sharpe": safe_float(target_sharpe),
            },
        },
        "yearly_diagnostics": {
            "yearly_trade_years": yearly_trade_years,
            "positive_years": positive_years,
            "negative_years": negative_years,
            "sparse_years_lt20_trades": sparse_years,
            "worst_year_drawdown": worst_year_drawdown,
            "worst_year_avg_return": worst_year_avg_return,
            "top_year_compound_share": safe_float(top_year_compound_share),
        },
        "penalties": penalties,
        "passed_gates": passed_gates,
        "hard_gate_ok": not penalties,
        "hard_gate_failures": failures,
    }


def arena_score(item: dict[str, Any], args: argparse.Namespace) -> float:
    return safe_float(arena_score_components(item, args).get("score"))


def arena_score_key(item: dict[str, Any], args: argparse.Namespace) -> tuple[float, float, float, float, float, float]:
    components = arena_score_components(item, args)
    raw = components.get("raw") or {}
    annual = safe_float(raw.get("capital_annual_return"))
    calmar = safe_float(raw.get("calmar"))
    rank_ic = safe_float(raw.get("rank_ic"))
    sharpe = safe_float(raw.get("capital_sharpe"))
    drawdown = safe_float(raw.get("capital_max_drawdown"))
    return (
        safe_float(components.get("score")),
        annual,
        calmar,
        rank_ic,
        sharpe,
        drawdown,
    )


def select_best_evaluation(evaluations: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    candidates = [item for item in evaluations if int(item.get("trade_count", 0)) > 0]
    min_trades = int(getattr(args, "selection_min_trades", 0) or 0)
    if min_trades > 0:
        filtered = [item for item in candidates if int(item.get("trade_count", 0)) >= min_trades]
        if filtered:
            candidates = filtered
    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    if min_rank_ic > 0:
        filtered = [item for item in candidates if safe_float(item.get("rank_ic")) >= min_rank_ic]
        if filtered:
            candidates = filtered
    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)
    if min_rank_ic_days > 0:
        filtered = [item for item in candidates if int(item.get("rank_ic_days", 0) or 0) >= min_rank_ic_days]
        if filtered:
            candidates = filtered
    min_trade_years = int(getattr(args, "selection_min_trade_years", 0) or 0)
    if min_trade_years > 0:
        filtered = [item for item in candidates if int(item.get("trade_years", 0) or 0) >= min_trade_years]
        if filtered:
            candidates = filtered
    min_capital_annual_return = float(getattr(args, "min_capital_annual_return", 0.0) or 0.0)
    if min_capital_annual_return > 0:
        filtered = [item for item in candidates if safe_float(item.get("capital_annual_return")) >= min_capital_annual_return]
        if filtered:
            candidates = filtered
    min_capital_sharpe = float(getattr(args, "min_capital_sharpe", 0.0) or 0.0)
    if min_capital_sharpe > 0:
        filtered = [item for item in candidates if safe_float(item.get("capital_sharpe")) >= min_capital_sharpe]
        if filtered:
            candidates = filtered
    max_capital_drawdown = float(getattr(args, "max_capital_drawdown", 0.0) or 0.0)
    if max_capital_drawdown < 0:
        filtered = [item for item in candidates if safe_float(item.get("capital_max_drawdown")) >= max_capital_drawdown]
        if filtered:
            candidates = filtered
    if not candidates:
        raise RuntimeError("收益擂台没有可选择的评估结果")
    metric = str(getattr(args, "selection_metric", "compound_return") or "compound_return")
    return max(candidates, key=lambda item: safe_float(item.get(metric)))


def select_best_challenger(evaluations: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    if not evaluations:
        return {}
    tradable = [item for item in evaluations if int(item.get("trade_count", 0) or 0) > 0]
    candidates = tradable or evaluations
    return max(candidates, key=lambda item: arena_score_key(item, args))


def select_progress_champion(evaluations: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    return select_best_challenger(evaluations, args)


def collect_evaluations(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        if result.get("status") != "success":
            continue
        scope = result.get("scope")
        horizon = result.get("horizon")
        for item in result.get("evaluations", []) or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("scope", scope)
            row.setdefault("horizon", horizon)
            rows.append(row)
    return rows


def leaderboard_entry(item: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    components = arena_score_components(item, args)
    return {
        "candidate": champion_payload(item),
        "arena_score": components.get("score"),
        "arena_tier": components.get("arena_tier"),
        "arena_tier_name": components.get("arena_tier_name"),
        "hard_gate_ok": components.get("hard_gate_ok"),
        "hard_gate_failures": components.get("hard_gate_failures"),
        "penalties": components.get("penalties"),
        "yearly_diagnostics": components.get("yearly_diagnostics"),
    }


def build_leaderboards(evaluations: list[dict[str, Any]], args: argparse.Namespace, limit: int = 10) -> dict[str, Any]:
    tradable = [item for item in evaluations if int(item.get("trade_count", 0) or 0) > 0]
    min_trades = int(getattr(args, "selection_min_trades", 0) or 0)
    min_trade_years = int(getattr(args, "selection_min_trade_years", 0) or 0)
    min_rank_ic = float(getattr(args, "min_rank_ic", 0.0) or 0.0)
    min_rank_ic_days = int(getattr(args, "min_rank_ic_days", 0) or 0)

    research_base = [
        item for item in tradable
        if int(item.get("trade_count", 0) or 0) >= min_trades
        and int(item.get("trade_years", 0) or 0) >= min_trade_years
        and safe_float(item.get("rank_ic")) >= min_rank_ic
        and int(item.get("rank_ic_days", 0) or 0) >= min_rank_ic_days
    ]
    strict = [item for item in research_base if not hard_gate_failures(item, args)]
    attack = [
        item for item in research_base
        if safe_float(item.get("capital_annual_return")) >= 0.30
        and safe_float(item.get("capital_max_drawdown")) >= -0.35
    ]
    risk_missing_return = [
        item for item in research_base
        if hard_gate_failures(item, args) == ["min_capital_annual_return"]
    ]

    def by_score(item: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        return arena_score_key(item, args)

    def by_annual(item: dict[str, Any]) -> float:
        return safe_float(item.get("capital_annual_return"))

    def by_return_drawdown_ratio(item: dict[str, Any]) -> float:
        annual = safe_float(item.get("capital_annual_return"))
        drawdown = abs(safe_float(item.get("capital_max_drawdown")))
        return annual / max(drawdown, 1e-9)

    return {
        "strict_champion_candidates": [
            leaderboard_entry(item, args) for item in sorted(strict, key=by_score, reverse=True)[:limit]
        ],
        "risk_qualified_missing_return": [
            leaderboard_entry(item, args) for item in sorted(risk_missing_return, key=by_score, reverse=True)[:limit]
        ],
        "attack_watchlist_by_annual": [
            leaderboard_entry(item, args) for item in sorted(attack, key=by_annual, reverse=True)[:limit]
        ],
        "attack_watchlist_by_return_drawdown_ratio": [
            leaderboard_entry(item, args) for item in sorted(attack, key=by_return_drawdown_ratio, reverse=True)[:limit]
        ],
        "top_annual_any_risk": [
            leaderboard_entry(item, args) for item in sorted(tradable, key=by_annual, reverse=True)[:limit]
        ],
    }


def champion_payload(item: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "scope",
        "horizon",
        "segment",
        "top_n",
        "min_pred_return",
        "min_market_volatility20",
        "min_turnover_rate",
        "max_crash_prob",
        "min_daily_top_score",
        "min_daily_top_pred_return",
        "max_daily_top_crash_prob",
        "execution_stop_loss",
        "execution_take_profit",
        "position_weighting",
        "capital_scale_mode",
        "capital_tranche_fraction",
        "trade_count",
        "trade_years",
        "capital_annual_return",
        "capital_max_drawdown",
        "capital_sharpe",
        "rank_ic",
        "rank_ic_days",
    ]
    return {key: item.get(key) for key in keys if key in item}


def comparable_champion_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = champion_payload(item)
    defaults = {
        "segment": "all",
        "min_market_volatility20": -999.0,
        "min_turnover_rate": -999.0,
        "min_daily_top_score": -999.0,
        "capital_scale_mode": "none",
    }
    for key, value in defaults.items():
        payload.setdefault(key, value)
    numeric_keys = {
        "horizon",
        "top_n",
        "min_pred_return",
        "min_market_volatility20",
        "min_turnover_rate",
        "max_crash_prob",
        "min_daily_top_score",
        "min_daily_top_pred_return",
        "max_daily_top_crash_prob",
        "execution_stop_loss",
        "execution_take_profit",
        "capital_tranche_fraction",
        "trade_count",
        "trade_years",
        "capital_annual_return",
        "capital_max_drawdown",
        "capital_sharpe",
        "rank_ic",
        "rank_ic_days",
    }
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in numeric_keys:
            normalized[key] = round(safe_float(value), 12)
        else:
            normalized[key] = value
    return normalized


def pct_text(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return "-"
    if not math.isfinite(num):
        return "-"
    return f"{num * 100:.2f}%"


def notify_arena_wechat(event: str, args: argparse.Namespace, champion: dict[str, Any], score: float, version: int, summary_path: Path) -> bool:
    if send_wechat is None:
        progress_log("arena_wechat_notify_skipped", run_id=args.run_id, notify_event=event, reason="notifier_unavailable")
        return False
    best = champion_payload(champion)
    components = arena_score_components(champion, args)
    qualification_status = "最终达标" if int(components.get("arena_tier", 0) or 0) >= 3 else "当前最优"
    title = f"收益擂台{qualification_status}擂主复验通过"
    content = "\n".join([
        f"## {title}",
        f"> 擂台：{getattr(args, 'arena_name', 'default')}",
        f"> 版本：v{version}",
        f"> run_id：{args.run_id}",
        f"> 分数：{score:.4f}",
        f"> 状态：{components.get('arena_tier_name')} / {qualification_status}",
        "",
        f"- 年化：{pct_text(best.get('capital_annual_return'))}",
        f"- 最大回撤：{pct_text(best.get('capital_max_drawdown'))}",
        f"- Sharpe：{safe_float(best.get('capital_sharpe')):.2f}",
        f"- RankIC：{safe_float(best.get('rank_ic')):.4f} / {int(best.get('rank_ic_days', 0) or 0)}天",
        f"- 配置：h{best.get('horizon')} Top{best.get('top_n')} {best.get('position_weighting')} {best.get('capital_scale_mode')} fraction={best.get('capital_tranche_fraction')}",
        f"- summary：{summary_path}",
    ])
    ok = bool(send_wechat(content))
    progress_log("arena_wechat_notify_done", run_id=args.run_id, notify_event=event, ok=ok)
    return ok


def arena_champion_path(args: argparse.Namespace) -> Path:
    arena_name = str(getattr(args, "arena_name", "default") or "default")
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in arena_name)
    return Path(args.data_path) / "profit_arena" / f"arena_champion_{safe_name}.json"


def arena_history_path(args: argparse.Namespace) -> Path:
    arena_name = str(getattr(args, "arena_name", "default") or "default")
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in arena_name)
    return Path(args.data_path) / "profit_arena" / f"arena_history_{safe_name}.jsonl"


def load_arena_champion(args: argparse.Namespace) -> dict[str, Any] | None:
    path = arena_champion_path(args)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        progress_log("arena_champion_load_error", run_id=args.run_id, path=str(path), error=str(exc))
        return None


def next_arena_challenge_version(args: argparse.Namespace) -> int:
    path = arena_history_path(args)
    if not path.exists():
        return 1
    last_version = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                last_version = max(last_version, int(payload.get("challenge_version", 0) or 0))
    except Exception as exc:
        progress_log("arena_history_read_error", run_id=args.run_id, path=str(path), error=str(exc))
    return last_version + 1


def append_arena_history(args: argparse.Namespace, record: dict[str, Any]) -> None:
    path = arena_history_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def update_arena_champion(
    args: argparse.Namespace,
    challenger: dict[str, Any],
    summary_path: Path,
    validation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = arena_champion_path(args)
    incumbent = load_arena_champion(args)
    challenge_version = next_arena_challenge_version(args)
    challenger_payload = champion_payload(challenger)
    challenger_components = arena_score_components(challenger, args)
    challenger_score = safe_float(challenger_components.get("score"))
    challenger_key = arena_score_key(challenger, args)
    incumbent_components = (incumbent or {}).get("arena_score_components") or {}
    if incumbent and not incumbent_components.get("arena_tier_name") and isinstance(incumbent.get("best"), dict):
        incumbent_components = arena_score_components(incumbent["best"], args)
    incumbent_score = safe_float((incumbent or {}).get("arena_score"), default=-1e18)
    incumbent_key = arena_score_key((incumbent or {}).get("best") or {}, args) if incumbent else (-1e18, -1e18, -1e18, -1e18, -1e18, -1e18)
    incumbent_tier = int(incumbent_components.get("arena_tier", 0) or 0) if incumbent else -1
    challenger_tier = int(challenger_components.get("arena_tier", 0) or 0)
    min_improvement = float(getattr(args, "champion_min_improvement", 0.0) or 0.0)
    challenger_qualification_status = "qualified" if challenger_tier >= 3 else "provisional"
    challenger_champion_type = "qualified_champion" if challenger_tier >= 3 else "current_best"
    incumbent_qualification_status = (incumbent or {}).get("qualification_status")
    incumbent_champion_type = (incumbent or {}).get("champion_type")
    improved = (
        incumbent is None
        or challenger_score > incumbent_score + min_improvement
        or (abs(challenger_score - incumbent_score) <= max(1e-9, abs(incumbent_score) * 1e-12) and challenger_key > incumbent_key)
    )
    result = {
        "arena_name": str(getattr(args, "arena_name", "default") or "default"),
        "challenge_version": challenge_version,
        "champion_path": str(path),
        "history_path": str(arena_history_path(args)),
        "updated": improved,
        "challenger_score": challenger_score,
        "challenger_score_key": challenger_key,
        "challenger_tier": challenger_tier,
        "challenger_tier_name": challenger_components.get("arena_tier_name"),
        "challenger_qualification_status": challenger_qualification_status,
        "challenger_champion_type": challenger_champion_type,
        "incumbent_score": None if incumbent is None else incumbent_score,
        "incumbent_score_key": None if incumbent is None else incumbent_key,
        "incumbent_tier": None if incumbent is None else incumbent_tier,
        "incumbent_tier_name": None if incumbent is None else incumbent_components.get("arena_tier_name"),
        "incumbent_qualification_status": incumbent_qualification_status,
        "incumbent_champion_type": incumbent_champion_type,
        "challenger": challenger_payload,
        "challenger_score_components": challenger_components,
        "incumbent": incumbent,
    }
    if improved:
        now = now_text()
        new_champion = {
            "arena_name": result["arena_name"],
            "champion_version": challenge_version,
            "run_id": args.run_id,
            "summary_path": str(summary_path),
            "arena_score": challenger_score,
            "arena_score_components": challenger_components,
            "best": challenger_payload,
            "qualification_status": challenger_qualification_status,
            "champion_type": challenger_champion_type,
            "champion_validation": validation_report,
            "validation_status": "pending_rerun",
            "validation_note": "新擂主仅代表首次挑战胜出，需要同配置重跑后才能标记为 confirmed。",
            "created_at": (incumbent or {}).get("created_at", now),
            "updated_at": now,
            "previous_champion": incumbent,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(new_champion, ensure_ascii=False, indent=2), encoding="utf-8")
        result["champion"] = new_champion
        progress_log(
            "arena_champion_updated",
            run_id=args.run_id,
            arena_name=result["arena_name"],
            champion_path=str(path),
            challenger_score=challenger_score,
            incumbent_score=result["incumbent_score"],
            challenger_tier=challenger_tier,
            challenger_tier_name=challenger_components.get("arena_tier_name"),
            challenger_qualification_status=challenger_qualification_status,
            challenger_champion_type=challenger_champion_type,
            incumbent_tier=result["incumbent_tier"],
            incumbent_tier_name=result["incumbent_tier_name"],
            incumbent_qualification_status=result["incumbent_qualification_status"],
            incumbent_champion_type=result["incumbent_champion_type"],
            challenger=challenger_payload,
        )
    else:
        validation_confirmed = False
        if incumbent:
            incumbent_payload = champion_payload((incumbent or {}).get("best") or {})
            same_champion = comparable_champion_payload(challenger_payload) == comparable_champion_payload(incumbent_payload)
            same_score = abs(challenger_score - incumbent_score) <= max(1e-9, abs(incumbent_score) * 1e-12)
            pending_validation = (incumbent or {}).get("validation_status") == "pending_rerun"
            historical_recalc_validation = (incumbent or {}).get("validation_status") == "historical_score_recalc"
            refresh_validation_report = validation_report is not None and same_champion and same_score
            should_notify_validation = pending_validation or historical_recalc_validation
            if same_champion and same_score and (pending_validation or historical_recalc_validation or refresh_validation_report):
                now = now_text()
                incumbent = dict(incumbent)
                incumbent["validation_status"] = "confirmed"
                incumbent["validation_note"] = "同配置重跑复验通过；验证轮未改变擂主版本，并刷新擂主复验报告。"
                incumbent["validated_at"] = now
                incumbent["validation_run_id"] = args.run_id
                incumbent["validation_summary_path"] = str(summary_path)
                incumbent["validation_score"] = challenger_score
                incumbent["champion_validation"] = validation_report
                incumbent["updated_at"] = now
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(incumbent, ensure_ascii=False, indent=2), encoding="utf-8")
                validation_confirmed = True
                result["validation_confirmed"] = True
                progress_log(
                    "arena_champion_validated",
                    run_id=args.run_id,
                    arena_name=result["arena_name"],
                    champion_path=str(path),
                    champion_run_id=incumbent.get("run_id"),
                    champion_version=incumbent.get("champion_version"),
                    challenger_score=challenger_score,
                )
                if should_notify_validation:
                    notify_arena_wechat("validated", args, challenger, challenger_score, int(incumbent.get("champion_version") or challenge_version), summary_path)
                else:
                    progress_log(
                        "arena_wechat_notify_skipped",
                        run_id=args.run_id,
                        notify_event="validated",
                        reason="validation_report_refresh_only",
                    )
        result["champion"] = incumbent
        progress_log(
            "arena_challenge_failed",
            run_id=args.run_id,
            arena_name=result["arena_name"],
            champion_path=str(path),
            challenger_score=challenger_score,
            incumbent_score=incumbent_score,
            challenger_tier=challenger_tier,
            challenger_tier_name=challenger_components.get("arena_tier_name"),
            challenger_qualification_status=challenger_qualification_status,
            challenger_champion_type=challenger_champion_type,
            incumbent_tier=incumbent_tier,
            incumbent_tier_name=incumbent_components.get("arena_tier_name"),
            incumbent_qualification_status=incumbent_qualification_status,
            incumbent_champion_type=incumbent_champion_type,
            challenger=challenger_payload,
            champion=(incumbent or {}).get("best"),
            validation_confirmed=validation_confirmed,
        )
    history_record = {
        "arena_name": result["arena_name"],
        "challenge_version": challenge_version,
        "run_id": args.run_id,
        "summary_path": str(summary_path),
        "challenged_at": now_text(),
        "updated": improved,
        "challenger_score": challenger_score,
        "challenger_tier": challenger_tier,
        "challenger_tier_name": challenger_components.get("arena_tier_name"),
        "challenger_qualification_status": challenger_qualification_status,
        "challenger_champion_type": challenger_champion_type,
        "incumbent_score": result["incumbent_score"],
        "incumbent_tier": result["incumbent_tier"],
        "incumbent_tier_name": result["incumbent_tier_name"],
        "incumbent_qualification_status": result["incumbent_qualification_status"],
        "incumbent_champion_type": result["incumbent_champion_type"],
        "challenger": challenger_payload,
        "challenger_score_components": challenger_components,
        "incumbent_run_id": (incumbent or {}).get("run_id"),
        "incumbent_champion_version": (incumbent or {}).get("champion_version"),
        "incumbent": (incumbent or {}).get("best"),
        "champion_after": (result.get("champion") or {}).get("best"),
        "champion_after_run_id": (result.get("champion") or {}).get("run_id"),
        "champion_after_version": (result.get("champion") or {}).get("champion_version"),
        "champion_after_qualification_status": (result.get("champion") or {}).get("qualification_status"),
        "champion_after_type": (result.get("champion") or {}).get("champion_type"),
        "validation_confirmed": bool(result.get("validation_confirmed", False)),
    }
    append_arena_history(args, history_record)
    progress_log(
        "arena_history_appended",
        run_id=args.run_id,
        arena_name=result["arena_name"],
        challenge_version=challenge_version,
        history_path=str(arena_history_path(args)),
        updated=improved,
    )
    return result


def compact_summary_for_db(summary: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in summary.items() if key != "runs"}
    compact_runs: list[dict[str, Any]] = []
    for run in summary.get("runs", []) or []:
        compact_runs.append({
            "scope": run.get("scope"),
            "horizon": run.get("horizon"),
            "status": run.get("status"),
            "rows": run.get("rows"),
            "test_rows": run.get("test_rows"),
            "test_start": run.get("test_start"),
            "test_end": run.get("test_end"),
            "latest_date": run.get("latest_date"),
            "latest_count": run.get("latest_count"),
            "folds": run.get("folds", []),
            "evaluation_count": len(run.get("evaluations", []) or []),
            "gate_pass_count": run.get("gate_pass_count", 0),
            "best_eval": run.get("best_eval", {}),
        })
    compact["runs"] = compact_runs
    return compact


def chunked_executemany(conn: Any, sql: str, rows: list[tuple[Any, ...]], chunk_size: int = 500) -> None:
    for start in range(0, len(rows), int(chunk_size)):
        conn.executemany(sql, rows[start:start + int(chunk_size)])


def write_results(args: argparse.Namespace, summary: dict[str, Any], results: list[dict[str, Any]], model_path: str) -> None:
    now = now_text()
    progress_log("db_write_start", run_id=args.run_id, db_path=args.db_path, model_path=model_path)
    compact_summary = compact_summary_for_db(summary)
    with write_transaction(args.db_path) as conn:
        conn.execute("DELETE FROM profit_arena_features WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM profit_arena_predictions WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM profit_arena_evaluations WHERE run_id = ?", (args.run_id,))
        best = summary["best"]
        conn.execute(
            replace_sql(
                "profit_arena_runs",
                [
                    "run_id", "start_date", "end_date", "train_mode", "model_type", "feature_count", "status",
                    "best_scope", "best_horizon", "best_top_n", "best_compound_return", "summary_json", "model_path",
                    "created_at", "updated_at",
                ],
                ["run_id"],
            ),
            (
                args.run_id, args.start, args.end, "walk_forward_profit_max", f"lightgbm_{args.model_kind}_{args.objective}_{args.target_mode}",
                len(getattr(args, "feature_columns", FEATURES)), "success", best["scope"], int(best["horizon"]), int(best["top_n"]),
                safe_float(best["compound_return"]), json.dumps(compact_summary, ensure_ascii=False), model_path, now, now,
            ),
        )
        feature_rows = []
        eval_rows = []
        pred_rows = []
        for result in results:
            if result.get("status") != "success":
                continue
            scope = str(result["scope"])
            horizon = int(result["horizon"])
            importance: pd.Series = result["importance"]
            for rank, (feature, value) in enumerate(importance.sort_values(ascending=False).items(), 1):
                feature_rows.append((args.run_id, scope, horizon, str(feature), safe_float(value), int(rank), now, now))
            for item in result["evaluations"]:
                eval_rows.append((
                    args.run_id, scope, horizon, int(item["top_n"]), safe_float(item["min_pred_return"]),
                    safe_float(item["min_market_up_ratio"]), safe_float(item["min_market_ret5"]),
                    safe_float(item.get("min_market_ret20", -999.0)),
                    safe_float(item["min_market_amount_chg5"]),
                    safe_float(item.get("max_market_drawdown20", 999.0)),
                    safe_float(item.get("max_market_volatility20", 999.0)),
                    safe_float(item["min_industry_up_ratio"]),
                    safe_float(item.get("max_crash_prob", 999.0)),
                    safe_float(item.get("execution_stop_loss", 0.0)),
                    safe_float(item.get("execution_take_profit", 0.0)),
                    str(item.get("position_weighting", "equal")),
                    str(item.get("capital_scale_mode", "none")),
                    str(item["segment"]), int(item["trade_count"]),
                    int(item["trade_days"]), safe_float(item["avg_return"]), safe_float(item["win_rate"]),
                    safe_float(item["compound_return"]), safe_float(item["annual_return"]), safe_float(item["max_drawdown"]),
                    safe_float(item["sharpe"]), safe_float(item["capital_compound_return"]), safe_float(item["capital_annual_return"]),
                    safe_float(item["capital_max_drawdown"]), safe_float(item["capital_sharpe"]), safe_float(item["capital_final_equity"]),
                    safe_float(item.get("capital_tranche_fraction")), safe_float(item.get("rank_ic")), int(item.get("rank_ic_days", 0) or 0),
                    json.dumps(item, ensure_ascii=False), now, now,
                ))
            pred_cols = [
                "trade_date", "ts_code", "name", "industry", "size_bucket", "close", "pred_return", "model_score",
                "realized_return", "future_return", "future_max_return", "future_drawdown", "crash_prob", "exit_date", "is_latest",
            ]
            pred_frame: pd.DataFrame = result["predictions"][pred_cols].copy()
            ranked = pred_frame.sort_values(["trade_date", "model_score"], ascending=[True, False]).groupby("trade_date", sort=False).head(max(args.top_n_values))
            latest = pred_frame[pred_frame["is_latest"] == 1].sort_values("model_score", ascending=False).head(max(args.top_n_values) * 5)
            pred_keep = pd.concat([ranked, latest], ignore_index=True).drop_duplicates(["trade_date", "ts_code"], keep="first")
            for row in pred_keep.itertuples(index=False):
                pred_rows.append((
                    args.run_id, scope, horizon, str(row.trade_date), str(row.ts_code), str(row.name or ""),
                    str(row.industry or ""), str(row.size_bucket or ""), safe_float(row.close), safe_float(row.pred_return),
                    safe_float(row.model_score), safe_float(row.realized_return), safe_float(row.future_return),
                    safe_float(row.future_max_return), safe_float(row.future_drawdown), safe_float(row.crash_prob), str(row.exit_date or ""), int(row.is_latest or 0),
                    "{}", now, now,
                ))
        if feature_rows:
            chunked_executemany(
                conn,
                replace_sql("profit_arena_features", ["run_id", "scope", "horizon", "feature", "importance", "rank_no", "created_at", "updated_at"], ["run_id", "scope", "horizon", "feature"]),
                feature_rows,
            )
        if eval_rows:
            chunked_executemany(
                conn,
                replace_sql(
                    "profit_arena_evaluations",
                    [
                        "run_id", "scope", "horizon", "top_n", "min_pred_return",
                        "min_market_up_ratio", "min_market_ret5", "min_market_ret20", "min_market_amount_chg5",
                        "max_market_drawdown20", "max_market_volatility20", "min_industry_up_ratio",
                        "max_crash_prob", "execution_stop_loss", "execution_take_profit", "position_weighting", "capital_scale_mode", "segment", "trade_count", "trade_days", "avg_return",
                        "win_rate", "compound_return", "annual_return", "max_drawdown", "sharpe",
                        "capital_compound_return", "capital_annual_return", "capital_max_drawdown", "capital_sharpe", "capital_final_equity",
                        "capital_tranche_fraction", "rank_ic", "rank_ic_days",
                        "summary_json",
                        "created_at", "updated_at",
                    ],
                    ["run_id", "scope", "horizon", "top_n", "min_pred_return", "min_market_up_ratio", "min_market_ret5", "min_market_ret20", "min_market_amount_chg5", "max_market_drawdown20", "max_market_volatility20", "min_industry_up_ratio", "max_crash_prob", "execution_stop_loss", "execution_take_profit", "position_weighting", "capital_scale_mode", "segment", "capital_tranche_fraction"],
                ),
                eval_rows,
            )
        if pred_rows:
            chunked_executemany(
                conn,
                replace_sql(
                    "profit_arena_predictions",
                    [
                        "run_id", "scope", "horizon", "trade_date", "ts_code", "name", "industry", "size_bucket",
                        "price", "pred_return", "model_score", "realized_return", "future_return", "future_max_return",
                        "future_drawdown", "crash_prob", "exit_date", "is_latest", "summary_json", "created_at", "updated_at",
                    ],
                    ["run_id", "scope", "horizon", "trade_date", "ts_code"],
                ),
                pred_rows,
            )
    progress_log(
        "db_write_done",
        run_id=args.run_id,
        feature_rows=len(feature_rows),
        evaluation_rows=len(eval_rows),
        prediction_rows=len(pred_rows),
    )


def write_latest_predictions(args: argparse.Namespace, source_run_id: str, scope: str, horizon: int, pred: pd.DataFrame) -> None:
    now = now_text()
    pred_cols = [
        "trade_date", "ts_code", "name", "industry", "size_bucket", "close", "pred_return", "model_score",
        "realized_return", "future_return", "future_max_return", "future_drawdown", "crash_prob", "exit_date", "is_latest",
    ]
    rows = []
    keep = pred[pred_cols].copy().sort_values("model_score", ascending=False)
    for row in keep.itertuples(index=False):
        rows.append((
            source_run_id, scope, int(horizon), str(row.trade_date), str(row.ts_code), str(row.name or ""),
            str(row.industry or ""), str(row.size_bucket or ""), safe_float(row.close), safe_float(row.pred_return),
            safe_float(row.model_score), safe_float(row.realized_return), safe_float(row.future_return),
            safe_float(row.future_max_return), safe_float(row.future_drawdown), safe_float(row.crash_prob),
            str(row.exit_date or ""), int(row.is_latest or 0), "{}", now, now,
        ))
    with write_transaction(args.db_path) as conn:
        conn.execute(
            "UPDATE profit_arena_predictions SET is_latest = 0 WHERE run_id = ? AND scope = ? AND horizon = ?",
            (source_run_id, scope, int(horizon)),
        )
        if rows:
            chunked_executemany(
                conn,
                replace_sql(
                    "profit_arena_predictions",
                    [
                        "run_id", "scope", "horizon", "trade_date", "ts_code", "name", "industry", "size_bucket",
                        "price", "pred_return", "model_score", "realized_return", "future_return", "future_max_return",
                        "future_drawdown", "crash_prob", "exit_date", "is_latest", "summary_json", "created_at", "updated_at",
                    ],
                    ["run_id", "scope", "horizon", "trade_date", "ts_code"],
                ),
                rows,
            )
        conn.execute("UPDATE profit_arena_runs SET updated_at = ? WHERE run_id = ?", (now, source_run_id))
    progress_log("latest_inference_db_write_done", run_id=args.run_id, source_run_id=source_run_id, rows=len(rows), latest_date=str(keep["trade_date"].max()) if not keep.empty else "")


def prepare_arena_args(args: argparse.Namespace) -> None:
    args.feature_columns = feature_columns_for_set(getattr(args, "feature_set", "all"))
    args.horizon_values = parse_int_list(args.horizons)
    args.top_n_values = parse_int_list(args.top_n)
    args.min_pred_return_values = parse_float_list(args.min_pred_return)
    args.min_market_up_ratio_values = parse_float_list(args.min_market_up_ratio)
    args.min_market_ret5_values = parse_float_list(args.min_market_ret5)
    args.min_market_ret20_values = parse_float_list(args.min_market_ret20)
    args.min_market_amount_chg5_values = parse_float_list(args.min_market_amount_chg5)
    args.min_market_volatility20_values = parse_float_list(args.min_market_volatility20)
    args.max_market_drawdown20_values = parse_float_list(args.max_market_drawdown20)
    args.max_market_volatility20_values = parse_float_list(args.max_market_volatility20)
    args.min_turnover_rate_values = parse_float_list(args.min_turnover_rate)
    args.min_industry_up_ratio_values = parse_float_list(args.min_industry_up_ratio)
    args.min_small_up_ratio_values = parse_float_list(args.min_small_up_ratio)
    args.min_small_limit_up_ratio_values = parse_float_list(args.min_small_limit_up_ratio)
    args.min_small_near_limit_up_ratio_values = parse_float_list(args.min_small_near_limit_up_ratio)
    args.min_small_amount_chg5_values = parse_float_list(args.min_small_amount_chg5)
    args.min_small_rs_market20_values = parse_float_list(args.min_small_rs_market20)
    args.min_small_breakout_high20_ratio_values = parse_float_list(args.min_small_breakout_high20_ratio)
    args.max_crash_prob_values = parse_float_list(args.max_crash_prob)
    args.min_daily_top_score_values = parse_float_list(args.min_daily_top_score)
    args.min_daily_top_pred_return_values = parse_float_list(args.min_daily_top_pred_return)
    args.max_daily_top_crash_prob_values = parse_float_list(args.max_daily_top_crash_prob)
    args.execution_stop_loss_values = parse_float_list(args.execution_stop_loss)
    args.execution_take_profit_values = parse_float_list(args.execution_take_profit)
    args.position_weighting_values = parse_position_weighting_list(args.position_weighting)
    args.capital_scale_mode_values = parse_capital_scale_mode_list(args.capital_scale_mode)
    args.capital_tranche_fraction_values = parse_float_list(args.capital_tranche_fractions)
    args.scope_values = parse_str_list(args.scopes)


def _model_feature_names(model: Any) -> list[str] | None:
    """Return the feature names a fitted model was trained on, if available.

    The arena feature list has grown over time, so a champion model file may
    have been trained on fewer columns than the current panel produces. Aligning
    inference inputs to the model's own training features avoids LightGBM's
    "number of features in data ... not the same as ... training data" error.
    """
    candidates: list[Any] = []
    if isinstance(model, dict):
        for key in ("regressor", "ranker", "main"):
            if key in model:
                candidates.append(model[key])
        if not candidates:
            candidates.extend(model.values())
    else:
        candidates.append(model)
    for candidate in candidates:
        names = getattr(candidate, "feature_name_", None)
        if names is None:
            names = getattr(candidate, "feature_names_in_", None)
        if names is None:
            booster = getattr(candidate, "booster_", None)
            if booster is not None:
                try:
                    names = booster.feature_name()
                except Exception:
                    names = None
        if names is not None and len(names) > 0:
            return [str(name) for name in names]
    return None


def _aligned_features(latest_pool: "pd.DataFrame", model: Any, default_columns: list[str], role: str) -> "pd.DataFrame":
    """Build the model input matrix using the model's own training features."""
    columns = _model_feature_names(model) or list(default_columns)
    missing = [col for col in columns if col not in latest_pool.columns]
    if missing:
        raise RuntimeError(f"最新截面缺少 {role} 模型所需特征: {', '.join(missing[:10])}")
    return latest_pool[columns].astype(float)


def latest_inference_model(args: argparse.Namespace) -> dict[str, Any]:
    prepare_arena_args(args)
    out_dir = Path(args.data_path) / "profit_arena" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    set_progress_file(out_dir / "progress.jsonl")
    source_run_id = str(args.latest_inference_source_run_id or "").strip()
    model_path = Path(str(args.latest_inference_model_path or "").strip())
    scope = str(args.latest_inference_scope or (args.scope_values[0] if args.scope_values else "small")).strip() or "small"
    horizon = int(args.latest_inference_horizon or (args.horizon_values[0] if args.horizon_values else 20))
    if not source_run_id:
        raise ValueError("最新截面推理缺少 source run_id")
    if not model_path.exists():
        raise FileNotFoundError(f"擂主模型文件不存在: {model_path}")
    progress_log(
        "latest_inference_start",
        run_id=args.run_id,
        source_run_id=source_run_id,
        model_path=str(model_path),
        scope=scope,
        horizon=horizon,
        feature_set=args.feature_set,
    )
    saved_model = joblib.load(model_path)
    data = load_or_build_panel(args, [horizon])
    sample = data[data["size_bucket"].astype(str).eq(scope)].copy() if scope in {"small", "mid", "large"} else data.copy()
    latest_date = str(sample["trade_date"].max()) if not sample.empty else ""
    latest_pool = sample[sample["trade_date"].astype(str).eq(latest_date)].copy()
    if latest_pool.empty:
        raise RuntimeError("最新截面没有可推理股票")
    if isinstance(saved_model, dict) and "main" in saved_model:
        model = saved_model.get("main")
        crash_model = saved_model.get("crash")
        breakout_model = saved_model.get("breakout")
    else:
        model = saved_model
        crash_model = saved_model.get("crash") if isinstance(saved_model, dict) else None
        breakout_model = saved_model.get("breakout") if isinstance(saved_model, dict) else None
    if model is None:
        raise RuntimeError("擂主模型文件缺少 main 模型，拒绝生成最新推荐")
    if args.crash_filter == "classifier" and crash_model is None:
        raise RuntimeError("擂主训练配置要求 crash classifier，但模型文件缺少 crash 模型，拒绝生成最新推荐")
    if args.breakout_filter == "classifier" and breakout_model is None:
        raise RuntimeError("擂主训练配置要求 breakout classifier，但模型文件缺少 breakout 模型，拒绝生成最新推荐")
    if isinstance(model, dict):
        if "regressor" not in model or "ranker" not in model:
            raise RuntimeError("hybrid 擂主模型缺少 regressor/ranker，拒绝生成最新推荐")
        latest_pool["pred_return"] = model["regressor"].predict(
            _aligned_features(latest_pool, model["regressor"], args.feature_columns, "regressor")
        ).astype(float)
        latest_pool["rank_score_raw"] = model["ranker"].predict(
            _aligned_features(latest_pool, model["ranker"], args.feature_columns, "ranker")
        ).astype(float)
    else:
        if not hasattr(model, "predict"):
            raise RuntimeError("擂主模型不支持 predict，拒绝生成最新推荐")
        latest_pool["pred_return"] = model.predict(
            _aligned_features(latest_pool, model, args.feature_columns, "main")
        ).astype(float)
        latest_pool["rank_score_raw"] = latest_pool["pred_return"] if args.model_kind == "ranker" else latest_pool["pred_return"] * 100.0
    if crash_model is not None:
        if not hasattr(crash_model, "predict_proba"):
            raise RuntimeError("crash 模型不支持 predict_proba，拒绝生成最新推荐")
        latest_pool["crash_prob"] = crash_model.predict_proba(
            _aligned_features(latest_pool, crash_model, args.feature_columns, "crash")
        )[:, 1].astype(float)
    else:
        latest_pool["crash_prob"] = 0.0
    if breakout_model is not None:
        if not hasattr(breakout_model, "predict_proba"):
            raise RuntimeError("breakout 模型不支持 predict_proba，拒绝生成最新推荐")
        latest_pool["breakout_prob"] = breakout_model.predict_proba(
            _aligned_features(latest_pool, breakout_model, args.feature_columns, "breakout")
        )[:, 1].astype(float)
    else:
        latest_pool["breakout_prob"] = 0.0
    latest_pool["model_score"] = latest_pool["rank_score_raw"]
    if args.score_mode == "blended":
        latest_pool["model_score"] = blend_model_score(latest_pool, args)
    latest_pool["realized_return"] = 0.0
    latest_pool["future_return"] = latest_pool.get(f"future_return_{horizon}d", 0.0)
    latest_pool["future_max_return"] = latest_pool.get(f"future_max_return_{horizon}d", 0.0)
    latest_pool["future_drawdown"] = latest_pool.get(f"future_drawdown_{horizon}d", 0.0)
    latest_pool["exit_date"] = latest_pool.get(f"exit_date_{horizon}d", "").fillna("").astype(str)
    latest_pool["is_latest"] = 1
    latest_pool = latest_pool.sort_values("model_score", ascending=False).head(max(args.top_n_values) * 8)
    write_latest_predictions(args, source_run_id, scope, horizon, latest_pool)
    summary = {
        "run_id": args.run_id,
        "source_run_id": source_run_id,
        "model_path": str(model_path),
        "scope": scope,
        "horizon": horizon,
        "latest_date": latest_date,
        "latest_count": int(len(latest_pool)),
        "top": latest_pool[["ts_code", "name", "model_score", "pred_return", "crash_prob"]].head(20).to_dict("records"),
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    progress_log("latest_inference_done", run_id=args.run_id, source_run_id=source_run_id, latest_date=latest_date, rows=len(latest_pool), summary_path=str(summary_path))
    return summary


def train_model(args: argparse.Namespace, data: pd.DataFrame) -> dict[str, Any]:
    prepare_arena_args(args)
    results: list[dict[str, Any]] = []
    out_dir = Path(args.data_path) / "profit_arena" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    set_progress_file(out_dir / "progress.jsonl")
    summary_path = out_dir / "summary.json"
    incumbent = load_arena_champion(args)
    incumbent_best = (incumbent or {}).get("best") if isinstance(incumbent, dict) else None
    best_payload: dict[str, Any] | None = None
    best_model_path = ""
    best_rank_key: float | None = None

    progress_log(
        "train_model_start",
        run_id=args.run_id,
        arena_name=args.arena_name,
        scopes=args.scope_values,
        horizons=args.horizon_values,
        feature_set=args.feature_set,
        feature_count=len(args.feature_columns),
        top_n=args.top_n_values,
        min_pred_return=args.min_pred_return_values,
        capital_fractions=args.capital_tranche_fraction_values,
        max_crash_prob=args.max_crash_prob_values,
        breakout_filter=args.breakout_filter,
        score_mode=args.score_mode,
        min_market_ret20=args.min_market_ret20_values,
        max_market_drawdown20=args.max_market_drawdown20_values,
        max_market_volatility20=args.max_market_volatility20_values,
        min_daily_top_score=args.min_daily_top_score_values,
        min_daily_top_pred_return=args.min_daily_top_pred_return_values,
        max_daily_top_crash_prob=args.max_daily_top_crash_prob_values,
        min_small_up_ratio=args.min_small_up_ratio_values,
        min_small_limit_up_ratio=args.min_small_limit_up_ratio_values,
        min_small_near_limit_up_ratio=args.min_small_near_limit_up_ratio_values,
        min_small_amount_chg5=args.min_small_amount_chg5_values,
        min_small_rs_market20=args.min_small_rs_market20_values,
        min_small_breakout_high20_ratio=args.min_small_breakout_high20_ratio_values,
        execution_stop_loss=args.execution_stop_loss_values,
        execution_take_profit=args.execution_take_profit_values,
        position_weighting=args.position_weighting_values,
        capital_scale_modes=args.capital_scale_mode_values,
        incumbent_champion=incumbent_best,
        incumbent_champion_version=(incumbent or {}).get("champion_version") if isinstance(incumbent, dict) else None,
        incumbent_run_id=(incumbent or {}).get("run_id") if isinstance(incumbent, dict) else None,
        incumbent_score=(incumbent or {}).get("arena_score"),
        incumbent_validation_status=(incumbent or {}).get("validation_status") if isinstance(incumbent, dict) else None,
        champion_path=str(arena_champion_path(args)),
        progress_path=str(PROGRESS_FILE),
    )
    for scope in args.scope_values:
        for horizon in args.horizon_values:
            result = train_scope_horizon(args, data, scope, horizon)
            best_eval = result.get("best_eval", {}) if isinstance(result.get("best_eval"), dict) else {}
            progress_log(
                "scope_horizon_result",
                run_id=args.run_id,
                scope=result.get("scope"),
                horizon=result.get("horizon"),
                status=result.get("status"),
                rows=result.get("rows"),
                test_rows=result.get("test_rows"),
                evaluations=len(result.get("evaluations", []) or []),
                gate_pass_count=result.get("gate_pass_count", 0),
                best_capital_annual_return=best_eval.get("capital_annual_return"),
                best_capital_max_drawdown=best_eval.get("capital_max_drawdown"),
                best_capital_sharpe=best_eval.get("capital_sharpe"),
                best_rank_ic=best_eval.get("rank_ic"),
                best_rank_ic_days=best_eval.get("rank_ic_days"),
                reason=result.get("reason"),
            )
            results.append(result)
            if result.get("status") != "success":
                continue
            if not bool(getattr(args, "skip_prediction_files", False)):
                pred_path = out_dir / f"predictions_{scope}_{horizon}d.parquet"
                progress_log("prediction_file_write_start", run_id=args.run_id, path=str(pred_path), rows=len(result["predictions"]))
                result["predictions"].to_parquet(pred_path, index=False, compression="zstd")
                progress_log("prediction_file_write_done", run_id=args.run_id, path=str(pred_path))
            model = result.get("model")
            if model is not None:
                current_model_path = out_dir / f"model_{scope}_{horizon}d.joblib"
                progress_log("model_write_start", run_id=args.run_id, path=str(current_model_path))
                joblib.dump(model, current_model_path)
                progress_log("model_write_done", run_id=args.run_id, path=str(current_model_path))
            else:
                current_model_path = None
            current_best = {**result["best_eval"], "scope": scope, "horizon": int(horizon)}
            rank_key = arena_score(current_best, args)
            if best_rank_key is None or rank_key > best_rank_key:
                best_payload = current_best
                best_rank_key = rank_key
                best_model_path = str(current_model_path) if current_model_path is not None else ""

    if str(getattr(args, "fusion_mode", "none") or "none").lower() == "horizon_blend":
        for scope in args.scope_values:
            fusion_result = build_horizon_fusion_result(args, results, scope, int(getattr(args, "fusion_eval_horizon", 20)))
            best_eval = fusion_result.get("best_eval", {}) if isinstance(fusion_result.get("best_eval"), dict) else {}
            progress_log(
                "fusion_result",
                run_id=args.run_id,
                scope=fusion_result.get("scope"),
                horizon=fusion_result.get("horizon"),
                status=fusion_result.get("status"),
                rows=fusion_result.get("rows"),
                evaluations=len(fusion_result.get("evaluations", []) or []),
                gate_pass_count=fusion_result.get("gate_pass_count", 0),
                best_capital_annual_return=best_eval.get("capital_annual_return"),
                best_capital_max_drawdown=best_eval.get("capital_max_drawdown"),
                best_capital_sharpe=best_eval.get("capital_sharpe"),
                best_rank_ic=best_eval.get("rank_ic"),
                best_rank_ic_days=best_eval.get("rank_ic_days"),
                reason=fusion_result.get("reason"),
            )
            results.append(fusion_result)
            if fusion_result.get("status") != "success":
                continue
            current_best = {**fusion_result["best_eval"], "scope": scope, "horizon": int(getattr(args, "fusion_eval_horizon", 20))}
            rank_key = arena_score(current_best, args)
            if best_rank_key is None or rank_key > best_rank_key:
                best_payload = current_best
                best_rank_key = rank_key
                best_model_path = ""

    successes = [item for item in results if item.get("status") == "success"]
    if not successes or best_payload is None:
        raise RuntimeError("收益擂台没有产生可评估模型")

    all_evaluations = collect_evaluations(results)
    leaderboards = build_leaderboards(all_evaluations, args)
    validation_report = None
    for item in results:
        if (
            item.get("status") == "success"
            and item.get("scope") == best_payload.get("scope")
            and int(item.get("horizon", 0) or 0) == int(best_payload.get("horizon", 0) or 0)
            and isinstance(item.get("predictions"), pd.DataFrame)
        ):
            validation_report = champion_validation_report(args, item["predictions"], best_payload)
            break
    challenge_result = update_arena_champion(args, best_payload, summary_path, validation_report)
    summary = {
        "run_id": args.run_id,
        "arena_name": args.arena_name,
        "objective": "maximize_risk_adjusted_arena_score",
        "model_kind": args.model_kind,
        "target_mode": args.target_mode,
        "selection": {
            "metric": args.selection_metric,
            "min_rank_ic": args.min_rank_ic,
            "min_rank_ic_days": args.min_rank_ic_days,
            "min_capital_annual_return": args.min_capital_annual_return,
            "min_capital_sharpe": args.min_capital_sharpe,
            "max_capital_drawdown": args.max_capital_drawdown,
            "selection_min_trades": args.selection_min_trades,
            "selection_min_trade_years": args.selection_min_trade_years,
        },
        "start": args.start,
        "end": args.end,
        "features": args.feature_columns,
        "feature_set": args.feature_set,
        "all_panel_features": FEATURES,
        "cost": {
            "buy_slippage": args.buy_slippage,
            "sell_slippage": args.sell_slippage,
            "commission": args.commission,
            "stamp_tax": args.stamp_tax,
            "stop_loss": args.stop_loss,
            "take_profit": args.take_profit,
            "execution_stop_loss": args.execution_stop_loss_values,
            "execution_take_profit": args.execution_take_profit_values,
            "capital_tranche_fraction": args.capital_tranche_fraction,
            "capital_tranche_fractions": args.capital_tranche_fraction_values,
            "max_gross_exposure": args.max_gross_exposure,
            "position_weighting": args.position_weighting_values,
            "capital_scale_mode": args.capital_scale_mode_values,
            "drawdown_penalty_weight": args.drawdown_penalty_weight,
        },
        "risk_filter": {
            "crash_filter": args.crash_filter,
            "crash_return_threshold": args.crash_return_threshold,
            "crash_drawdown_threshold": args.crash_drawdown_threshold,
            "max_crash_prob": args.max_crash_prob_values,
            "crash_n_estimators": args.crash_n_estimators,
            "breakout_filter": args.breakout_filter,
            "breakout_quantile": args.breakout_quantile,
            "breakout_n_estimators": args.breakout_n_estimators,
            "score_mode": args.score_mode,
            "rank_score_weight": args.rank_score_weight,
            "pred_score_weight": args.pred_score_weight,
            "breakout_score_weight": args.breakout_score_weight,
            "crash_score_weight": args.crash_score_weight,
            "min_market_volatility20": args.min_market_volatility20_values,
            "max_market_volatility20": args.max_market_volatility20_values,
            "min_turnover_rate": args.min_turnover_rate_values,
            "min_daily_top_score": args.min_daily_top_score_values,
            "min_daily_top_pred_return": args.min_daily_top_pred_return_values,
            "max_daily_top_crash_prob": args.max_daily_top_crash_prob_values,
            "min_small_up_ratio": args.min_small_up_ratio_values,
            "min_small_limit_up_ratio": args.min_small_limit_up_ratio_values,
            "min_small_near_limit_up_ratio": args.min_small_near_limit_up_ratio_values,
            "min_small_amount_chg5": args.min_small_amount_chg5_values,
            "min_small_rs_market20": args.min_small_rs_market20_values,
            "min_small_breakout_high20_ratio": args.min_small_breakout_high20_ratio_values,
        },
        "universe": "A股主板可交易池，排除ST、退市、创业板、科创板、北交所；按日成交额和价格做基本可成交过滤。",
        "best": best_payload,
        "best_challenger_score": best_rank_key,
        "best_challenger_score_components": arena_score_components(best_payload, args),
        "leaderboards": leaderboards,
        "champion_validation": validation_report,
        "arena_champion": challenge_result.get("champion"),
        "challenge_result": {key: value for key, value in challenge_result.items() if key not in {"champion", "incumbent"}},
        "runs": [{k: v for k, v in item.items() if k not in {"predictions", "importance", "model"}} for item in results],
    }
    progress_log(
        "leaderboards_ready",
        run_id=args.run_id,
        strict_count=len(leaderboards.get("strict_champion_candidates", []) or []),
        risk_qualified_missing_return_count=len(leaderboards.get("risk_qualified_missing_return", []) or []),
        attack_watchlist_by_annual_count=len(leaderboards.get("attack_watchlist_by_annual", []) or []),
        strict_best=(leaderboards.get("strict_champion_candidates") or [{}])[0].get("candidate"),
        attack_best_by_annual=(leaderboards.get("attack_watchlist_by_annual") or [{}])[0].get("candidate"),
        attack_best_by_return_drawdown_ratio=(leaderboards.get("attack_watchlist_by_return_drawdown_ratio") or [{}])[0].get("candidate"),
    )
    progress_log("summary_write_start", run_id=args.run_id, path=str(summary_path))
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    progress_log("summary_write_done", run_id=args.run_id, path=str(summary_path))
    write_results(args, summary, results, best_model_path)
    return summary


def eval_only_model(args: argparse.Namespace) -> dict[str, Any]:
    prepare_arena_args(args)
    out_dir = Path(args.data_path) / "profit_arena" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    set_progress_file(out_dir / "progress.jsonl")
    summary_path = out_dir / "summary.json"
    source_path = Path(str(args.eval_only_predictions))
    if not source_path.exists():
        raise FileNotFoundError(f"预测文件不存在: {source_path}")
    scope = str(args.eval_only_scope or (args.scope_values[0] if args.scope_values else "small"))
    horizon = int(args.eval_only_horizon or (args.horizon_values[0] if args.horizon_values else 20))
    progress_log(
        "eval_only_start",
        run_id=args.run_id,
        arena_name=args.arena_name,
        predictions_path=str(source_path),
        scope=scope,
        horizon=horizon,
        top_n=args.top_n_values,
        min_pred_return=args.min_pred_return_values,
        capital_fractions=args.capital_tranche_fraction_values,
        max_crash_prob=args.max_crash_prob_values,
        min_daily_top_score=args.min_daily_top_score_values,
        min_daily_top_pred_return=args.min_daily_top_pred_return_values,
        max_daily_top_crash_prob=args.max_daily_top_crash_prob_values,
        execution_stop_loss=args.execution_stop_loss_values,
        execution_take_profit=args.execution_take_profit_values,
        position_weighting=args.position_weighting_values,
        capital_scale_modes=args.capital_scale_mode_values,
        champion_path=str(arena_champion_path(args)),
        progress_path=str(PROGRESS_FILE),
    )
    pred = pd.read_parquet(source_path)
    progress_log("eval_only_predictions_loaded", run_id=args.run_id, path=str(source_path), rows=len(pred), columns=len(pred.columns))
    result = evaluate_prediction_grid(args, pred, scope, horizon)
    if result.get("status") != "success":
        raise RuntimeError(f"预测重评估没有产生可评估结果: {result.get('reason')}")
    best_payload = {**result["best_eval"], "scope": scope, "horizon": int(horizon)}
    best_rank_key = arena_score(best_payload, args)
    all_evaluations = collect_evaluations([result])
    leaderboards = build_leaderboards(all_evaluations, args)
    validation_report = champion_validation_report(args, pred, best_payload)
    challenge_result = update_arena_champion(args, best_payload, summary_path, validation_report)
    summary = {
        "run_id": args.run_id,
        "arena_name": args.arena_name,
        "objective": "maximize_risk_adjusted_arena_score_eval_only",
        "model_kind": args.model_kind,
        "target_mode": args.target_mode,
        "source_predictions": str(source_path),
        "source_run_id": str(args.eval_only_source_run_id or ""),
        "selection": {
            "metric": args.selection_metric,
            "min_rank_ic": args.min_rank_ic,
            "min_rank_ic_days": args.min_rank_ic_days,
            "min_capital_annual_return": args.min_capital_annual_return,
            "min_capital_sharpe": args.min_capital_sharpe,
            "max_capital_drawdown": args.max_capital_drawdown,
            "selection_min_trades": args.selection_min_trades,
            "selection_min_trade_years": args.selection_min_trade_years,
        },
        "start": args.start,
        "end": args.end,
        "features": args.feature_columns,
        "feature_set": args.feature_set,
        "all_panel_features": FEATURES,
        "cost": {
            "buy_slippage": args.buy_slippage,
            "sell_slippage": args.sell_slippage,
            "commission": args.commission,
            "stamp_tax": args.stamp_tax,
            "stop_loss": args.stop_loss,
            "take_profit": args.take_profit,
            "execution_stop_loss": args.execution_stop_loss_values,
            "execution_take_profit": args.execution_take_profit_values,
            "capital_tranche_fraction": args.capital_tranche_fraction,
            "capital_tranche_fractions": args.capital_tranche_fraction_values,
            "max_gross_exposure": args.max_gross_exposure,
            "position_weighting": args.position_weighting_values,
            "capital_scale_mode": args.capital_scale_mode_values,
            "drawdown_penalty_weight": args.drawdown_penalty_weight,
        },
        "risk_filter": {
            "crash_filter": args.crash_filter,
            "crash_return_threshold": args.crash_return_threshold,
            "crash_drawdown_threshold": args.crash_drawdown_threshold,
            "max_crash_prob": args.max_crash_prob_values,
            "crash_n_estimators": args.crash_n_estimators,
            "breakout_filter": args.breakout_filter,
            "breakout_quantile": args.breakout_quantile,
            "breakout_n_estimators": args.breakout_n_estimators,
            "score_mode": args.score_mode,
            "rank_score_weight": args.rank_score_weight,
            "pred_score_weight": args.pred_score_weight,
            "breakout_score_weight": args.breakout_score_weight,
            "crash_score_weight": args.crash_score_weight,
            "min_market_volatility20": args.min_market_volatility20_values,
            "max_market_volatility20": args.max_market_volatility20_values,
            "min_turnover_rate": args.min_turnover_rate_values,
            "min_daily_top_score": args.min_daily_top_score_values,
            "min_daily_top_pred_return": args.min_daily_top_pred_return_values,
            "max_daily_top_crash_prob": args.max_daily_top_crash_prob_values,
            "min_small_up_ratio": args.min_small_up_ratio_values,
            "min_small_limit_up_ratio": args.min_small_limit_up_ratio_values,
            "min_small_near_limit_up_ratio": args.min_small_near_limit_up_ratio_values,
            "min_small_amount_chg5": args.min_small_amount_chg5_values,
            "min_small_rs_market20": args.min_small_rs_market20_values,
            "min_small_breakout_high20_ratio": args.min_small_breakout_high20_ratio_values,
        },
        "universe": "A股主板可交易池，排除ST、退市、创业板、科创板、北交所；按日成交额和价格做基本可成交过滤。",
        "best": best_payload,
        "best_challenger_score": best_rank_key,
        "best_challenger_score_components": arena_score_components(best_payload, args),
        "leaderboards": leaderboards,
        "champion_validation": validation_report,
        "arena_champion": challenge_result.get("champion"),
        "challenge_result": {key: value for key, value in challenge_result.items() if key not in {"champion", "incumbent"}},
        "runs": [{k: v for k, v in result.items() if k not in {"predictions", "importance", "model"}}],
    }
    progress_log(
        "leaderboards_ready",
        run_id=args.run_id,
        strict_count=len(leaderboards.get("strict_champion_candidates", []) or []),
        risk_qualified_missing_return_count=len(leaderboards.get("risk_qualified_missing_return", []) or []),
        attack_watchlist_by_annual_count=len(leaderboards.get("attack_watchlist_by_annual", []) or []),
        strict_best=(leaderboards.get("strict_champion_candidates") or [{}])[0].get("candidate"),
        attack_best_by_annual=(leaderboards.get("attack_watchlist_by_annual") or [{}])[0].get("candidate"),
        attack_best_by_return_drawdown_ratio=(leaderboards.get("attack_watchlist_by_return_drawdown_ratio") or [{}])[0].get("candidate"),
    )
    progress_log("summary_write_start", run_id=args.run_id, path=str(summary_path))
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    progress_log("summary_write_done", run_id=args.run_id, path=str(summary_path))
    write_results(args, summary, [result], str(source_path))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=f"profit_arena_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--arena-name", default="profit_nolev_rankic_sharpe_dd15_ann50")
    parser.add_argument("--champion-min-improvement", type=float, default=0.0)
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--start", default="20150101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--min-train-years", type=int, default=4)
    parser.add_argument("--train-window-years", type=int, default=0)
    parser.add_argument("--min-test-year", type=int, default=2020)
    parser.add_argument("--min-train-rows", type=int, default=3000)
    parser.add_argument("--train-sample-per-year", type=int, default=0)
    parser.add_argument("--horizons", default="1,3,5,10")
    parser.add_argument("--top-n", default="1,3,5,10")
    parser.add_argument("--min-pred-return", default="-999,0,0.01,0.02,0.03,0.05")
    parser.add_argument("--min-market-up-ratio", default="-999")
    parser.add_argument("--min-market-ret5", default="-999")
    parser.add_argument("--min-market-ret20", default="-999")
    parser.add_argument("--min-market-amount-chg5", default="-999")
    parser.add_argument("--min-market-volatility20", default="-999")
    parser.add_argument("--max-market-drawdown20", default="999")
    parser.add_argument("--max-market-volatility20", default="999")
    parser.add_argument("--min-turnover-rate", default="-999")
    parser.add_argument("--min-industry-up-ratio", default="-999")
    parser.add_argument("--min-small-up-ratio", default="-999")
    parser.add_argument("--min-small-limit-up-ratio", default="-999")
    parser.add_argument("--min-small-near-limit-up-ratio", default="-999")
    parser.add_argument("--min-small-amount-chg5", default="-999")
    parser.add_argument("--min-small-rs-market20", default="-999")
    parser.add_argument("--min-small-breakout-high20-ratio", default="-999")
    parser.add_argument("--max-crash-prob", default="999")
    parser.add_argument("--min-daily-top-score", default="-999")
    parser.add_argument("--min-daily-top-pred-return", default="-999")
    parser.add_argument("--max-daily-top-crash-prob", default="999")
    parser.add_argument("--scopes", default="all,small,mid,large")
    parser.add_argument("--feature-set", choices=["legacy53", "core", "ecology", "all", "v6all", "pre_v7", "champion_v100"], default="all")
    parser.add_argument("--model-kind", choices=["regressor", "ranker", "hybrid"], default="regressor")
    parser.add_argument("--crash-filter", choices=["none", "classifier"], default="none")
    parser.add_argument("--crash-return-threshold", type=float, default=-0.08)
    parser.add_argument("--crash-drawdown-threshold", type=float, default=-0.12)
    parser.add_argument("--crash-n-estimators", type=int, default=120)
    parser.add_argument("--breakout-filter", choices=["none", "classifier"], default="none")
    parser.add_argument("--breakout-quantile", type=float, default=0.95)
    parser.add_argument("--breakout-n-estimators", type=int, default=120)
    parser.add_argument("--score-mode", choices=["raw", "blended"], default="raw")
    parser.add_argument("--rank-score-weight", type=float, default=1.0)
    parser.add_argument("--pred-score-weight", type=float, default=0.25)
    parser.add_argument("--breakout-score-weight", type=float, default=1.0)
    parser.add_argument("--crash-score-weight", type=float, default=0.25)
    parser.add_argument("--target-mode", choices=["net_return", "future_max_return", "drawdown_penalized"], default="net_return")
    parser.add_argument("--drawdown-penalty-weight", type=float, default=0.5)
    parser.add_argument("--objective", choices=["l2", "l1"], default="l2")
    parser.add_argument("--selection-metric", choices=["compound_return", "annual_return", "capital_annual_return", "capital_compound_return"], default="compound_return")
    parser.add_argument("--min-rank-ic", type=float, default=0.0)
    parser.add_argument("--min-rank-ic-days", type=int, default=0)
    parser.add_argument("--min-capital-annual-return", type=float, default=0.0)
    parser.add_argument("--min-capital-sharpe", type=float, default=0.0)
    parser.add_argument("--max-capital-drawdown", type=float, default=0.0)
    parser.add_argument("--selection-min-trades", type=int, default=0)
    parser.add_argument("--selection-min-trade-years", type=int, default=0)
    parser.add_argument("--n-estimators", type=int, default=360)
    parser.add_argument("--learning-rate", type=float, default=0.035)
    parser.add_argument("--num-leaves", type=int, default=47)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--min-child-samples", type=int, default=50)
    parser.add_argument("--subsample", type=float, default=0.88)
    parser.add_argument("--colsample-bytree", type=float, default=0.88)
    parser.add_argument("--reg-alpha", type=float, default=0.05)
    parser.add_argument("--reg-lambda", type=float, default=0.8)
    parser.add_argument("--buy-slippage", type=float, default=0.0015)
    parser.add_argument("--sell-slippage", type=float, default=0.0015)
    parser.add_argument("--commission", type=float, default=0.00025)
    parser.add_argument("--stamp-tax", type=float, default=0.0005)
    parser.add_argument("--stop-loss", type=float, default=0.0)
    parser.add_argument("--take-profit", type=float, default=0.0)
    parser.add_argument("--execution-stop-loss", default="0")
    parser.add_argument("--execution-take-profit", default="0")
    parser.add_argument("--position-weighting", default="equal")
    parser.add_argument("--capital-scale-mode", default="none")
    parser.add_argument("--capital-tranche-fraction", type=float, default=0.0)
    parser.add_argument("--capital-tranche-fractions", default=None)
    parser.add_argument("--max-gross-exposure", type=float, default=1.0)
    parser.add_argument("--fusion-mode", choices=["none", "horizon_blend"], default="none")
    parser.add_argument("--fusion-horizons", default="5,10,20")
    parser.add_argument("--fusion-eval-horizon", type=int, default=20)
    parser.add_argument("--fusion-pred-score-weight", type=float, default=0.15)
    parser.add_argument("--fusion-breakout-score-weight", type=float, default=0.25)
    parser.add_argument("--fusion-crash-score-weight", type=float, default=0.35)
    parser.add_argument("--eval-only-predictions", default="")
    parser.add_argument("--eval-only-scope", default="")
    parser.add_argument("--eval-only-horizon", type=int, default=0)
    parser.add_argument("--eval-only-source-run-id", default="")
    parser.add_argument("--eval-only-reblend-score", action="store_true")
    parser.add_argument("--latest-inference-source-run-id", default="")
    parser.add_argument("--latest-inference-model-path", default="")
    parser.add_argument("--latest-inference-scope", default="")
    parser.add_argument("--latest-inference-horizon", type=int, default=0)
    parser.add_argument("--no-panel-cache", action="store_true")
    parser.add_argument("--skip-prediction-files", action="store_true")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--progress-every-evals", type=int, default=250)
    parser.add_argument("--print-full-summary", action="store_true")
    args = parser.parse_args()
    if args.capital_tranche_fractions is None:
        args.capital_tranche_fractions = str(args.capital_tranche_fraction)
    args.progress_every_evals = max(int(args.progress_every_evals), 1)

    try:
        run_status.begin(TASK_NAME)
        progress_log("run_start", run_id=args.run_id, start=args.start, end=args.end, horizons=args.horizons, scopes=args.scopes, model_kind=args.model_kind)
        run_status.progress(TASK_NAME, 1, 5, "schema", "创建收益最大化擂台独立表")
        progress_log("schema_start", run_id=args.run_id, db_path=args.db_path)
        ensure_tables(args.db_path)
        if str(args.latest_inference_source_run_id or "").strip():
            run_status.progress(TASK_NAME, 2, 5, "latest_panel", "生成最新截面特征")
            summary = latest_inference_model(args)
            run_status.progress(TASK_NAME, 5, 5, "done", "写入收益擂台最新推荐")
            run_status.done(
                TASK_NAME,
                f"收益擂台最新截面推理完成: {summary.get('scope')} {summary.get('horizon')}日 "
                f"{summary.get('latest_date')} 推荐 {summary.get('latest_count')} 只",
            )
            print(json.dumps({
                "run_id": args.run_id,
                "source_run_id": summary.get("source_run_id"),
                "latest_date": summary.get("latest_date"),
                "latest_count": summary.get("latest_count"),
            }, ensure_ascii=False), flush=True)
            return 0
        if str(args.eval_only_predictions or "").strip():
            run_status.progress(TASK_NAME, 2, 5, "eval_load", "读取已保存预测并快速重评估")
            summary = eval_only_model(args)
            run_status.progress(TASK_NAME, 5, 5, "done", "写入收益擂台重评估结果")
            best = summary["best"]
            run_status.done(
                TASK_NAME,
                f"收益擂台重评估完成: {best['scope']} {best['horizon']}日 Top{best['top_n']} "
                f"信号复利 {best['compound_return']:.2%} 资金年化 {best.get('capital_annual_return', 0):.2%} "
                f"资金回撤 {best.get('capital_max_drawdown', 0):.2%}",
            )
            progress_log(
                "run_done",
                run_id=args.run_id,
                arena_name=args.arena_name,
                best_scope=best.get("scope"),
                best_horizon=best.get("horizon"),
                best_top_n=best.get("top_n"),
                best_capital_annual_return=best.get("capital_annual_return"),
                best_capital_max_drawdown=best.get("capital_max_drawdown"),
                best_capital_sharpe=best.get("capital_sharpe"),
                best_rank_ic=best.get("rank_ic"),
                best_rank_ic_days=best.get("rank_ic_days"),
                best_challenger_score=summary.get("best_challenger_score"),
                best_challenger=champion_payload(best),
                arena_champion=(summary.get("arena_champion") or {}).get("best"),
                arena_champion_score=(summary.get("arena_champion") or {}).get("arena_score"),
                challenge_updated=(summary.get("challenge_result") or {}).get("updated"),
            )
            if args.print_full_summary:
                print(json.dumps(summary, ensure_ascii=False), flush=True)
            else:
                print(json.dumps({
                    "run_id": args.run_id,
                    "summary_path": str(Path(args.data_path) / "profit_arena" / args.run_id / "summary.json"),
                    "best_challenger": champion_payload(best),
                    "best_challenger_score": summary.get("best_challenger_score"),
                    "leaderboards": {
                        "strict_champion_candidates": (summary.get("leaderboards") or {}).get("strict_champion_candidates", [])[:5],
                        "risk_qualified_missing_return": (summary.get("leaderboards") or {}).get("risk_qualified_missing_return", [])[:5],
                        "attack_watchlist_by_annual": (summary.get("leaderboards") or {}).get("attack_watchlist_by_annual", [])[:5],
                        "attack_watchlist_by_return_drawdown_ratio": (summary.get("leaderboards") or {}).get("attack_watchlist_by_return_drawdown_ratio", [])[:5],
                    },
                    "arena_champion": (summary.get("arena_champion") or {}).get("best"),
                    "arena_champion_score": (summary.get("arena_champion") or {}).get("arena_score"),
                    "challenge_updated": (summary.get("challenge_result") or {}).get("updated"),
                }, ensure_ascii=False), flush=True)
            return 0
        run_status.progress(TASK_NAME, 2, 5, "load", "读取主板可交易日线与市值数据")
        horizons = parse_int_list(args.horizons)
        run_status.progress(TASK_NAME, 3, 5, "features", "生成独立技术、流动性、市值和行业状态特征")
        progress_log("panel_load_start", run_id=args.run_id, horizons=horizons)
        data = load_or_build_panel(args, horizons)
        progress_log("panel_load_done", run_id=args.run_id, rows=len(data), columns=len(data.columns))
        if len(data) < int(args.min_train_rows):
            raise RuntimeError(f"收益擂台样本不足: {len(data)}")
        run_status.progress(TASK_NAME, 4, 5, "train", "按收益最大化 walk-forward 训练并分层评估")
        summary = train_model(args, data)
        run_status.progress(TASK_NAME, 5, 5, "done", "写入收益擂台结果")
        best = summary["best"]
        run_status.done(
            TASK_NAME,
            f"收益擂台完成: {best['scope']} {best['horizon']}日 Top{best['top_n']} "
            f"信号复利 {best['compound_return']:.2%} 资金年化 {best.get('capital_annual_return', 0):.2%} "
            f"资金回撤 {best.get('capital_max_drawdown', 0):.2%}",
        )
        progress_log(
            "run_done",
            run_id=args.run_id,
            arena_name=args.arena_name,
            best_scope=best.get("scope"),
            best_horizon=best.get("horizon"),
            best_top_n=best.get("top_n"),
            best_capital_annual_return=best.get("capital_annual_return"),
            best_capital_max_drawdown=best.get("capital_max_drawdown"),
            best_capital_sharpe=best.get("capital_sharpe"),
            best_rank_ic=best.get("rank_ic"),
            best_rank_ic_days=best.get("rank_ic_days"),
            best_challenger_score=summary.get("best_challenger_score"),
            best_challenger=champion_payload(best),
            arena_champion=(summary.get("arena_champion") or {}).get("best"),
            arena_champion_score=(summary.get("arena_champion") or {}).get("arena_score"),
            challenge_updated=(summary.get("challenge_result") or {}).get("updated"),
        )
        if args.print_full_summary:
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        else:
            print(json.dumps({
                "run_id": args.run_id,
                "summary_path": str(Path(args.data_path) / "profit_arena" / args.run_id / "summary.json"),
                "best_challenger": champion_payload(best),
                "best_challenger_score": summary.get("best_challenger_score"),
                "leaderboards": {
                    "strict_champion_candidates": (summary.get("leaderboards") or {}).get("strict_champion_candidates", [])[:5],
                    "risk_qualified_missing_return": (summary.get("leaderboards") or {}).get("risk_qualified_missing_return", [])[:5],
                    "attack_watchlist_by_annual": (summary.get("leaderboards") or {}).get("attack_watchlist_by_annual", [])[:5],
                    "attack_watchlist_by_return_drawdown_ratio": (summary.get("leaderboards") or {}).get("attack_watchlist_by_return_drawdown_ratio", [])[:5],
                },
                "arena_champion": (summary.get("arena_champion") or {}).get("best"),
                "arena_champion_score": (summary.get("arena_champion") or {}).get("arena_score"),
                "challenge_updated": (summary.get("challenge_result") or {}).get("updated"),
            }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        progress_log("run_error", run_id=args.run_id, error=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
