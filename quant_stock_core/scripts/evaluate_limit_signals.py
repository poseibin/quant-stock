from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import connect_db, upsert_sql, write_transaction


TASK_NAME = "limit_signal_evaluation"


@dataclass
class Prediction:
    id: str
    signal_type: str
    strategy_version: str
    parameter_key: str
    ts_code: str
    name: str
    signal_date: str
    signal_price: float
    score: float


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
    code = ts_code or ""
    if code.startswith("688") or code.startswith("300"):
        return 19.0
    if code.startswith("8") or code.startswith("4") or ".BJ" in code:
        return 28.0
    return 9.2


def ensure_tables(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_limit_signal_predictions (
            id TEXT PRIMARY KEY,
            signal_type TEXT NOT NULL,
            strategy_version TEXT NOT NULL DEFAULT 'v1',
            parameter_key TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            ts_code TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            signal_date TEXT NOT NULL,
            signal_price REAL NOT NULL DEFAULT 0,
            score REAL NOT NULL DEFAULT 0,
            recommendation TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            ret_1d REAL,
            ret_3d REAL,
            ret_5d REAL,
            ret_10d REAL,
            max_drawdown_5d REAL,
            hit_limit_up_5d INTEGER,
            target_hit INTEGER,
            outcome_json TEXT NOT NULL DEFAULT '{}',
            evaluated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(signal_type, parameter_key, ts_code, signal_date)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_limit_signal_eval_summary (
            signal_type TEXT NOT NULL,
            strategy_version TEXT NOT NULL DEFAULT 'v1',
            parameter_key TEXT NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 0,
            pending_count INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL NOT NULL DEFAULT 0,
            avg_return_1d REAL NOT NULL DEFAULT 0,
            avg_return_3d REAL NOT NULL DEFAULT 0,
            avg_return_5d REAL NOT NULL DEFAULT 0,
            avg_return_10d REAL NOT NULL DEFAULT 0,
            avg_max_drawdown_5d REAL NOT NULL DEFAULT 0,
            avg_score REAL NOT NULL DEFAULT 0,
            recommendation TEXT NOT NULL DEFAULT '',
            parameter_hint TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(signal_type, strategy_version, parameter_key)
        )"""
    )


def load_predictions(db_path: Path, limit: int) -> list[Prediction]:
    with connect_db(db_path) as conn:
        ensure_tables(conn)
        rows = conn.execute(
            """SELECT id, signal_type, strategy_version, parameter_key, ts_code, name,
                      signal_date, signal_price, score
               FROM market_limit_signal_predictions
               ORDER BY signal_date DESC, rank ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        Prediction(
            id=str(row[0]),
            signal_type=str(row[1]),
            strategy_version=str(row[2]),
            parameter_key=str(row[3]),
            ts_code=str(row[4]),
            name=str(row[5]),
            signal_date=str(row[6]),
            signal_price=safe_float(row[7]),
            score=safe_float(row[8]),
        )
        for row in rows
    ]


def load_daily(data_path: Path, predictions: list[Prediction]) -> pd.DataFrame:
    if not predictions:
        return pd.DataFrame()
    raw_daily = data_path / "raw" / "daily" / "*.parquet"
    codes = sorted({p.ts_code for p in predictions if p.ts_code})
    min_date = min(p.signal_date for p in predictions if p.signal_date)
    escaped = ",".join("'" + code.replace("'", "''") + "'" for code in codes)
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            SELECT ts_code, trade_date, high, low, close, pct_chg
            FROM read_parquet('{raw_daily}')
            WHERE ts_code IN ({escaped}) AND trade_date >= '{min_date}'
            ORDER BY ts_code, trade_date
            """
        ).fetch_df()
    finally:
        con.close()


def evaluate_one(pred: Prediction, bars: pd.DataFrame) -> dict[str, object] | None:
    future = bars[bars["trade_date"] > pred.signal_date].sort_values("trade_date")
    if len(future) < 1:
        return None
    entry = pred.signal_price
    if entry <= 0:
        same_or_prev = bars[bars["trade_date"] <= pred.signal_date].sort_values("trade_date")
        if not same_or_prev.empty:
            entry = safe_float(same_or_prev.iloc[-1].get("close"))
    if entry <= 0:
        return None

    def ret_at(horizon: int) -> float | None:
        if len(future) < horizon:
            return None
        close = safe_float(future.iloc[horizon - 1].get("close"))
        return close / entry - 1 if close > 0 else None

    first5 = future.head(5)
    lows = first5["low"].map(safe_float)
    max_drawdown_5d = (safe_float(lows.min()) / entry - 1) if not lows.empty else None
    threshold = limit_threshold(pred.ts_code, pred.name)
    hit_limit_up_5d = int((first5["pct_chg"].map(safe_float) >= threshold).any()) if not first5.empty else 0
    ret_1d = ret_at(1)
    ret_3d = ret_at(3)
    ret_5d = ret_at(5)
    ret_10d = ret_at(10)
    target = ret_5d if pred.signal_type == "limit_up_momentum" else ret_10d
    drawdown_ok = max_drawdown_5d is None or max_drawdown_5d > -0.12
    target_hit = int(target is not None and target >= 0.03 and drawdown_ok)
    outcome = {
        "entry": entry,
        "target_horizon": 5 if pred.signal_type == "limit_up_momentum" else 10,
        "limit_up_threshold_pct": threshold,
        "target_rule": "target return >= 3% and 5d drawdown > -12%",
    }
    return {
        "ret_1d": ret_1d,
        "ret_3d": ret_3d,
        "ret_5d": ret_5d,
        "ret_10d": ret_10d,
        "max_drawdown_5d": max_drawdown_5d,
        "hit_limit_up_5d": hit_limit_up_5d,
        "target_hit": target_hit,
        "outcome_json": json.dumps(outcome, ensure_ascii=False, separators=(",", ":")),
    }


def recommendation_for(signal_type: str, sample_count: int, hit_rate: float, avg_return: float, avg_drawdown: float) -> tuple[str, str]:
    if sample_count < 20:
        return "collecting", "样本不足，继续累积预测快照后再调参"
    if hit_rate >= 0.55 and avg_return > 0 and avg_drawdown > -0.08:
        return "keep", "命中率与收益质量可接受，优先扩大样本做样本外确认"
    if hit_rate >= 0.45 and avg_return > -0.01:
        return "tune", "边际有效，建议围绕分数阈值、涨幅阈值和量能阈值做网格实验"
    if signal_type == "limit_up_momentum":
        return "tighten", "短线承接不足，建议提高资金确认权重并降低末端涨幅容忍度"
    return "tighten", "突破延续不足，建议提高箱体质量和突破量能阈值"


def write_results(db_path: Path, predictions: list[Prediction], results: dict[str, dict[str, object]]) -> tuple[int, int]:
    ts = now_text()
    evaluated = 0
    with write_transaction(db_path) as conn:
        ensure_tables(conn)
        for pred in predictions:
            result = results.get(pred.id)
            if result is None:
                continue
            evaluated += 1
            conn.execute(
                """UPDATE market_limit_signal_predictions
                   SET ret_1d=?, ret_3d=?, ret_5d=?, ret_10d=?, max_drawdown_5d=?,
                       hit_limit_up_5d=?, target_hit=?, outcome_json=?, evaluated_at=?, updated_at=?
                   WHERE id=?""",
                (
                    result["ret_1d"],
                    result["ret_3d"],
                    result["ret_5d"],
                    result["ret_10d"],
                    result["max_drawdown_5d"],
                    result["hit_limit_up_5d"],
                    result["target_hit"],
                    result["outcome_json"],
                    ts,
                    ts,
                    pred.id,
                ),
            )

        rows = conn.execute(
            """SELECT signal_type, strategy_version, parameter_key,
                      COUNT(*) AS total_count,
                      SUM(CASE WHEN evaluated_at IS NULL OR evaluated_at = '' THEN 1 ELSE 0 END) AS pending_count,
                      SUM(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN 1 ELSE 0 END) AS sample_count,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN target_hit END) AS hit_rate,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_1d END) AS avg_return_1d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_3d END) AS avg_return_3d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_5d END) AS avg_return_5d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_10d END) AS avg_return_10d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN max_drawdown_5d END) AS avg_max_drawdown_5d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN score END) AS avg_score
               FROM market_limit_signal_predictions
               GROUP BY signal_type, strategy_version, parameter_key"""
        ).fetchall()
        for row in rows:
            signal_type = str(row[0])
            strategy_version = str(row[1])
            parameter_key = str(row[2])
            pending_count = int(row[4] or 0)
            sample_count = int(row[5] or 0)
            hit_rate = safe_float(row[6])
            avg_return_1d = safe_float(row[7])
            avg_return_3d = safe_float(row[8])
            avg_return_5d = safe_float(row[9])
            avg_return_10d = safe_float(row[10])
            avg_max_drawdown_5d = safe_float(row[11])
            avg_score = safe_float(row[12])
            target_avg = avg_return_5d if signal_type == "limit_up_momentum" else avg_return_10d
            rec, hint = recommendation_for(signal_type, sample_count, hit_rate, target_avg, avg_max_drawdown_5d)
            columns = [
                "signal_type", "strategy_version", "parameter_key", "sample_count", "pending_count",
                "hit_rate", "avg_return_1d", "avg_return_3d", "avg_return_5d", "avg_return_10d",
                "avg_max_drawdown_5d", "avg_score", "recommendation", "parameter_hint", "updated_at",
            ]
            conn.execute(
                upsert_sql(
                    "market_limit_signal_eval_summary",
                    columns,
                    ["signal_type", "strategy_version", "parameter_key"],
                    [
                        "sample_count", "pending_count", "hit_rate", "avg_return_1d",
                        "avg_return_3d", "avg_return_5d", "avg_return_10d",
                        "avg_max_drawdown_5d", "avg_score", "recommendation",
                        "parameter_hint", "updated_at",
                    ],
                ),
                (
                    signal_type,
                    strategy_version,
                    parameter_key,
                    sample_count,
                    pending_count,
                    hit_rate,
                    avg_return_1d,
                    avg_return_3d,
                    avg_return_5d,
                    avg_return_10d,
                    avg_max_drawdown_5d,
                    avg_score,
                    rec,
                    hint,
                    ts,
                ),
            )
    return evaluated, len(predictions) - evaluated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", default=os.getenv("DATA_ROOT", "data_store"))
    parser.add_argument("--db-path", default=os.getenv("DESKTOP_DB_PATH", ""))
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    db_path = Path(args.db_path or (Path(args.data_path) / "meta.db")).expanduser().resolve()
    data_path = Path(args.data_path).expanduser().resolve()
    try:
        run_status.begin(TASK_NAME)
        run_status.progress(TASK_NAME, 1, 100, "load", "读取预测快照")
        predictions = load_predictions(db_path, args.limit)
        if not predictions:
            run_status.done(TASK_NAME, "暂无涨停预测快照，先刷新涨停推荐或横盘突发预警")
            return 0
        run_status.progress(TASK_NAME, 12, 100, "daily", f"读取 {len(predictions)} 条预测的后验行情")
        daily = load_daily(data_path, predictions)
        groups = {code: group.copy() for code, group in daily.groupby("ts_code", sort=False)}
        results: dict[str, dict[str, object]] = {}
        total = len(predictions)
        for idx, pred in enumerate(predictions, start=1):
            bars = groups.get(pred.ts_code, pd.DataFrame())
            result = evaluate_one(pred, bars)
            if result is not None:
                results[pred.id] = result
            if idx == 1 or idx == total or idx % 200 == 0:
                progress = 12 + int(idx / total * 76)
                run_status.progress(TASK_NAME, progress, 100, "evaluate", f"回看预测 {idx}/{total}")
        run_status.progress(TASK_NAME, 92, 100, "persist", "写入回看指标和参数建议")
        evaluated, pending = write_results(db_path, predictions, results)
        run_status.progress(TASK_NAME, 100, 100, "done", "刷新评估摘要")
        run_status.done(TASK_NAME, f"已回看 {evaluated} 条预测，待样本成熟 {pending} 条")
        print(json.dumps({"evaluated": evaluated, "pending": pending}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
