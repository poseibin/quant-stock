from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable.*")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import open_db, replace_sql, table_exists, upsert_sql, write_transaction


TASK_NAME = "t0_daily_research"
TIMEMACHINE_TASK_NAME = "t0_daily_timemachine"
COST_RATE = 0.004


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
    price: float
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
                price REAL NOT NULL DEFAULT 0,
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


def add_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["open", "high", "low", "close", "pre_close", "pct_chg", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.sort_values(["ts_code", "trade_date"])
    group = df.groupby("ts_code", group_keys=False)
    prev_close_5 = group["close"].shift(4)
    prev_close_20 = group["close"].shift(19)
    rolling_high_20 = group["high"].rolling(20, min_periods=10).max().reset_index(level=0, drop=True)
    df["return_5d"] = df["close"] / prev_close_5.replace(0, pd.NA) - 1
    df["return_20d"] = df["close"] / prev_close_20.replace(0, pd.NA) - 1
    df["range"] = (df["high"] - df["low"]) / df["close"].replace(0, pd.NA)
    df["avg_range_20d"] = group["range"].rolling(20, min_periods=10).mean().reset_index(level=0, drop=True)
    df["avg_amount_20d"] = group["amount"].rolling(20, min_periods=10).mean().reset_index(level=0, drop=True)
    df["ma5"] = group["close"].rolling(5, min_periods=3).mean().reset_index(level=0, drop=True)
    df["ma20"] = group["close"].rolling(20, min_periods=10).mean().reset_index(level=0, drop=True)
    df["drawdown_20d"] = df["close"] / rolling_high_20.replace(0, pd.NA) - 1
    return df.replace([math.inf, -math.inf], pd.NA).fillna(0.0)


def score_row(row: pd.Series, run_id: str) -> Candidate:
    avg_range = safe_float(row.get("avg_range_20d"))
    avg_amount = safe_float(row.get("avg_amount_20d"))
    today_pct = safe_float(row.get("pct_chg")) / 100
    return_20 = safe_float(row.get("return_20d"))
    drawdown_20 = safe_float(row.get("drawdown_20d"))
    vol_score = clamp((avg_range - 0.018) / 0.04, 0, 1) * 38
    liquidity_score = clamp((math.log10(max(avg_amount, 1)) - 4.8) / 2.3, 0, 1) * 30
    reversion_score = clamp((abs(today_pct) - 0.004) / 0.035, 0, 1) * 14
    trend_penalty = clamp((abs(return_20) - 0.08) / 0.18, 0, 1) * 16
    score = 22 + vol_score + liquidity_score + reversion_score - trend_penalty
    reasons: list[str] = []
    risks: list[str] = []
    if avg_range >= 0.03:
        reasons.append(f"20日平均振幅 {avg_range * 100:.2f}%，日线足够做T计划")
    else:
        risks.append(f"20日平均振幅 {avg_range * 100:.2f}%，日内空间一般")
    if avg_amount > 0:
        reasons.append(f"20日平均成交额 {avg_amount:.0f}，流动性满足粗筛")
    state = "普通震荡"
    close = safe_float(row.get("close"))
    ma5 = safe_float(row.get("ma5"))
    ma20 = safe_float(row.get("ma20"))
    if close > ma5 > ma20 and return_20 > 0.08:
        state = "趋势偏强"
        risks.append("强趋势票做T容易卖飞")
    elif close < ma5 < ma20 and return_20 < -0.08:
        state = "趋势偏弱"
        risks.append("弱趋势票低吸风险较高")
    elif avg_range >= 0.045:
        state = "高波震荡"
        reasons.append("高波震荡优先纳入日线做T计划")
    if drawdown_20 < -0.18:
        risks.append(f"距20日高点回撤 {drawdown_20 * 100:.2f}%，先按观察候选处理")
        score -= 6
    band = clamp(avg_range * 0.55, 0.008, 0.04)
    expected_edge = band * 2 - COST_RATE
    if expected_edge <= 0.01:
        risks.append("扣成本后价差偏薄，优先级下调")
        score -= 8
    score = round(clamp(score, 0, 100), 1)
    action = "优先计划" if score >= 72 else "候选观察" if score >= 58 else "暂缓"
    return Candidate(
        run_id=run_id,
        ts_code=str(row.get("ts_code") or ""),
        name=str(row.get("name") or ""),
        industry=str(row.get("industry") or ""),
        trade_date=str(row.get("trade_date") or ""),
        action=action,
        score=score,
        state=state,
        price=close,
        today_pct=today_pct,
        return_5d=safe_float(row.get("return_5d")),
        return_20d=return_20,
        avg_range_20d=avg_range,
        drawdown_20d=drawdown_20,
        amount=safe_float(row.get("amount")),
        avg_amount_20d=avg_amount,
        expected_edge=expected_edge,
        target_freq="daily",
        lookback_days=0,
        reasons=reasons,
        risks=risks,
    )


def build_candidates(df: pd.DataFrame, run_id: str, limit: int) -> list[Candidate]:
    latest_date = str(df["trade_date"].max())
    latest = add_metrics(df)
    latest = latest[latest["trade_date"] == latest_date].copy()
    candidates = [score_row(row, run_id) for _, row in latest.iterrows()]
    candidates = [item for item in candidates if item.score >= 52]
    candidates.sort(key=lambda item: (item.score, item.avg_amount_20d), reverse=True)
    return candidates[:limit]


def backtest_candidates(history: pd.DataFrame, run_id: str) -> list[dict[str, object]]:
    if history.empty:
        return []
    df = add_metrics(history)
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
            band = clamp(candidate.avg_range_20d * 0.55, 0.008, 0.04)
            reduce_price = candidate.price * (1 + band)
            buy_price = candidate.price * (1 - band)
            high_hit = safe_float(nxt["high"]) >= reduce_price
            low_hit = safe_float(nxt["low"]) <= buy_price
            two_sided = high_hit and low_hit
            one_sided = high_hit ^ low_hit
            raw_edge = (reduce_price - buy_price) / max(candidate.price, 0.01) - COST_RATE
            rows.append({
                "two_sided": two_sided,
                "one_sided": one_sided,
                "edge": raw_edge if two_sided else 0.0,
                "next_range": (safe_float(nxt["high"]) - safe_float(nxt["low"])) / max(safe_float(nxt["close"]), 0.01),
                "score": candidate.score,
            })
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        latest = group.iloc[-1]
        n = len(frame)
        two_sided_rate = safe_float(frame["two_sided"].mean())
        one_sided_rate = safe_float(frame["one_sided"].mean())
        avg_edge = safe_float(frame["edge"].mean())
        total_edge = safe_float(frame["edge"].sum())
        avg_next_range = safe_float(frame["next_range"].mean())
        score = round(clamp(two_sided_rate * 55 + avg_edge * 900 + avg_next_range * 120 - one_sided_rate * 10, 0, 100), 2)
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
            }, ensure_ascii=False),
            "updated_at": now(),
        })
    out.sort(key=lambda row: safe_float(row["score"]), reverse=True)
    return out


def write_results(run_id: str, candidates: list[Candidate], backtests: list[dict[str, object]]) -> None:
    generated_at = now()
    latest_date = candidates[0].trade_date if candidates else ""
    summary = {
        "candidate_count": len(candidates),
        "backtest_count": len(backtests),
        "priority_count": sum(1 for item in candidates if item.action == "优先计划"),
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
                        "price", "today_pct", "return_5d", "return_20d", "avg_range_20d", "drawdown_20d",
                        "amount", "avg_amount_20d", "expected_edge", "target_freq", "lookback_days",
                        "reasons_json", "risks_json", "generated_at",
                    ],
                    ["run_id", "ts_code"],
                ),
                [
                    (
                        item.run_id, item.ts_code, item.name, item.industry, item.trade_date, item.action, item.score, item.state,
                        item.price, item.today_pct, item.return_5d, item.return_20d, item.avg_range_20d, item.drawdown_20d,
                        item.amount, item.avg_amount_20d, item.expected_edge, item.target_freq, item.lookback_days,
                        json.dumps(item.reasons, ensure_ascii=False), json.dumps(item.risks, ensure_ascii=False), generated_at,
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


def run_time_machine(run_id: str, as_of_date: str, lookback: int, eval_days: int, limit: int) -> dict[str, object]:
    start_date, as_of, eval_start, eval_end = resolve_time_machine_dates(as_of_date, lookback, eval_days)
    df = add_metrics(read_daily_between(start_date, eval_end))
    as_of_rows = df[df["trade_date"] == as_of].copy()
    candidates = [score_row(row, run_id) for _, row in as_of_rows.iterrows()]
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
            band = clamp(daily_candidate.avg_range_20d * 0.55, 0.008, 0.04)
            reduce_price = daily_candidate.price * (1 + band)
            buy_price = daily_candidate.price * (1 - band)
            high_hit = safe_float(nxt["high"]) >= reduce_price
            low_hit = safe_float(nxt["low"]) <= buy_price
            raw_edge = (reduce_price - buy_price) / max(daily_candidate.price, 0.01) - COST_RATE
            eval_rows.append({
                "two_sided": high_hit and low_hit,
                "one_sided": high_hit ^ low_hit,
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
                "note": "做T时光机：as_of 当日只使用历史数据选股；后续每日用前一日收盘生成高抛/低吸区间。只有次日 high/low 同时触达才计入做T价差。",
                "cost_rate": COST_RATE,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily-bar T0 suitability research worker")
    parser.add_argument("--data-path", default="")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--mode", choices=["research", "time_machine"], default="research")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--eval-days", type=int, default=20)
    parser.add_argument("--lookback", type=int, default=80)
    parser.add_argument("--history-days", type=int, default=520)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--backtest-limit", type=int, default=80)
    args = parser.parse_args()

    run_id_prefix = "t0_tm" if args.mode == "time_machine" else "t0_daily"
    run_id = args.run_id.strip() or run_id_prefix + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    task_name = TIMEMACHINE_TASK_NAME if args.mode == "time_machine" else TASK_NAME
    run_status.begin(task_name)
    try:
        run_status.progress(task_name, 1, 5, "schema", "准备日线做T结果表")
        ensure_schema()
        if args.mode == "time_machine":
            run_status.progress(task_name, 2, 5, "timemachine", "选择历史截面并评估后续收益")
            result = run_time_machine(run_id, args.as_of_date.strip(), args.lookback, args.eval_days, args.limit)
            run_status.progress(task_name, 5, 5, "write", "写入做T时光机结果")
            run_status.done(task_name, f"完成做T时光机：候选 {result['candidate_count']}，评估 {result['evaluated_count']}")
            print(json.dumps(result, ensure_ascii=False))
            return
        run_status.progress(task_name, 2, 5, "daily", "读取最近日线并粗筛")
        recent = read_recent_daily(args.lookback)
        candidates = build_candidates(recent, run_id, args.limit)
        run_status.progress(task_name, 3, 5, "backtest", "读取候选历史日线")
        codes = [item.ts_code for item in candidates[: args.backtest_limit]]
        history = read_history_for_codes(codes, args.history_days)
        run_status.progress(task_name, 4, 5, "backtest", "执行日线近似回测")
        backtests = backtest_candidates(history, run_id)
        run_status.progress(task_name, 5, 5, "write", "写入日线做T研究结果")
        write_results(run_id, candidates, backtests)
        run_status.done(task_name, f"完成日线做T研究：候选 {len(candidates)}，回测 {len(backtests)}")
        print(json.dumps({"run_id": run_id, "candidates": len(candidates), "backtests": len(backtests)}, ensure_ascii=False))
    except Exception as exc:
        run_status.error(task_name, str(exc))
        raise


if __name__ == "__main__":
    main()
