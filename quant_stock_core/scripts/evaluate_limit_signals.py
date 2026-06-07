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
from common.infra.db import add_column, connect_db, table_columns, upsert_sql, write_transaction


TASK_NAME = "limit_signal_evaluation"


@dataclass
class Prediction:
    id: str
    signal_type: str
    strategy_version: str
    parameter_key: str
    ts_code: str
    name: str
    industry: str
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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_limit_signal_tm_slices (
            signal_type TEXT NOT NULL,
            strategy_version TEXT NOT NULL DEFAULT 'v1',
            parameter_key TEXT NOT NULL,
            signal_date TEXT NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            evaluated_count INTEGER NOT NULL DEFAULT 0,
            hit_rate REAL NOT NULL DEFAULT 0,
            limit_up_hit_rate REAL NOT NULL DEFAULT 0,
            avg_return_1d REAL NOT NULL DEFAULT 0,
            avg_return_3d REAL NOT NULL DEFAULT 0,
            avg_return_5d REAL NOT NULL DEFAULT 0,
            avg_return_10d REAL NOT NULL DEFAULT 0,
            avg_target_return REAL NOT NULL DEFAULT 0,
            avg_max_drawdown_5d REAL NOT NULL DEFAULT 0,
            avg_score REAL NOT NULL DEFAULT 0,
            slice_score REAL NOT NULL DEFAULT 0,
            market_heat_score REAL NOT NULL DEFAULT 0,
            limit_up_count INTEGER NOT NULL DEFAULT 0,
            limit_up_ratio REAL NOT NULL DEFAULT 0,
            up_ratio REAL NOT NULL DEFAULT 0,
            hot_tags_json TEXT NOT NULL DEFAULT '[]',
            top_industries_json TEXT NOT NULL DEFAULT '[]',
            recommendation TEXT NOT NULL DEFAULT '',
            summary_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(signal_type, strategy_version, parameter_key, signal_date)
        )"""
    )
    slice_columns = table_columns(conn, "market_limit_signal_tm_slices")
    json_ddl = "TEXT NOT NULL" if conn.backend == "mysql" else "TEXT NOT NULL DEFAULT '[]'"
    additions = {
        "market_heat_score": "REAL NOT NULL DEFAULT 0",
        "limit_up_count": "INTEGER NOT NULL DEFAULT 0",
        "limit_up_ratio": "REAL NOT NULL DEFAULT 0",
        "up_ratio": "REAL NOT NULL DEFAULT 0",
        "hot_tags_json": json_ddl,
        "top_industries_json": json_ddl,
    }
    for name, ddl in additions.items():
        if name not in slice_columns:
            add_column(conn, "market_limit_signal_tm_slices", name, ddl)


def load_predictions(db_path: Path, limit: int) -> list[Prediction]:
    with connect_db(db_path) as conn:
        ensure_tables(conn)
        rows = conn.execute(
            """SELECT id, signal_type, strategy_version, parameter_key, ts_code, name, industry,
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
            industry=str(row[6] or ""),
            signal_date=str(row[7]),
            signal_price=safe_float(row[8]),
            score=safe_float(row[9]),
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


def heat_score(limit_up_count: int, limit_up_ratio: float, up_ratio: float, avg_pct: float) -> float:
    return max(
        0.0,
        min(
            100.0,
            min(1.0, limit_up_count / 120.0) * 35.0
            + min(1.0, limit_up_ratio / 0.05) * 25.0
            + min(1.0, up_ratio / 0.65) * 20.0
            + min(1.0, max(0.0, avg_pct) / 2.5) * 20.0,
        ),
    )


def load_market_context(data_path: Path, dates: list[str]) -> dict[str, dict[str, object]]:
    dates = sorted({str(date) for date in dates if str(date)})
    if not dates:
        return {}
    raw = data_path / "raw"
    escaped = ",".join("'" + date.replace("'", "''") + "'" for date in dates)
    con = duckdb.connect()
    try:
        daily = con.execute(
            f"""
            SELECT d.ts_code, d.trade_date, d.pct_chg,
                   COALESCE(s.name, '') AS name,
                   COALESCE(s.industry, '') AS industry
            FROM read_parquet('{raw / "daily" / "*.parquet"}') d
            LEFT JOIN read_parquet('{raw / "stock_basic" / "data.parquet"}') s
              ON d.ts_code = s.ts_code
            WHERE d.trade_date IN ({escaped})
              AND d.pct_chg IS NOT NULL
            """
        ).fetch_df()
    finally:
        con.close()
    if daily.empty:
        return {}
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily["pct_chg"] = pd.to_numeric(daily["pct_chg"], errors="coerce")
    daily = daily.dropna(subset=["pct_chg"])
    daily["industry"] = daily["industry"].fillna("").astype(str).replace("", "未分类")
    daily["is_up"] = daily["pct_chg"] > 0
    daily["is_limit_up"] = daily.apply(
        lambda row: safe_float(row.get("pct_chg")) >= limit_threshold(str(row.get("ts_code") or ""), str(row.get("name") or "")),
        axis=1,
    )
    contexts: dict[str, dict[str, object]] = {}
    for trade_date, day in daily.groupby("trade_date", sort=False):
        universe_count = int(day["ts_code"].nunique())
        limit_up_count = int(day["is_limit_up"].sum())
        limit_up_ratio = limit_up_count / universe_count if universe_count else 0.0
        up_ratio = float(day["is_up"].mean()) if universe_count else 0.0
        avg_pct = safe_float(day["pct_chg"].mean())
        industries = []
        grouped = day.groupby("industry", sort=False)
        for industry, group in grouped:
            count = int(group["ts_code"].nunique())
            industry_limit_up_count = int(group["is_limit_up"].sum())
            industry_up_ratio = float(group["is_up"].mean()) if count else 0.0
            industry_limit_up_ratio = industry_limit_up_count / count if count else 0.0
            industry_avg_pct = safe_float(group["pct_chg"].mean())
            industries.append(
                {
                    "industry": str(industry or "未分类"),
                    "count": count,
                    "limit_up_count": industry_limit_up_count,
                    "limit_up_ratio": industry_limit_up_ratio,
                    "up_ratio": industry_up_ratio,
                    "avg_pct": industry_avg_pct,
                    "heat_score": heat_score(industry_limit_up_count, industry_limit_up_ratio, industry_up_ratio, industry_avg_pct),
                }
            )
        industries.sort(key=lambda item: (safe_float(item["heat_score"]), int(item["limit_up_count"]), int(item["count"])), reverse=True)
        contexts[str(trade_date)] = {
            "market_heat_score": heat_score(limit_up_count, limit_up_ratio, up_ratio, avg_pct),
            "universe_count": universe_count,
            "limit_up_count": limit_up_count,
            "limit_up_ratio": limit_up_ratio,
            "up_ratio": up_ratio,
            "avg_pct": avg_pct,
            "industries": industries[:20],
        }
    return contexts


def slice_hot_context(predictions: list[Prediction], market: dict[str, object]) -> dict[str, object]:
    candidate_count = len(predictions)
    market_heat = safe_float(market.get("market_heat_score") if market else 0)
    limit_up_count = int(market.get("limit_up_count") or 0) if market else 0
    limit_up_ratio = safe_float(market.get("limit_up_ratio") if market else 0)
    up_ratio = safe_float(market.get("up_ratio") if market else 0)
    market_industries = {
        str(item.get("industry") or "未分类"): item
        for item in (market.get("industries") or [])
        if isinstance(item, dict)
    }
    counts: dict[str, int] = {}
    for pred in predictions:
        industry = pred.industry or "未分类"
        counts[industry] = counts.get(industry, 0) + 1
    top_industries = []
    for industry, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]:
        base = market_industries.get(industry, {})
        top_industries.append(
            {
                "industry": industry,
                "candidate_count": count,
                "candidate_weight": count / candidate_count if candidate_count else 0.0,
                "market_limit_up_count": int(base.get("limit_up_count") or 0),
                "market_limit_up_ratio": safe_float(base.get("limit_up_ratio")),
                "market_up_ratio": safe_float(base.get("up_ratio")),
                "market_avg_pct": safe_float(base.get("avg_pct")),
                "heat_score": safe_float(base.get("heat_score")),
            }
        )
    tags: list[str] = []
    if market_heat >= 70:
        tags.append("市场热度高")
    elif market_heat >= 45:
        tags.append("市场热度中")
    else:
        tags.append("市场热度低")
    if limit_up_count >= 80 or limit_up_ratio >= 0.03:
        tags.append("涨停扩散强")
    elif limit_up_count >= 35 or limit_up_ratio >= 0.012:
        tags.append("涨停扩散中")
    if up_ratio >= 0.65:
        tags.append("赚钱效应强")
    elif up_ratio <= 0.40:
        tags.append("赚钱效应弱")
    if candidate_count >= 30:
        tags.append("候选密集")
    if top_industries:
        leader = top_industries[0]
        if safe_float(leader.get("candidate_weight")) >= 0.35:
            tags.append(f"热点集中:{leader['industry']}")
        tags.append("题材:" + "/".join(str(item["industry"]) for item in top_industries[:3]))
    return {
        "market_heat_score": market_heat,
        "limit_up_count": limit_up_count,
        "limit_up_ratio": limit_up_ratio,
        "up_ratio": up_ratio,
        "hot_tags": tags,
        "top_industries": top_industries,
    }


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


def slice_recommendation(evaluated_count: int, hit_rate: float, avg_target_return: float, avg_drawdown: float) -> str:
    if evaluated_count < 5:
        return "collecting"
    if hit_rate >= 0.55 and avg_target_return >= 0.04 and avg_drawdown > -0.10:
        return "keep"
    if hit_rate >= 0.40 and avg_target_return > 0:
        return "tune"
    return "tighten"


def slice_score(hit_rate: float, limit_up_hit_rate: float, avg_target_return: float, avg_drawdown: float, avg_score: float) -> float:
    drawdown_score = max(0.0, min(1.0, (avg_drawdown + 0.16) / 0.16))
    return max(
        0.0,
        min(
            100.0,
            hit_rate * 34.0
            + limit_up_hit_rate * 18.0
            + max(-0.10, min(0.12, avg_target_return)) / 0.12 * 26.0
            + drawdown_score * 12.0
            + max(0.0, min(100.0, avg_score)) / 100.0 * 10.0,
        ),
    )


def write_results(db_path: Path, data_path: Path, predictions: list[Prediction], results: dict[str, dict[str, object]]) -> tuple[int, int]:
    ts = now_text()
    evaluated = 0
    slice_predictions: dict[tuple[str, str, str, str], list[Prediction]] = {}
    for pred in predictions:
        key = (pred.signal_type, pred.strategy_version, pred.parameter_key, pred.signal_date)
        slice_predictions.setdefault(key, []).append(pred)
    market_context = load_market_context(data_path, sorted({p.signal_date for p in predictions if p.signal_date}))
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
        slice_rows = conn.execute(
            """SELECT signal_type, strategy_version, parameter_key, signal_date,
                      COUNT(*) AS candidate_count,
                      SUM(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN 1 ELSE 0 END) AS evaluated_count,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN target_hit END) AS hit_rate,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN hit_limit_up_5d END) AS limit_up_hit_rate,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_1d END) AS avg_return_1d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_3d END) AS avg_return_3d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_5d END) AS avg_return_5d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN ret_10d END) AS avg_return_10d,
                      AVG(CASE WHEN evaluated_at IS NOT NULL AND evaluated_at != '' THEN max_drawdown_5d END) AS avg_max_drawdown_5d,
                      AVG(score) AS avg_score
               FROM market_limit_signal_predictions
               GROUP BY signal_type, strategy_version, parameter_key, signal_date"""
        ).fetchall()
        for row in slice_rows:
            signal_type = str(row[0])
            strategy_version = str(row[1])
            parameter_key = str(row[2])
            signal_date = str(row[3])
            candidate_count = int(row[4] or 0)
            evaluated_count = int(row[5] or 0)
            hit_rate = safe_float(row[6])
            limit_up_hit_rate = safe_float(row[7])
            avg_return_1d = safe_float(row[8])
            avg_return_3d = safe_float(row[9])
            avg_return_5d = safe_float(row[10])
            avg_return_10d = safe_float(row[11])
            avg_max_drawdown_5d = safe_float(row[12])
            avg_score = safe_float(row[13])
            avg_target_return = avg_return_5d if signal_type == "limit_up_momentum" else avg_return_10d
            score = slice_score(hit_rate, limit_up_hit_rate, avg_target_return, avg_max_drawdown_5d, avg_score)
            rec = slice_recommendation(evaluated_count, hit_rate, avg_target_return, avg_max_drawdown_5d)
            hot_context = slice_hot_context(
                slice_predictions.get((signal_type, strategy_version, parameter_key, signal_date), []),
                market_context.get(signal_date, {}),
            )
            hot_tags = hot_context["hot_tags"]
            top_industries = hot_context["top_industries"]
            summary = {
                "target_horizon": 5 if signal_type == "limit_up_momentum" else 10,
                "target_rule": "avg target return, target_hit rate, limit-up hit rate, drawdown",
                "market_context": {
                    "market_heat_score": hot_context["market_heat_score"],
                    "limit_up_count": hot_context["limit_up_count"],
                    "limit_up_ratio": hot_context["limit_up_ratio"],
                    "up_ratio": hot_context["up_ratio"],
                    "hot_tags": hot_tags,
                    "top_industries": top_industries,
                },
            }
            conn.execute(
                upsert_sql(
                    "market_limit_signal_tm_slices",
                    [
                        "signal_type", "strategy_version", "parameter_key", "signal_date",
                        "candidate_count", "evaluated_count", "hit_rate", "limit_up_hit_rate",
                        "avg_return_1d", "avg_return_3d", "avg_return_5d", "avg_return_10d",
                        "avg_target_return", "avg_max_drawdown_5d", "avg_score", "slice_score",
                        "market_heat_score", "limit_up_count", "limit_up_ratio", "up_ratio",
                        "hot_tags_json", "top_industries_json",
                        "recommendation", "summary_json", "updated_at",
                    ],
                    ["signal_type", "strategy_version", "parameter_key", "signal_date"],
                    [
                        "candidate_count", "evaluated_count", "hit_rate", "limit_up_hit_rate",
                        "avg_return_1d", "avg_return_3d", "avg_return_5d", "avg_return_10d",
                        "avg_target_return", "avg_max_drawdown_5d", "avg_score", "slice_score",
                        "market_heat_score", "limit_up_count", "limit_up_ratio", "up_ratio",
                        "hot_tags_json", "top_industries_json",
                        "recommendation", "summary_json", "updated_at",
                    ],
                ),
                (
                    signal_type, strategy_version, parameter_key, signal_date,
                    candidate_count, evaluated_count, hit_rate, limit_up_hit_rate,
                    avg_return_1d, avg_return_3d, avg_return_5d, avg_return_10d,
                    avg_target_return, avg_max_drawdown_5d, avg_score, score,
                    hot_context["market_heat_score"],
                    hot_context["limit_up_count"],
                    hot_context["limit_up_ratio"],
                    hot_context["up_ratio"],
                    json.dumps(hot_tags, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(top_industries, ensure_ascii=False, separators=(",", ":")),
                    rec, json.dumps(summary, ensure_ascii=False, separators=(",", ":")), ts,
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
        evaluated, pending = write_results(db_path, data_path, predictions, results)
        run_status.progress(TASK_NAME, 100, 100, "done", "刷新评估摘要")
        run_status.done(TASK_NAME, f"已回看 {evaluated} 条预测，待样本成熟 {pending} 条")
        print(json.dumps({"evaluated": evaluated, "pending": pending}, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
