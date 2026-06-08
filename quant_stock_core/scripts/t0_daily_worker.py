from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable.*")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import add_column, open_db, replace_sql, table_columns, table_exists, write_transaction


TASK_NAME = "t0_daily_research"
TIMEMACHINE_TASK_NAME = "t0_daily_timemachine"
COST_RATE = 0.004

T0_MODEL_FEATURES = [
    "rule_score",
    "avg_range_20d",
    "range_std_20d",
    "box_width_20d",
    "box_width_60d",
    "close_position_20d",
    "ma_gap_20d",
    "ma5_ma20_gap",
    "amount_ratio_20d",
    "return_5d",
    "return_20d",
    "drawdown_20d",
    "today_pct",
    "expected_edge",
]


@dataclass
class Candidate:
    run_id: str
    ts_code: str
    name: str
    industry: str
    trade_date: str
    action: str
    score: float
    state: str
    setup: str
    first_action: str
    price: float
    reduce_price: float
    buy_price: float
    stop_price: float
    t_ratio: float
    today_pct: float
    return_5d: float
    return_20d: float
    avg_range_20d: float
    drawdown_20d: float
    amount: float
    avg_amount_20d: float
    expected_edge: float
    target_freq: str
    lookback_days: int
    plan: dict[str, object]
    reasons: list[str]
    risks: list[str]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    if not math.isfinite(value):
        return low
    return max(low, min(high, value))


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def ensure_schema() -> None:
    with open_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS t0_daily_runs (
                run_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                status TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                backtest_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS t0_daily_candidates (
                run_id TEXT NOT NULL,
                ts_code TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                trade_date TEXT NOT NULL,
                action TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT '',
                setup TEXT NOT NULL DEFAULT '',
                first_action TEXT NOT NULL DEFAULT '',
                price REAL NOT NULL DEFAULT 0,
                reduce_price REAL NOT NULL DEFAULT 0,
                buy_price REAL NOT NULL DEFAULT 0,
                stop_price REAL NOT NULL DEFAULT 0,
                t_ratio REAL NOT NULL DEFAULT 0,
                today_pct REAL NOT NULL DEFAULT 0,
                return_5d REAL NOT NULL DEFAULT 0,
                return_20d REAL NOT NULL DEFAULT 0,
                avg_range_20d REAL NOT NULL DEFAULT 0,
                drawdown_20d REAL NOT NULL DEFAULT 0,
                amount REAL NOT NULL DEFAULT 0,
                avg_amount_20d REAL NOT NULL DEFAULT 0,
                expected_edge REAL NOT NULL DEFAULT 0,
                target_freq TEXT NOT NULL DEFAULT 'daily',
                lookback_days INTEGER NOT NULL DEFAULT 0,
                plan_json TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                risks_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, ts_code)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS t0_daily_backtests (
                run_id TEXT NOT NULL,
                ts_code TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                n_days INTEGER NOT NULL DEFAULT 0,
                n_candidates INTEGER NOT NULL DEFAULT 0,
                two_sided_rate REAL NOT NULL DEFAULT 0,
                one_sided_rate REAL NOT NULL DEFAULT 0,
                avg_edge REAL NOT NULL DEFAULT 0,
                total_edge REAL NOT NULL DEFAULT 0,
                avg_next_range REAL NOT NULL DEFAULT 0,
                score REAL NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, ts_code)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t0_daily_candidates_latest ON t0_daily_candidates(trade_date, score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t0_daily_backtests_score ON t0_daily_backtests(run_id, score DESC)")
        existing = table_columns(conn, "t0_daily_candidates")
        candidate_columns = {
            "setup": "TEXT NOT NULL DEFAULT ''",
            "first_action": "TEXT NOT NULL DEFAULT ''",
            "reduce_price": "REAL NOT NULL DEFAULT 0",
            "buy_price": "REAL NOT NULL DEFAULT 0",
            "stop_price": "REAL NOT NULL DEFAULT 0",
            "t_ratio": "REAL NOT NULL DEFAULT 0",
            "plan_json": "LONGTEXT NOT NULL",
        }
        for name, ddl in candidate_columns.items():
            if name not in existing:
                add_column(conn, "t0_daily_candidates", name, ddl)
        if conn.backend == "mysql":
            conn.execute("ALTER TABLE t0_daily_candidates MODIFY COLUMN plan_json LONGTEXT NOT NULL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS t0_daily_time_machine_runs (
                run_id TEXT PRIMARY KEY,
                as_of_date TEXT NOT NULL,
                eval_start_date TEXT NOT NULL,
                eval_end_date TEXT NOT NULL,
                status TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                evaluated_count INTEGER NOT NULL DEFAULT 0,
                avg_t0_edge REAL NOT NULL DEFAULT 0,
                avg_underlying_return REAL NOT NULL DEFAULT 0,
                avg_combined_return REAL NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS t0_daily_time_machine_results (
                run_id TEXT NOT NULL,
                ts_code TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                as_of_date TEXT NOT NULL,
                eval_start_date TEXT NOT NULL,
                eval_end_date TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                n_eval_days INTEGER NOT NULL DEFAULT 0,
                two_sided_count INTEGER NOT NULL DEFAULT 0,
                one_sided_count INTEGER NOT NULL DEFAULT 0,
                t0_edge REAL NOT NULL DEFAULT 0,
                avg_t0_edge REAL NOT NULL DEFAULT 0,
                underlying_return REAL NOT NULL DEFAULT 0,
                combined_return REAL NOT NULL DEFAULT 0,
                max_drawdown REAL NOT NULL DEFAULT 0,
                summary_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, ts_code)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_t0_daily_tm_results_score ON t0_daily_time_machine_results(run_id, combined_return DESC)")


def trade_dates() -> list[str]:
    with open_db() as conn:
        rows = pd.read_sql("SELECT DISTINCT trade_date FROM data_daily_bars ORDER BY trade_date", conn.raw)
    return rows["trade_date"].astype(str).tolist()


def read_recent_daily(lookback: int) -> pd.DataFrame:
    with open_db() as conn:
        if not table_exists(conn, "data_daily_bars"):
            raise RuntimeError("缺少 data_daily_bars，请先更新日线行情")
        raw = conn.raw
        dates = pd.read_sql(
            f"""
            SELECT DISTINCT trade_date
            FROM data_daily_bars
            ORDER BY trade_date DESC
            LIMIT {int(lookback)}
            """,
            raw,
        )["trade_date"].astype(str).tolist()
        if not dates:
            raise RuntimeError("data_daily_bars 为空")
        min_date = min(dates)
        return pd.read_sql(
            f"""
            SELECT d.ts_code, COALESCE(s.name, '') AS name, COALESCE(s.industry, '') AS industry,
                   d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg, d.amount
            FROM data_daily_bars d
            LEFT JOIN data_stock_basic s ON s.ts_code = d.ts_code
            WHERE d.trade_date >= '{min_date}'
              AND COALESCE(s.name, '') NOT LIKE '%%ST%%'
            ORDER BY d.ts_code, d.trade_date
            """,
            raw,
        )


def read_history_for_codes(codes: list[str], days: int) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame()
    with open_db() as conn:
        raw = conn.raw
        dates = pd.read_sql(
            f"""
            SELECT DISTINCT trade_date
            FROM data_daily_bars
            ORDER BY trade_date DESC
            LIMIT {int(days)}
            """,
            raw,
        )["trade_date"].astype(str).tolist()
        if not dates:
            return pd.DataFrame()
        min_date = min(dates)
        placeholders = ",".join(["%s" if conn.backend == "mysql" else "?"] * len(codes))
        return pd.read_sql(
            f"""
            SELECT d.ts_code, COALESCE(s.name, '') AS name, COALESCE(s.industry, '') AS industry,
                   d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg, d.amount
            FROM data_daily_bars d
            LEFT JOIN data_stock_basic s ON s.ts_code = d.ts_code
            WHERE d.trade_date >= '{min_date}' AND d.ts_code IN ({placeholders})
            ORDER BY d.ts_code, d.trade_date
            """,
            raw,
            params=tuple(codes),
        )


def read_history_all(days: int) -> pd.DataFrame:
    with open_db() as conn:
        raw = conn.raw
        dates = pd.read_sql(
            f"""
            SELECT DISTINCT trade_date
            FROM data_daily_bars
            ORDER BY trade_date DESC
            LIMIT {int(days)}
            """,
            raw,
        )["trade_date"].astype(str).tolist()
        if not dates:
            return pd.DataFrame()
        min_date = min(dates)
        return pd.read_sql(
            f"""
            SELECT d.ts_code, COALESCE(s.name, '') AS name, COALESCE(s.industry, '') AS industry,
                   d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg, d.amount
            FROM data_daily_bars d
            LEFT JOIN data_stock_basic s ON s.ts_code = d.ts_code
            WHERE d.trade_date >= '{min_date}'
              AND COALESCE(s.name, '') NOT LIKE '%%ST%%'
              AND COALESCE(s.name, '') NOT LIKE '退市%%'
            ORDER BY d.ts_code, d.trade_date
            """,
            raw,
        )


def read_daily_between(start_date: str, end_date: str) -> pd.DataFrame:
    with open_db() as conn:
        raw = conn.raw
        return pd.read_sql(
            f"""
            SELECT d.ts_code, COALESCE(s.name, '') AS name, COALESCE(s.industry, '') AS industry,
                   d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg, d.amount
            FROM data_daily_bars d
            LEFT JOIN data_stock_basic s ON s.ts_code = d.ts_code
            WHERE d.trade_date >= '{start_date}' AND d.trade_date <= '{end_date}'
              AND COALESCE(s.name, '') NOT LIKE '%%ST%%'
            ORDER BY d.ts_code, d.trade_date
            """,
            raw,
        )


def add_metrics(df: pd.DataFrame, metric_window: int = 20) -> pd.DataFrame:
    df = df.copy()
    window = max(5, int(metric_window or 20))
    min_periods = max(5, min(20, window // 2))
    for col in ["open", "high", "low", "close", "pre_close", "pct_chg", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.sort_values(["ts_code", "trade_date"])
    group = df.groupby("ts_code", group_keys=False)
    prev_close_5 = group["close"].shift(4)
    prev_close_20 = group["close"].shift(window - 1)
    rolling_high_20 = group["high"].rolling(window, min_periods=min_periods).max().reset_index(level=0, drop=True)
    rolling_low_20 = group["low"].rolling(window, min_periods=min_periods).min().reset_index(level=0, drop=True)
    rolling_high_60 = group["high"].rolling(60, min_periods=20).max().reset_index(level=0, drop=True)
    rolling_low_60 = group["low"].rolling(60, min_periods=20).min().reset_index(level=0, drop=True)
    df["return_5d"] = df["close"] / prev_close_5.replace(0, pd.NA) - 1
    df["return_20d"] = df["close"] / prev_close_20.replace(0, pd.NA) - 1
    df["range"] = (df["high"] - df["low"]) / df["close"].replace(0, pd.NA)
    df["avg_range_20d"] = group["range"].rolling(window, min_periods=min_periods).mean().reset_index(level=0, drop=True)
    df["range_std_20d"] = group["range"].rolling(window, min_periods=min_periods).std().reset_index(level=0, drop=True)
    df["avg_amount_20d"] = group["amount"].rolling(window, min_periods=min_periods).mean().reset_index(level=0, drop=True)
    df["ma5"] = group["close"].rolling(5, min_periods=3).mean().reset_index(level=0, drop=True)
    df["ma20"] = group["close"].rolling(window, min_periods=min_periods).mean().reset_index(level=0, drop=True)
    df["ma60"] = group["close"].rolling(60, min_periods=20).mean().reset_index(level=0, drop=True)
    df["high_20d"] = rolling_high_20
    df["low_20d"] = rolling_low_20
    df["high_60d"] = rolling_high_60
    df["low_60d"] = rolling_low_60
    df["box_width_20d"] = (rolling_high_20 - rolling_low_20) / df["close"].replace(0, pd.NA)
    df["box_width_60d"] = (rolling_high_60 - rolling_low_60) / df["close"].replace(0, pd.NA)
    df["close_position_20d"] = (df["close"] - rolling_low_20) / (rolling_high_20 - rolling_low_20).replace(0, pd.NA)
    df["ma_gap_20d"] = (df["close"] / df["ma20"].replace(0, pd.NA) - 1).abs()
    df["ma5_ma20_gap"] = (df["ma5"] / df["ma20"].replace(0, pd.NA) - 1).abs()
    df["amount_ratio_20d"] = df["amount"] / df["avg_amount_20d"].replace(0, pd.NA)
    df["drawdown_20d"] = df["close"] / rolling_high_20.replace(0, pd.NA) - 1
    return df.replace([math.inf, -math.inf], pd.NA).fillna(0.0)


def round_price(value: float) -> float:
    return round(max(safe_float(value), 0.0), 2)


def t_ratio_from_score(score: float, state: str) -> float:
    if "停手" in state or "破位" in state:
        return 0.0
    if score >= 86:
        return 0.30
    if score >= 74:
        return 0.20
    if score >= 62:
        return 0.10
    return 0.0


def score_row(row: pd.Series, run_id: str) -> Candidate:
    avg_range = safe_float(row.get("avg_range_20d"))
    range_std = safe_float(row.get("range_std_20d"))
    avg_amount = safe_float(row.get("avg_amount_20d"))
    amount = safe_float(row.get("amount"))
    amount_ratio = safe_float(row.get("amount_ratio_20d"), amount / avg_amount if avg_amount > 0 else 0.0)
    today_pct = safe_float(row.get("pct_chg")) / 100
    return_20 = safe_float(row.get("return_20d"))
    drawdown_20 = safe_float(row.get("drawdown_20d"))
    return_5 = safe_float(row.get("return_5d"))
    close = safe_float(row.get("close"))
    high_20 = safe_float(row.get("high_20d"))
    low_20 = safe_float(row.get("low_20d"))
    box_width = safe_float(row.get("box_width_20d"))
    box_width_60 = safe_float(row.get("box_width_60d"))
    close_pos = clamp(safe_float(row.get("close_position_20d")), 0, 1)
    ma_gap = safe_float(row.get("ma_gap_20d"))
    ma5_ma20_gap = safe_float(row.get("ma5_ma20_gap"))
    ma5 = safe_float(row.get("ma5"))
    ma20 = safe_float(row.get("ma20"))
    ma60 = safe_float(row.get("ma60"))
    day_range = safe_float(row.get("range"))
    range_cv = range_std / avg_range if avg_range > 0 else 0.0

    volatility_score = clamp((avg_range - 0.018) / 0.035, 0, 1) * 22
    liquidity_score = clamp((math.log10(max(avg_amount, 1)) - 4.8) / 2.3, 0, 1) * 18
    box_score = (
        clamp((box_width - 0.06) / 0.18, 0, 1) * 10
        + clamp((0.34 - abs(close_pos - 0.5)) / 0.34, 0, 1) * 10
        + clamp((0.80 - range_cv) / 0.80, 0, 1) * 8
        + clamp((0.035 - ma5_ma20_gap) / 0.035, 0, 1) * 8
    )
    mean_reversion_score = clamp((abs(today_pct) - 0.004) / 0.035, 0, 1) * 10
    trend_penalty = clamp((abs(return_20) - 0.10) / 0.22, 0, 1) * 18
    broken_penalty = 0.0
    if close > 0 and low_20 > 0 and close < low_20 * 1.012:
        broken_penalty += 12
    if return_5 < -0.10 and today_pct < 0:
        broken_penalty += 8
    score = 24 + volatility_score + liquidity_score + box_score + mean_reversion_score - trend_penalty - broken_penalty
    reasons: list[str] = []
    risks: list[str] = []

    if avg_range >= 0.026:
        reasons.append(f"20日平均振幅 {avg_range * 100:.2f}%，扣成本后有可操作空间")
    else:
        risks.append(f"20日平均振幅 {avg_range * 100:.2f}%，日内空间偏薄")
    if avg_amount > 0:
        reasons.append(f"20日平均成交额 {avg_amount:.0f}，满足T仓进出流动性粗筛")

    if box_width >= 0.07 and 0.20 <= close_pos <= 0.80:
        reasons.append(f"20日箱体宽度 {box_width * 100:.2f}%，收盘位于箱体 {close_pos * 100:.0f}%")
    elif box_width > 0:
        risks.append(f"箱体位置 {close_pos * 100:.0f}% / 宽度 {box_width * 100:.2f}%，计划价需保守")

    if ma5 > 0 and ma20 > 0 and ma60 > 0 and abs(ma20 / ma60 - 1) <= 0.06 and ma5_ma20_gap <= 0.035:
        reasons.append("均线收敛，偏适合箱体内高抛低吸")
    elif ma_gap >= 0.07:
        risks.append("价格偏离20日均线较大，容易走单边")

    if amount_ratio >= 2.0 and today_pct <= -0.025:
        risks.append(f"当日成交额为20日均量 {amount_ratio:.1f} 倍且下跌，疑似放量砸盘")
        score -= 16
    elif amount_ratio >= 1.6 and today_pct < 0:
        risks.append(f"放量下跌，成交额为20日均量 {amount_ratio:.1f} 倍")
        score -= 8
    elif amount_ratio >= 1.6 and today_pct > 0:
        reasons.append(f"放量上攻，成交额为20日均量 {amount_ratio:.1f} 倍，冲高先减更优")
    elif 0 < amount_ratio < 0.55:
        risks.append(f"成交额仅为20日均量 {amount_ratio:.1f} 倍，缩量时计划价可能难触发")

    state = "箱体震荡"
    setup = "箱体高抛低吸"
    first_action = "挂单等待"
    if close > ma5 > ma20 and return_20 > 0.10:
        state = "趋势偏强"
        setup = "强势回踩T"
        first_action = "回踩低吸优先"
        risks.append("强趋势票高抛容易卖飞，卖出价必须靠近压力位")
        score -= 6
    elif close < ma5 < ma20 and return_20 < -0.10:
        state = "趋势偏弱"
        setup = "弱势反抽T"
        first_action = "冲高先卖"
        risks.append("弱趋势票低吸风险较高")
        score -= 8
    elif avg_range >= 0.045 and box_width >= 0.10:
        state = "高波震荡"
        setup = "宽幅箱体T"
        first_action = "两边挂单"
        reasons.append("高波震荡优先纳入日线做T计划")

    if drawdown_20 < -0.18:
        risks.append(f"距20日高点回撤 {drawdown_20 * 100:.2f}%，先按观察候选处理")
        score -= 10
    if close > 0 and low_20 > 0 and close < low_20 * 1.006:
        state = "破位停手"
        setup = "停止做T"
        first_action = "停手观察"
        risks.append("收盘贴近或跌破20日箱体下沿，先停止低吸")
        score -= 28

    if close_pos >= 0.68 and today_pct >= -0.01:
        first_action = "冲高先卖"
    elif close_pos <= 0.32 and today_pct <= 0.015 and state != "破位停手":
        first_action = "回踩先买"
    elif abs(today_pct) <= 0.01 and state == "箱体震荡":
        first_action = "两边挂单"

    band = clamp(avg_range * 0.58, 0.009, 0.042)
    if box_width > 0:
        band = min(band, clamp(box_width * 0.28, 0.009, 0.045))
    if amount_ratio >= 1.8 and today_pct < 0:
        band *= 0.85
    if state == "趋势偏强":
        band *= 1.05
    if state == "趋势偏弱":
        band *= 0.90

    base_reduce = close * (1 + band)
    base_buy = close * (1 - band)
    box_resistance = high_20 * 0.992 if high_20 > 0 else 0.0
    box_support = low_20 * 1.008 if low_20 > 0 else 0.0
    reduce_price = base_reduce
    buy_price = base_buy
    if box_resistance > close and box_resistance <= close * 1.06:
        reduce_price = min(base_reduce * 1.15, box_resistance)
    if box_support > 0 and box_support < close and box_support >= close * 0.94:
        buy_price = max(base_buy * 0.985, box_support)
    reduce_price = min(reduce_price, close * 1.055)
    buy_price = max(buy_price, close * 0.945)
    if reduce_price <= close:
        reduce_price = close * (1 + band)
    if buy_price >= close:
        buy_price = close * (1 - band)
    stop_band = clamp(max(avg_range * 1.05, box_width * 0.22 if box_width > 0 else 0), 0.018, 0.065)
    structure_stop = low_20 * 0.985 if low_20 > 0 and low_20 >= close * 0.86 else close * (1 - stop_band)
    stop_price = max(close * (1 - stop_band), structure_stop)
    expected_edge = band * 2 - COST_RATE
    if first_action == "冲高先卖":
        reasons.append("收盘偏箱体上半区，交易脚本以冲高减T仓为先")
    elif first_action == "回踩先买":
        reasons.append("收盘偏箱体下半区，交易脚本以回踩接回为先")
    elif first_action == "两边挂单":
        reasons.append("收盘居中且波动充足，适合两边挂计划价")
    if expected_edge <= 0.012:
        risks.append("扣成本后价差偏薄，优先级下调")
        score -= 10

    score = round(clamp(score, 0, 100), 1)
    t_ratio = t_ratio_from_score(score, state)
    action = "优先计划" if score >= 76 and t_ratio > 0 else "候选观察" if score >= 58 else "暂缓"
    if t_ratio <= 0 and action != "暂缓":
        action = "候选观察"
    plan = {
        "setup": setup,
        "first_action": first_action,
        "reduce_price": round_price(reduce_price),
        "buy_price": round_price(buy_price),
        "stop_price": round_price(stop_price),
        "t_ratio": t_ratio,
        "script": {
            "open": first_action,
            "reduce": f"冲高到 {round_price(reduce_price):.2f} 附近只卖T仓，不追卖",
            "buy": f"回落到 {round_price(buy_price):.2f} 附近接回T仓，不加隔夜仓",
            "stop": f"跌破 {round_price(stop_price):.2f} 停止低吸，等待重新站回箱体",
        },
        "box": {
            "high_20d": round_price(high_20),
            "low_20d": round_price(low_20),
            "width_20d": box_width,
            "width_60d": box_width_60,
            "close_position_20d": close_pos,
        },
        "execution": [
            "只用可T底仓，不扩大隔夜仓位",
            "先触发哪边做哪边，未到计划价不追",
            "跌破停手线后停止低吸，等待重新站回箱体",
        ],
    }
    return Candidate(
        run_id=run_id,
        ts_code=str(row.get("ts_code") or ""),
        name=str(row.get("name") or ""),
        industry=str(row.get("industry") or ""),
        trade_date=str(row.get("trade_date") or ""),
        action=action,
        score=score,
        state=state,
        setup=setup,
        first_action=first_action,
        price=close,
        reduce_price=round_price(reduce_price),
        buy_price=round_price(buy_price),
        stop_price=round_price(stop_price),
        t_ratio=t_ratio,
        today_pct=today_pct,
        return_5d=return_5,
        return_20d=return_20,
        avg_range_20d=avg_range,
        drawdown_20d=drawdown_20,
        amount=safe_float(row.get("amount")),
        avg_amount_20d=avg_amount,
        expected_edge=expected_edge,
        target_freq="daily",
        lookback_days=0,
        plan=plan,
        reasons=reasons,
        risks=risks,
    )


def build_candidates(df: pd.DataFrame, run_id: str, limit: int, metric_window: int = 20) -> list[Candidate]:
    latest_date = str(df["trade_date"].max())
    latest = add_metrics(df, metric_window)
    latest = latest[latest["trade_date"] == latest_date].copy()
    candidates = [score_row(row, run_id) for _, row in latest.iterrows()]
    candidates = [item for item in candidates if item.score >= 52]
    candidates.sort(key=lambda item: (item.score, item.avg_amount_20d), reverse=True)
    return candidates[:limit]


def candidate_pool_limit(display_limit: int, explicit_pool_limit: int = 0) -> int:
    display = max(1, int(display_limit))
    if explicit_pool_limit > 0:
        return max(display, int(explicit_pool_limit))
    return max(display, display * 3)


def t0_model_feature_row(row: pd.Series, candidate: Candidate) -> dict[str, float]:
    return {
        "rule_score": safe_float(candidate.score),
        "avg_range_20d": safe_float(row.get("avg_range_20d")),
        "range_std_20d": safe_float(row.get("range_std_20d")),
        "box_width_20d": safe_float(row.get("box_width_20d")),
        "box_width_60d": safe_float(row.get("box_width_60d")),
        "close_position_20d": clamp(safe_float(row.get("close_position_20d")), 0, 1),
        "ma_gap_20d": safe_float(row.get("ma_gap_20d")),
        "ma5_ma20_gap": safe_float(row.get("ma5_ma20_gap")),
        "amount_ratio_20d": safe_float(row.get("amount_ratio_20d")),
        "return_5d": safe_float(row.get("return_5d")),
        "return_20d": safe_float(row.get("return_20d")),
        "drawdown_20d": safe_float(row.get("drawdown_20d")),
        "today_pct": safe_float(row.get("pct_chg")) / 100,
        "expected_edge": safe_float(candidate.expected_edge),
    }


def build_t0_model_samples(history: pd.DataFrame, run_id: str, metric_window: int = 20) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    df = add_metrics(history, metric_window)
    rows: list[dict[str, object]] = []
    for code, group in df.groupby("ts_code"):
        group = group.sort_values("trade_date").reset_index(drop=True)
        for idx in range(max(60, metric_window), len(group) - 1):
            row = group.iloc[idx]
            nxt = group.iloc[idx + 1]
            candidate = score_row(row, run_id)
            if candidate.score < 50 or candidate.price <= 0:
                continue
            high_hit = safe_float(nxt["high"]) >= candidate.reduce_price
            low_hit = safe_float(nxt["low"]) <= candidate.buy_price
            stop_hit = safe_float(nxt["low"]) <= candidate.stop_price
            edge = (candidate.reduce_price - candidate.buy_price) / max(candidate.price, 0.01) - COST_RATE
            feature_row = t0_model_feature_row(row, candidate)
            rows.append({
                **feature_row,
                "ts_code": candidate.ts_code,
                "trade_date": str(row.get("trade_date") or ""),
                "year": int(str(row.get("trade_date") or "0000")[:4] or 0),
                "label": int(high_hit and low_hit and edge >= 0.006 and not stop_hit),
                "two_sided": int(high_hit and low_hit),
                "one_sided": int(high_hit ^ low_hit),
                "stop_hit": int(stop_hit),
                "edge": edge if high_hit and low_hit and not stop_hit else 0.0,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.replace([np.inf, -np.inf], np.nan)
    out[T0_MODEL_FEATURES] = out[T0_MODEL_FEATURES].fillna(0.0)
    return out


def t0_rank_ic(frame: pd.DataFrame) -> float:
    if frame.empty or frame["model_score"].nunique() <= 1 or frame["edge"].nunique() <= 1:
        return 0.0
    return safe_float(frame["model_score"].corr(frame["edge"], method="spearman"))


def t0_quality_summary(samples: pd.DataFrame, pred: pd.DataFrame, folds: list[dict[str, object]]) -> dict[str, object]:
    years = sorted(int(year) for year in samples["year"].dropna().unique()) if not samples.empty else []
    fold_years = [int(item["year"]) for item in folds if "year" in item]
    ambiguous = safe_float(((samples["two_sided"] == 1) | (samples["stop_hit"] == 1)).mean()) if not samples.empty else 0.0
    return {
        "sample_rows": int(len(samples)),
        "prediction_rows": int(len(pred)),
        "sample_years": years,
        "fold_years": fold_years,
        "fold_count": int(len(folds)),
        "missing_fold_years": [int(year) for year in years if year >= (min(fold_years) if fold_years else 9999) and year not in fold_years],
        "overall_positive_rate": safe_float(samples["label"].mean()) if not samples.empty else 0.0,
        "tested_positive_rate": safe_float(pred["label"].mean()) if not pred.empty else 0.0,
        "path_ambiguity_rate": ambiguous,
        "path_assumption": "日线 OHLC 无法确认盘中高抛、低吸、停手线的先后顺序；标签要求高低两边触达且未触停手线，仍属于近似评估。",
        "universe_note": "模型样本来自规则分达到候选线的日线做T候选，不代表全市场无条件预测能力。",
    }


def train_t0_admission_model(history: pd.DataFrame, latest: pd.DataFrame, candidates: list[Candidate], run_id: str, data_path: str, metric_window: int = 20) -> dict[str, object]:
    import lightgbm as lgb
    from sklearn.metrics import average_precision_score, roc_auc_score

    samples = build_t0_model_samples(history, run_id, metric_window)
    if samples.empty:
        return {"status": "skipped", "reason": "no_samples", "candidate_scores": {}, "feature_importance": []}
    years = sorted(int(year) for year in samples["year"].dropna().unique() if int(year) > 0)
    if len(years) < 3:
        return {"status": "skipped", "reason": "insufficient_years", "candidate_scores": {}, "feature_importance": []}
    min_test_year = max(years[0] + 1, years[-4] if len(years) >= 4 else years[1])
    test_years = [year for year in years if year >= min_test_year]
    x_all = samples[T0_MODEL_FEATURES].astype(float)
    y_all = samples["label"].astype(int)
    predictions: list[pd.DataFrame] = []
    folds: list[dict[str, object]] = []
    models: list[object] = []
    importance = pd.Series(0.0, index=T0_MODEL_FEATURES, dtype="float64")
    for year in test_years:
        train_mask = samples["year"] < year
        test_mask = samples["year"] == year
        if int(train_mask.sum()) < 500 or int(test_mask.sum()) < 50:
            continue
        y_train = y_all.loc[train_mask]
        pos = int(y_train.sum())
        if pos < 20:
            continue
        neg = int(len(y_train) - pos)
        model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=220,
            learning_rate=0.035,
            num_leaves=24,
            max_depth=5,
            min_child_samples=28,
            subsample=0.86,
            colsample_bytree=0.9,
            reg_alpha=0.08,
            reg_lambda=1.1,
            scale_pos_weight=max(1.0, neg / max(pos, 1)),
            random_state=20260607,
            n_jobs=4,
            verbosity=-1,
        )
        model.fit(x_all.loc[train_mask], y_train)
        prob = model.predict_proba(x_all.loc[test_mask])[:, 1]
        fold = samples.loc[test_mask].copy()
        fold["prob"] = prob.astype(float)
        fold["model_score"] = fold["prob"] * 100.0
        predictions.append(fold)
        top = fold.sort_values(["trade_date", "model_score"], ascending=[True, False]).groupby("trade_date", group_keys=False).head(10)
        folds.append({
            "year": int(year),
            "rows": int(len(fold)),
            "train_rows": int(train_mask.sum()),
            "train_positive_rate": safe_float(y_train.mean()),
            "positive_rate": safe_float(fold["label"].mean()),
            "path_ambiguity_rate": safe_float(((fold["two_sided"] == 1) | (fold["stop_hit"] == 1)).mean()),
            "top10_two_sided": safe_float(top["two_sided"].mean()),
            "top10_avg_edge": safe_float(top["edge"].mean()),
            "top10_total_edge": safe_float(top["edge"].sum()),
            "rank_ic": t0_rank_ic(fold),
            "roc_auc": safe_float(roc_auc_score(fold["label"], prob)) if fold["label"].nunique() > 1 else 0.0,
            "avg_precision": safe_float(average_precision_score(fold["label"], prob)) if fold["label"].nunique() > 1 else 0.0,
        })
        importance += pd.Series(model.feature_importances_, index=T0_MODEL_FEATURES)
        models.append(model)
    if not models:
        return {"status": "skipped", "reason": "no_walk_forward", "candidate_scores": {}, "feature_importance": []}
    pred = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    latest_by_code = {str(row.get("ts_code") or ""): row for _, row in latest.iterrows()}
    latest_rows: list[dict[str, object]] = []
    for item in candidates:
        row = latest_by_code.get(item.ts_code)
        if row is None:
            continue
        latest_rows.append({"ts_code": item.ts_code, **t0_model_feature_row(row, item)})
    latest_scores: dict[str, float] = {}
    if latest_rows:
        latest_frame = pd.DataFrame(latest_rows)
        latest_frame[T0_MODEL_FEATURES] = latest_frame[T0_MODEL_FEATURES].fillna(0.0)
        latest_frame["model_score"] = models[-1].predict_proba(latest_frame[T0_MODEL_FEATURES].astype(float))[:, 1] * 100.0
        latest_scores = {str(row.ts_code): safe_float(row.model_score) for row in latest_frame.itertuples(index=False)}
    out_dir = Path(data_path) / "t0_daily_model" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(models[-1], out_dir / "latest_model.joblib")
    feature_importance = [
        {"feature": str(feature), "importance": safe_float(value), "rank_no": int(rank)}
        for rank, (feature, value) in enumerate((importance / max(len(models), 1)).sort_values(ascending=False).items(), 1)
    ]
    return {
        "status": "success",
        "rows": int(len(samples)),
        "positive_rate": safe_float(samples["label"].mean()),
        "test_start": str(pred["trade_date"].min()) if not pred.empty else "",
        "test_end": str(pred["trade_date"].max()) if not pred.empty else "",
        "rank_ic": safe_float(pd.Series([safe_float(item["rank_ic"]) for item in folds]).mean()) if folds else 0.0,
        "top10_avg_edge": safe_float(pd.Series([safe_float(item["top10_avg_edge"]) for item in folds]).mean()) if folds else 0.0,
        "top10_two_sided": safe_float(pd.Series([safe_float(item["top10_two_sided"]) for item in folds]).mean()) if folds else 0.0,
        "folds": folds,
        "evaluation_quality": t0_quality_summary(samples, pred, folds),
        "feature_importance": feature_importance,
        "candidate_scores": latest_scores,
        "model_path": str(out_dir / "latest_model.joblib"),
    }


def apply_model_scores(candidates: list[Candidate], model_summary: dict[str, object]) -> list[Candidate]:
    scores = model_summary.get("candidate_scores")
    if not isinstance(scores, dict) or not scores:
        return candidates
    out: list[Candidate] = []
    for item in candidates:
        model_score = safe_float(scores.get(item.ts_code), -1.0)
        if model_score >= 0:
            original = item.score
            item.score = round(clamp(original * 0.62 + model_score * 0.38, 0, 100), 1)
            item.plan["model_score"] = round(model_score, 2)
            item.reasons.insert(0, f"做T模型准入分 {model_score:.1f}，规则分 {original:.1f}")
            if model_score < 42:
                item.risks.append("模型认为次日两边触达概率偏低，降为观察")
                item.action = "候选观察" if item.score >= 58 else "暂缓"
                item.t_ratio = min(item.t_ratio, 0.10)
            elif model_score >= 72 and item.action != "暂缓":
                item.t_ratio = max(item.t_ratio, 0.20)
        out.append(item)
    out.sort(key=lambda item: (item.score, item.avg_amount_20d), reverse=True)
    return out


def backtest_candidates(history: pd.DataFrame, run_id: str, metric_window: int = 20) -> list[dict[str, object]]:
    if history.empty:
        return []
    df = add_metrics(history, metric_window)
    out: list[dict[str, object]] = []
    for code, group in df.groupby("ts_code"):
        group = group.sort_values("trade_date").reset_index(drop=True)
        rows = []
        for idx in range(20, len(group) - 1):
            row = group.iloc[idx]
            nxt = group.iloc[idx + 1]
            candidate = score_row(row, run_id)
            if candidate.score < 58:
                continue
            reduce_price = candidate.reduce_price
            buy_price = candidate.buy_price
            stop_price = candidate.stop_price
            high_hit = safe_float(nxt["high"]) >= reduce_price
            low_hit = safe_float(nxt["low"]) <= buy_price
            stop_hit = safe_float(nxt["low"]) <= stop_price
            two_sided = high_hit and low_hit
            one_sided = high_hit ^ low_hit
            raw_edge = (reduce_price - buy_price) / max(candidate.price, 0.01) - COST_RATE
            rows.append({
                "two_sided": two_sided,
                "one_sided": one_sided,
                "stop_hit": stop_hit,
                "sell_first_miss": high_hit and not low_hit,
                "buy_first_drawdown": low_hit and stop_hit,
                "edge": raw_edge if two_sided else 0.0,
                "next_range": (safe_float(nxt["high"]) - safe_float(nxt["low"])) / max(safe_float(nxt["close"]), 0.01),
                "score": candidate.score,
                "trade_date": str(nxt.get("trade_date") or ""),
            })
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        recent = frame.tail(40)
        latest = group.iloc[-1]
        n = len(frame)
        two_sided_rate = safe_float(frame["two_sided"].mean())
        one_sided_rate = safe_float(frame["one_sided"].mean())
        avg_edge = safe_float(frame["edge"].mean())
        total_edge = safe_float(frame["edge"].sum())
        avg_next_range = safe_float(frame["next_range"].mean())
        recent_n = int(len(recent))
        recent_two_sided_rate = safe_float(recent["two_sided"].mean()) if recent_n else 0.0
        recent_one_sided_rate = safe_float(recent["one_sided"].mean()) if recent_n else 0.0
        recent_avg_edge = safe_float(recent["edge"].mean()) if recent_n else 0.0
        recent_total_edge = safe_float(recent["edge"].sum()) if recent_n else 0.0
        recent_avg_next_range = safe_float(recent["next_range"].mean()) if recent_n else 0.0
        stop_hit_rate = safe_float(frame["stop_hit"].mean())
        sell_first_miss_rate = safe_float(frame["sell_first_miss"].mean())
        buy_first_drawdown_rate = safe_float(frame["buy_first_drawdown"].mean())
        recent_stop_hit_rate = safe_float(recent["stop_hit"].mean()) if recent_n else 0.0
        recent_sell_first_miss_rate = safe_float(recent["sell_first_miss"].mean()) if recent_n else 0.0
        recent_buy_first_drawdown_rate = safe_float(recent["buy_first_drawdown"].mean()) if recent_n else 0.0
        score = round(clamp(
            two_sided_rate * 60
            + avg_edge * 950
            + avg_next_range * 105
            - one_sided_rate * 12
            - stop_hit_rate * 18
            - buy_first_drawdown_rate * 12,
            0,
            100,
        ), 2)
        out.append({
            "run_id": run_id,
            "ts_code": str(code),
            "name": str(latest.get("name") or ""),
            "industry": str(latest.get("industry") or ""),
            "n_days": int(len(group)),
            "n_candidates": int(n),
            "two_sided_rate": two_sided_rate,
            "one_sided_rate": one_sided_rate,
            "avg_edge": avg_edge,
            "total_edge": total_edge,
            "avg_next_range": avg_next_range,
            "score": score,
            "summary_json": json.dumps({
                "note": "日线近似回测：只有次日 high/low 同时触达高抛和低吸区间才计为完成；不知道日内顺序，结果偏保守但仍可能高估成交。",
                "cost_rate": COST_RATE,
                "recent_2m": {
                    "n_candidates": recent_n,
                    "start_date": str(recent["trade_date"].iloc[0]) if recent_n else "",
                    "end_date": str(recent["trade_date"].iloc[-1]) if recent_n else "",
                    "two_sided_rate": recent_two_sided_rate,
                    "one_sided_rate": recent_one_sided_rate,
                    "stop_hit_rate": recent_stop_hit_rate,
                    "sell_first_miss_rate": recent_sell_first_miss_rate,
                    "buy_first_drawdown_rate": recent_buy_first_drawdown_rate,
                    "avg_edge": recent_avg_edge,
                    "total_edge": recent_total_edge,
                    "avg_next_range": recent_avg_next_range,
                },
                "trader_risk": {
                    "stop_hit_rate": stop_hit_rate,
                    "sell_first_miss_rate": sell_first_miss_rate,
                    "buy_first_drawdown_rate": buy_first_drawdown_rate,
                },
            }, ensure_ascii=False),
            "updated_at": now(),
        })
    out.sort(key=lambda row: safe_float(row["score"]), reverse=True)
    return out


def recent_backtest_stats(row: dict[str, object]) -> dict[str, float]:
    try:
        summary = json.loads(str(row.get("summary_json") or "{}"))
        recent = summary.get("recent_2m") or {}
    except Exception:
        recent = {}
    return {
        "n_candidates": safe_float(recent.get("n_candidates")),
        "two_sided_rate": safe_float(recent.get("two_sided_rate")),
        "one_sided_rate": safe_float(recent.get("one_sided_rate")),
        "stop_hit_rate": safe_float(recent.get("stop_hit_rate")),
        "sell_first_miss_rate": safe_float(recent.get("sell_first_miss_rate")),
        "buy_first_drawdown_rate": safe_float(recent.get("buy_first_drawdown_rate")),
        "avg_edge": safe_float(recent.get("avg_edge")),
        "total_edge": safe_float(recent.get("total_edge")),
        "avg_next_range": safe_float(recent.get("avg_next_range")),
    }


def t0_admission_level(recent: dict[str, float], score: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    total = recent["total_edge"]
    two = recent["two_sided_rate"]
    one = recent["one_sided_rate"]
    stop = recent["stop_hit_rate"]
    sell_miss = recent["sell_first_miss_rate"]
    drawdown = recent["buy_first_drawdown_rate"]
    if total < 0.18:
        reasons.append(f"近2月累计价差 {total * 100:.2f}% 低于18%准入线")
    if two < 0.10:
        reasons.append(f"近2月两边触达 {two * 100:.2f}% 低于10%准入线")
    if one > 0.72:
        reasons.append(f"近2月单边触达 {one * 100:.2f}% 高于72%上限")
    if stop > 0.12:
        reasons.append(f"近2月停手线触达 {stop * 100:.2f}% 高于12%上限")
    if sell_miss > 0.42:
        reasons.append(f"近2月卖飞风险 {sell_miss * 100:.2f}% 高于42%上限")
    if drawdown > 0.08:
        reasons.append(f"近2月接刀风险 {drawdown * 100:.2f}% 高于8%上限")
    if score >= 76 and not reasons:
        return "trade", []
    soft_failures = len(reasons)
    if total >= 0.12 and two >= 0.075 and one <= 0.78 and stop <= 0.18 and drawdown <= 0.12 and soft_failures <= 2:
        return "watch", reasons
    return "pause", reasons


def apply_effective_scores(candidates: list[Candidate], backtests: list[dict[str, object]]) -> list[Candidate]:
    backtest_by_code = {str(row.get("ts_code") or ""): row for row in backtests}
    rescored: list[Candidate] = []
    for item in candidates:
        original_score = item.score
        row = backtest_by_code.get(item.ts_code)
        if row is None:
            item.score = round(min(original_score, 45.0), 1)
            item.action = "暂缓"
            item.risks.append("缺少近2月做T验证，不进入实盘Top10")
            rescored.append(item)
            continue

        recent = recent_backtest_stats(row)
        recent_total = recent["total_edge"]
        recent_two = recent["two_sided_rate"]
        recent_avg = recent["avg_edge"]
        recent_one = recent["one_sided_rate"]
        recent_stop = recent["stop_hit_rate"]
        recent_sell_miss = recent["sell_first_miss_rate"]
        recent_drawdown = recent["buy_first_drawdown_rate"]
        liquidity = clamp((math.log10(max(item.avg_amount_20d, 1)) - 4.8) / 2.3, 0, 1)
        suitability = clamp(original_score / 100, 0, 1)
        score = (
            clamp(recent_total / 0.30, 0, 1) * 38
            + clamp(recent_two / 0.18, 0, 1) * 24
            + clamp(recent_avg / 0.008, 0, 1) * 14
            + clamp(safe_float(row.get("score")) / 100, 0, 1) * 8
            + liquidity * 8
            + suitability * 8
        )
        admission, admission_reasons = t0_admission_level(recent, score)
        if recent_total <= 0:
            score -= 35
            item.risks.append("近2月做T累计收益为0或为负，剔除优先计划")
        if recent_two <= 0:
            score -= 25
            item.risks.append("近2月没有两边触达样本，不适合当前规则做T")
        if recent_one > 0.35:
            score -= clamp((recent_one - 0.35) / 0.45, 0, 1) * 22
            item.risks.append(f"近2月单边触达 {recent_one * 100:.2f}%，容易卖出后接不回或低吸后继续跌")
        if recent_sell_miss > 0.35:
            score -= clamp((recent_sell_miss - 0.35) / 0.30, 0, 1) * 12
            item.risks.append(f"近2月卖飞风险 {recent_sell_miss * 100:.2f}%，高抛后接回难度偏高")
        if recent_stop > 0.20:
            score -= 14
            item.risks.append(f"近2月停手线触达 {recent_stop * 100:.2f}%，结构破位频繁")
        if recent_drawdown > 0.12:
            score -= 10
            item.risks.append(f"近2月低吸后触及停手线 {recent_drawdown * 100:.2f}%，接刀风险偏高")
        if item.drawdown_20d < -0.18:
            score -= 5
        amount_ratio = item.amount / item.avg_amount_20d if item.avg_amount_20d > 0 else 0.0
        if 0 < amount_ratio < 0.55:
            score -= 6
        item.score = round(clamp(score, 0, 100), 1)
        if recent_total > 0 and recent_two > 0:
            item.reasons.insert(0, f"近2月做T累计 {recent_total * 100:.2f}%，两边触达 {recent_two * 100:.2f}%")
        for reason in admission_reasons[:2]:
            item.risks.append(reason)
        if admission == "trade" and item.score >= 76:
            item.action = "优先计划"
            item.t_ratio = max(item.t_ratio, 0.20)
        elif admission in {"trade", "watch"} and item.score >= 58:
            item.action = "候选观察"
            item.t_ratio = min(max(item.t_ratio, 0.10), 0.20)
        else:
            item.action = "暂缓"
            item.t_ratio = 0.0
        item.plan["t_ratio"] = item.t_ratio
        rescored.append(item)
    rescored.sort(key=lambda item: (item.score, item.avg_amount_20d), reverse=True)
    return rescored


def write_results(run_id: str, candidates: list[Candidate], backtests: list[dict[str, object]], model_summary: dict[str, object] | None = None) -> None:
    generated_at = now()
    latest_date = candidates[0].trade_date if candidates else ""
    setup_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for item in candidates:
        setup_counts[item.setup] = setup_counts.get(item.setup, 0) + 1
        action_counts[item.first_action] = action_counts.get(item.first_action, 0) + 1
    summary = {
        "candidate_count": len(candidates),
        "backtest_count": len(backtests),
        "priority_count": sum(1 for item in candidates if item.action == "优先计划"),
        "avg_score": safe_float(pd.Series([item.score for item in candidates]).mean()) if candidates else 0.0,
        "setup_counts": setup_counts,
        "first_action_counts": action_counts,
        "model": model_summary or {},
        "generated_at": generated_at,
    }
    with write_transaction() as conn:
        conn.execute(
            replace_sql("t0_daily_runs", ["run_id", "trade_date", "status", "candidate_count", "backtest_count", "summary_json", "created_at", "updated_at"], ["run_id"]),
            (run_id, latest_date, "success", len(candidates), len(backtests), json.dumps(summary, ensure_ascii=False), generated_at, generated_at),
        )
        if candidates:
            conn.executemany(
                replace_sql(
                    "t0_daily_candidates",
                    [
                        "run_id", "ts_code", "name", "industry", "trade_date", "action", "score", "state",
                        "setup", "first_action", "price", "reduce_price", "buy_price", "stop_price", "t_ratio",
                        "today_pct", "return_5d", "return_20d", "avg_range_20d", "drawdown_20d",
                        "amount", "avg_amount_20d", "expected_edge", "target_freq", "lookback_days",
                        "plan_json", "reasons_json", "risks_json", "generated_at",
                    ],
                    ["run_id", "ts_code"],
                ),
                [
                    (
                        item.run_id, item.ts_code, item.name, item.industry, item.trade_date, item.action, item.score, item.state,
                        item.setup, item.first_action, item.price, item.reduce_price, item.buy_price, item.stop_price, item.t_ratio,
                        item.today_pct, item.return_5d, item.return_20d, item.avg_range_20d, item.drawdown_20d,
                        item.amount, item.avg_amount_20d, item.expected_edge, item.target_freq, item.lookback_days,
                        json.dumps(item.plan, ensure_ascii=False), json.dumps(item.reasons, ensure_ascii=False), json.dumps(item.risks, ensure_ascii=False), generated_at,
                    )
                    for item in candidates
                ],
            )
        if backtests:
            conn.executemany(
                replace_sql(
                    "t0_daily_backtests",
                    [
                        "run_id", "ts_code", "name", "industry", "n_days", "n_candidates", "two_sided_rate",
                        "one_sided_rate", "avg_edge", "total_edge", "avg_next_range", "score", "summary_json", "updated_at",
                    ],
                    ["run_id", "ts_code"],
                ),
                [
                    (
                        row["run_id"], row["ts_code"], row["name"], row["industry"], row["n_days"], row["n_candidates"],
                        row["two_sided_rate"], row["one_sided_rate"], row["avg_edge"], row["total_edge"],
                        row["avg_next_range"], row["score"], row["summary_json"], row["updated_at"],
                    )
                    for row in backtests
                ],
            )


def resolve_time_machine_dates(as_of_date: str, lookback: int, eval_days: int) -> tuple[str, str, str, str]:
    dates = trade_dates()
    if not dates:
        raise RuntimeError("data_daily_bars 为空")
    if as_of_date:
        eligible = [date for date in dates if date <= as_of_date]
        if not eligible:
            raise RuntimeError(f"找不到 as_of_date={as_of_date} 之前的交易日")
        as_of = eligible[-1]
    else:
        idx = max(lookback, len(dates) - eval_days - 1)
        idx = min(idx, len(dates) - eval_days - 1)
        if idx < lookback:
            raise RuntimeError("交易日数量不足，无法执行时光机")
        as_of = dates[idx]
    as_idx = dates.index(as_of)
    eval_dates = dates[as_idx + 1: as_idx + 1 + eval_days]
    if not eval_dates:
        raise RuntimeError("as_of_date 后没有可评估交易日")
    start_idx = max(0, as_idx - lookback + 1)
    return dates[start_idx], as_of, eval_dates[0], eval_dates[-1]


def history_start_for_date(as_of_date: str, days: int) -> str:
    dates = trade_dates()
    if not dates:
        raise RuntimeError("data_daily_bars 为空")
    eligible = [date for date in dates if date <= as_of_date]
    if not eligible:
        raise RuntimeError(f"找不到 as_of_date={as_of_date} 之前的交易日")
    idx = max(0, len(eligible) - max(1, int(days)))
    return eligible[idx]


def run_time_machine(
    run_id: str,
    as_of_date: str,
    lookback: int,
    eval_days: int,
    limit: int,
    candidate_pool: int = 0,
    model_history_days: int = 1600,
    model_cache: dict[str, dict[str, object]] | None = None,
    data_path: str = ".",
) -> dict[str, object]:
    start_date, as_of, eval_start, eval_end = resolve_time_machine_dates(as_of_date, lookback, eval_days)
    df = add_metrics(read_daily_between(start_date, eval_end), lookback)
    as_of_rows = df[df["trade_date"] == as_of].copy()
    candidates = [score_row(row, run_id) for _, row in as_of_rows.iterrows()]
    candidates = [item for item in candidates if item.score >= 52]
    candidates.sort(key=lambda item: (item.score, item.avg_amount_20d), reverse=True)
    candidates = candidates[:candidate_pool_limit(limit, candidate_pool)]
    cache_key = f"{as_of}|{lookback}|{model_history_days}"
    if model_cache is not None and cache_key in model_cache:
        model_summary = model_cache[cache_key]
    else:
        model_start = history_start_for_date(as_of, model_history_days)
        model_history = read_daily_between(model_start, as_of)
        model_summary = train_t0_admission_model(model_history, as_of_rows, candidates, run_id, data_path, lookback)
        if model_cache is not None:
            model_cache[cache_key] = model_summary
    candidates = apply_model_scores(candidates, model_summary)
    candidates = [item for item in candidates if item.score >= 52]
    candidates.sort(key=lambda item: (item.score, item.avg_amount_20d), reverse=True)
    candidates = candidates[:limit]
    code_set = {item.ts_code for item in candidates}
    results: list[dict[str, object]] = []
    for item in candidates:
        group = df[df["ts_code"] == item.ts_code].sort_values("trade_date").reset_index(drop=True)
        as_rows = group.index[group["trade_date"] == as_of].tolist()
        if not as_rows:
            continue
        start_pos = as_rows[0]
        eval_rows = []
        closes = []
        for pos in range(start_pos, len(group) - 1):
            row = group.iloc[pos]
            nxt = group.iloc[pos + 1]
            if str(nxt["trade_date"]) > eval_end:
                break
            if str(nxt["trade_date"]) < eval_start:
                continue
            daily_candidate = score_row(row, run_id)
            reduce_price = daily_candidate.reduce_price
            buy_price = daily_candidate.buy_price
            high_hit = safe_float(nxt["high"]) >= reduce_price
            low_hit = safe_float(nxt["low"]) <= buy_price
            stop_hit = safe_float(nxt["low"]) <= daily_candidate.stop_price
            raw_edge = (reduce_price - buy_price) / max(daily_candidate.price, 0.01) - COST_RATE
            eval_rows.append({
                "two_sided": high_hit and low_hit,
                "one_sided": high_hit ^ low_hit,
                "stop_hit": stop_hit,
                "edge": raw_edge if high_hit and low_hit else 0.0,
                "close": safe_float(nxt["close"]),
            })
            closes.append(safe_float(nxt["close"]))
        if not eval_rows:
            continue
        frame = pd.DataFrame(eval_rows)
        t0_edge = safe_float(frame["edge"].sum())
        avg_t0_edge = safe_float(frame["edge"].mean())
        base_close = max(item.price, 0.01)
        underlying_return = safe_float(closes[-1] / base_close - 1) if closes else 0.0
        curve = [safe_float(close / base_close - 1) for close in closes]
        max_drawdown = 0.0
        peak = -1e9
        for value in curve:
            peak = max(peak, value)
            max_drawdown = min(max_drawdown, value - peak)
        combined_return = underlying_return + t0_edge
        results.append({
            "run_id": run_id,
            "ts_code": item.ts_code,
            "name": item.name,
            "industry": item.industry,
            "as_of_date": as_of,
            "eval_start_date": eval_start,
            "eval_end_date": eval_end,
            "score": item.score,
            "n_eval_days": int(len(eval_rows)),
            "two_sided_count": int(frame["two_sided"].sum()),
            "one_sided_count": int(frame["one_sided"].sum()),
            "t0_edge": t0_edge,
            "avg_t0_edge": avg_t0_edge,
            "underlying_return": underlying_return,
            "combined_return": combined_return,
            "max_drawdown": max_drawdown,
            "summary_json": json.dumps({
                "note": "做T时光机：as_of 当日只使用历史数据选股；后续每日用前一日收盘生成交易员模型的高抛/接回/停手线。只有次日 high/low 同时触达才计入做T价差。",
                "cost_rate": COST_RATE,
                "stop_hit_rate": safe_float(frame["stop_hit"].mean()),
                "setup": item.setup,
                "first_action": item.first_action,
                "model_score": item.plan.get("model_score", 0),
            }, ensure_ascii=False),
            "updated_at": now(),
        })
    results.sort(key=lambda row: safe_float(row["combined_return"]), reverse=True)
    generated_at = now()
    evaluated = len(results)
    avg_t0_edge = safe_float(pd.Series([row["t0_edge"] for row in results]).mean()) if results else 0.0
    avg_underlying = safe_float(pd.Series([row["underlying_return"] for row in results]).mean()) if results else 0.0
    avg_combined = safe_float(pd.Series([row["combined_return"] for row in results]).mean()) if results else 0.0
    win_rate = safe_float(pd.Series([row["combined_return"] > 0 for row in results]).mean()) if results else 0.0
    summary = {
        "as_of_date": as_of,
        "eval_start_date": eval_start,
        "eval_end_date": eval_end,
        "candidate_count": len(candidates),
        "evaluated_count": evaluated,
        "avg_t0_edge": avg_t0_edge,
        "avg_underlying_return": avg_underlying,
        "avg_combined_return": avg_combined,
        "win_rate": win_rate,
        "selected_codes": sorted(code_set)[:20],
        "model": {key: value for key, value in model_summary.items() if key not in {"candidate_scores"}},
    }
    with write_transaction() as conn:
        conn.execute(
            replace_sql(
                "t0_daily_time_machine_runs",
                [
                    "run_id", "as_of_date", "eval_start_date", "eval_end_date", "status", "candidate_count",
                    "evaluated_count", "avg_t0_edge", "avg_underlying_return", "avg_combined_return",
                    "win_rate", "summary_json", "created_at", "updated_at",
                ],
                ["run_id"],
            ),
            (
                run_id, as_of, eval_start, eval_end, "success", len(candidates), evaluated, avg_t0_edge,
                avg_underlying, avg_combined, win_rate, json.dumps(summary, ensure_ascii=False), generated_at, generated_at,
            ),
        )
        if results:
            conn.executemany(
                replace_sql(
                    "t0_daily_time_machine_results",
                    [
                        "run_id", "ts_code", "name", "industry", "as_of_date", "eval_start_date", "eval_end_date",
                        "score", "n_eval_days", "two_sided_count", "one_sided_count", "t0_edge", "avg_t0_edge",
                        "underlying_return", "combined_return", "max_drawdown", "summary_json", "updated_at",
                    ],
                    ["run_id", "ts_code"],
                ),
                [
                    (
                        row["run_id"], row["ts_code"], row["name"], row["industry"], row["as_of_date"],
                        row["eval_start_date"], row["eval_end_date"], row["score"], row["n_eval_days"],
                        row["two_sided_count"], row["one_sided_count"], row["t0_edge"], row["avg_t0_edge"],
                        row["underlying_return"], row["combined_return"], row["max_drawdown"],
                        row["summary_json"], row["updated_at"],
                    )
                    for row in results
                ],
            )
    return {"run_id": run_id, **summary}


def parse_int_grid(value: str, fallback: list[int]) -> list[int]:
    if not value.strip():
        return fallback
    out: list[int] = []
    for part in value.split(","):
        try:
            item = int(part.strip())
        except ValueError:
            continue
        if item > 0 and item not in out:
            out.append(item)
    return out or fallback


def window_stability_score(item: dict[str, object]) -> float:
    avg_combined = safe_float(item.get("avg_combined_return"))
    avg_t0_edge = safe_float(item.get("avg_t0_edge"))
    win_rate = safe_float(item.get("win_rate"))
    evaluated = safe_float(item.get("evaluated_count"))
    return avg_combined * 100 + avg_t0_edge * 45 + win_rate * 8 + min(evaluated / 80, 1) * 2


def resolve_anchor_dates(as_of_date: str, eval_days: int, count: int, step: int, min_lookback: int) -> list[str]:
    if as_of_date.strip():
        return [resolve_time_machine_dates(as_of_date, min_lookback, eval_days)[1]]
    dates = trade_dates()
    anchors: list[str] = []
    latest_idx = len(dates) - eval_days - 1
    for offset in range(max(1, count)):
        idx = latest_idx - offset * max(1, step)
        if idx < min_lookback:
            break
        anchors.append(dates[idx])
    return anchors or [resolve_time_machine_dates("", min_lookback, eval_days)[1]]


def aggregate_window_results(rows: list[dict[str, object]], lookback: int, eval_days: int) -> dict[str, object]:
    combined = [safe_float(row.get("avg_combined_return")) for row in rows]
    t0_edges = [safe_float(row.get("avg_t0_edge")) for row in rows]
    win_rates = [safe_float(row.get("win_rate")) for row in rows]
    evaluated = [safe_float(row.get("evaluated_count")) for row in rows]
    mean_combined = sum(combined) / len(combined) if combined else 0.0
    min_combined = min(combined) if combined else 0.0
    positive_rate = len([value for value in combined if value > 0]) / len(combined) if combined else 0.0
    mean_t0 = sum(t0_edges) / len(t0_edges) if t0_edges else 0.0
    mean_win_rate = sum(win_rates) / len(win_rates) if win_rates else 0.0
    stability_score = mean_combined * 100 + min_combined * 60 + positive_rate * 12 + mean_t0 * 35 + mean_win_rate * 6 + min(sum(evaluated) / max(len(evaluated), 1) / 80, 1) * 2
    return {
        "lookback": lookback,
        "eval_days": eval_days,
        "anchor_count": len(rows),
        "anchors": [row.get("as_of_date", "") for row in rows],
        "mean_avg_combined_return": mean_combined,
        "worst_avg_combined_return": min_combined,
        "positive_anchor_rate": positive_rate,
        "mean_avg_t0_edge": mean_t0,
        "mean_win_rate": mean_win_rate,
        "stability_score": stability_score,
        "runs": rows,
    }


def run_time_machine_grid(
    run_id: str,
    as_of_date: str,
    lookbacks: list[int],
    eval_days_list: list[int],
    limit: int,
    candidate_pool: int,
    anchor_count: int,
    anchor_step: int,
    model_history_days: int = 1600,
    data_path: str = ".",
) -> dict[str, object]:
    windows: list[dict[str, object]] = []
    best: dict[str, object] | None = None
    model_cache: dict[str, dict[str, object]] = {}
    min_lookback = max(lookbacks) if lookbacks else 80
    total = max(1, len(lookbacks) * len(eval_days_list) * max(1, anchor_count))
    step = 0
    for lookback in lookbacks:
        for eval_days in eval_days_list:
            anchor_dates = resolve_anchor_dates(as_of_date, eval_days, anchor_count, anchor_step, min_lookback)
            anchor_results: list[dict[str, object]] = []
            for anchor in anchor_dates:
                step += 1
                run_status.progress(TIMEMACHINE_TASK_NAME, step, total + 1, "grid", f"压测窗口 lookback={lookback}, eval={eval_days}, as_of={anchor}")
                window_run_id = f"{run_id}_lb{lookback}_ev{eval_days}_{anchor}"
                result = run_time_machine(window_run_id, anchor, lookback, eval_days, limit, candidate_pool, model_history_days, model_cache, data_path)
                anchor_results.append({
                    "run_id": result["run_id"],
                    "as_of_date": result.get("as_of_date", ""),
                    "eval_start_date": result.get("eval_start_date", ""),
                    "eval_end_date": result.get("eval_end_date", ""),
                    "candidate_count": result.get("candidate_count", 0),
                    "evaluated_count": result.get("evaluated_count", 0),
                    "avg_t0_edge": result.get("avg_t0_edge", 0),
                    "avg_underlying_return": result.get("avg_underlying_return", 0),
                    "avg_combined_return": result.get("avg_combined_return", 0),
                    "win_rate": result.get("win_rate", 0),
                })
            item = aggregate_window_results(anchor_results, lookback, eval_days)
            windows.append(item)
            if best is None or safe_float(item["stability_score"]) > safe_float(best["stability_score"]):
                best = item
    if best is None:
        raise RuntimeError("做T时光机网格没有可用窗口")
    run_status.progress(TIMEMACHINE_TASK_NAME, total, total + 1, "best", "写入最佳稳定窗口")
    final_as_of = as_of_date or str((best.get("anchors") or [""])[0])
    final = run_time_machine(run_id, final_as_of, int(best["lookback"]), int(best["eval_days"]), limit, candidate_pool, model_history_days, model_cache, data_path)
    avg_returns = [safe_float(row.get("mean_avg_combined_return")) for row in windows]
    worst_returns = [safe_float(row.get("worst_avg_combined_return")) for row in windows]
    positive = [row for row in windows if safe_float(row.get("positive_anchor_rate")) >= 0.67]
    grid_summary = {
        "mode": "grid",
        "lookbacks": lookbacks,
        "eval_days": eval_days_list,
        "anchor_count": anchor_count,
        "anchor_step": anchor_step,
        "window_count": len(windows),
        "best": best,
        "windows": sorted(windows, key=lambda row: safe_float(row["stability_score"]), reverse=True),
        "positive_window_rate": len(positive) / len(windows) if windows else 0,
        "worst_avg_combined_return": min(worst_returns) if worst_returns else 0,
        "mean_avg_combined_return": sum(avg_returns) / len(avg_returns) if avg_returns else 0,
    }
    with write_transaction() as conn:
        summary_text = json.dumps({**final, "grid": grid_summary}, ensure_ascii=False)
        conn.execute(
            "UPDATE t0_daily_time_machine_runs SET summary_json = ? WHERE run_id = ?",
            (summary_text, run_id),
        )
        conn.execute(
            "UPDATE t0_daily_time_machine_results SET summary_json = ? WHERE run_id = ?",
            (summary_text, run_id),
        )
    return {"run_id": run_id, **final, "grid": grid_summary}


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily-bar T0 suitability research worker")
    parser.add_argument("--data-path", default="")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--mode", choices=["research", "time_machine"], default="research")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--eval-days", type=int, default=20)
    parser.add_argument("--lookback-grid", default="")
    parser.add_argument("--eval-days-grid", default="")
    parser.add_argument("--anchor-count", type=int, default=1)
    parser.add_argument("--anchor-step", type=int, default=20)
    parser.add_argument("--lookback", type=int, default=80)
    parser.add_argument("--history-days", type=int, default=520)
    parser.add_argument("--model-history-days", type=int, default=2200)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--candidate-pool-limit", type=int, default=0)
    parser.add_argument("--backtest-limit", type=int, default=80)
    args = parser.parse_args()

    run_id_prefix = "t0_tm" if args.mode == "time_machine" else "t0_daily"
    run_id = args.run_id.strip() or run_id_prefix + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    task_name = TIMEMACHINE_TASK_NAME if args.mode == "time_machine" else TASK_NAME
    run_status.begin(task_name)
    try:
        run_status.progress(task_name, 1, 6, "schema", "准备日线做T结果表")
        ensure_schema()
        if args.mode == "time_machine":
            lookbacks = parse_int_grid(args.lookback_grid, [args.lookback])
            eval_days_list = parse_int_grid(args.eval_days_grid, [args.eval_days])
            run_status.progress(task_name, 2, 5, "timemachine", "选择历史截面并评估后续收益")
            if len(lookbacks) > 1 or len(eval_days_list) > 1:
                result = run_time_machine_grid(run_id, args.as_of_date.strip(), lookbacks, eval_days_list, args.limit, args.candidate_pool_limit, args.anchor_count, args.anchor_step, args.model_history_days, args.data_path or ".")
            else:
                result = run_time_machine(run_id, args.as_of_date.strip(), args.lookback, args.eval_days, args.limit, args.candidate_pool_limit, args.model_history_days, None, args.data_path or ".")
            run_status.progress(task_name, 5, 5, "write", "写入做T时光机结果")
            run_status.done(task_name, f"完成做T时光机：候选 {result['candidate_count']}，评估 {result['evaluated_count']}")
            print(json.dumps(result, ensure_ascii=False))
            return
        run_status.progress(task_name, 2, 6, "daily", "读取最近日线并粗筛")
        recent = read_recent_daily(args.lookback)
        pool_limit = candidate_pool_limit(args.limit, args.candidate_pool_limit)
        candidates = build_candidates(recent, run_id, pool_limit, args.lookback)
        latest_metrics = add_metrics(recent, args.lookback)
        latest_metrics = latest_metrics[latest_metrics["trade_date"] == str(latest_metrics["trade_date"].max())].copy()
        run_status.progress(task_name, 3, 6, "train", "全市场历史训练做T准入模型")
        model_history = read_history_all(max(args.model_history_days, args.history_days))
        model_summary = train_t0_admission_model(model_history, latest_metrics, candidates, run_id, args.data_path or ".", args.lookback)
        candidates = apply_model_scores(candidates, model_summary)
        run_status.progress(task_name, 4, 6, "backtest", "读取候选历史日线")
        codes = [item.ts_code for item in candidates[: args.backtest_limit]]
        history = read_history_for_codes(codes, args.history_days)
        run_status.progress(task_name, 5, 6, "backtest", "执行日线近似回测")
        backtests = backtest_candidates(history, run_id, args.lookback)
        candidates = apply_effective_scores(candidates, backtests)
        candidates = candidates[: args.limit]
        run_status.progress(task_name, 6, 6, "write", "写入做T模型与推荐结果")
        write_results(run_id, candidates, backtests, model_summary)
        run_status.done(task_name, f"完成日线做T研究：候选 {len(candidates)}，回测 {len(backtests)}")
        print(json.dumps({"run_id": run_id, "candidates": len(candidates), "backtests": len(backtests), "model": model_summary}, ensure_ascii=False))
    except Exception as exc:
        run_status.error(task_name, str(exc))
        raise


if __name__ == "__main__":
    main()
