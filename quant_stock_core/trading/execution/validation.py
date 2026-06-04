"""信号验证

将 SQLite daily_recommendation 表中的历史信号与次日真实行情对比，
计算组合收益、命中率、单股表现，用于策略效果回看。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
sys.path = [p for p in sys.path if Path(p or ".").resolve() != SCRIPT_DIR]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from common.infra.db import desktop_db_path
from common.config import RAW_DIR
from research.data.storage import duckdb_query as dq
from trading.execution import signal as sig
from common.utils import get_logger

log = get_logger("validation")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _next_trade_date(date: str) -> str | None:
    return _future_trade_date(date, 1)


def _future_trade_date(date: str, horizon_days: int) -> str | None:
    cal = dq.get_trade_dates()
    if date not in cal:
        return None
    idx = cal.index(date)
    target = idx + max(1, horizon_days)
    return cal[target] if target < len(cal) else None


def _fetch_pct_chg(date: str, codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, pct_chg
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date = '{date}' AND ts_code IN ({in_clause})
    """)
    if df.empty:
        return {}
    return {r["ts_code"]: float(r["pct_chg"]) for _, r in df.iterrows() if pd.notna(r["pct_chg"])}


def _fetch_window_return(start_exclusive: str, end_date: str, codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, trade_date, pct_chg
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date > '{start_exclusive}' AND trade_date <= '{end_date}' AND ts_code IN ({in_clause})
        ORDER BY ts_code, trade_date
    """)
    if df.empty:
        return {}
    out: dict[str, float] = {}
    for code, sub in df.groupby("ts_code"):
        equity = 1.0
        for _, row in sub.iterrows():
            if pd.notna(row["pct_chg"]):
                equity *= 1 + float(row["pct_chg"]) / 100.0
        out[str(code)] = (equity - 1.0) * 100.0
    return out


def _fetch_names(codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    try:
        df = dq.sql(f"""
            SELECT ts_code, name
            FROM read_parquet('{RAW_DIR / "stock_basic" / "*.parquet"}')
            WHERE ts_code IN ({in_clause})
        """)
    except Exception:
        return {}
    return {r["ts_code"]: r["name"] for _, r in df.iterrows()}


def evaluate_signal(date: str, horizon_days: int = 1) -> dict | None:
    """评估单个交易日信号 vs 次日真实表现。"""
    s = sig.load_by_date(date)
    if not s or not s.get("holdings"):
        return None
    nd = _future_trade_date(date, horizon_days)
    if not nd:
        log.info(f"{date} 无 {horizon_days} 日后交易日（可能是最新日），无法评估")
        return None

    holdings = s["holdings"]
    codes = [h["ts_code"] for h in holdings]
    pct_map = _fetch_pct_chg(nd, codes) if horizon_days <= 1 else _fetch_window_return(date, nd, codes)
    if not pct_map:
        return None
    name_map = _fetch_names(codes)

    details = []
    weighted_return = 0.0
    equal_rets = []
    win = lose = 0
    for h in holdings:
        code = h["ts_code"]
        w = float(h["weight"])
        pct = pct_map.get(code)
        if pct is None:
            details.append({
                "ts_code": code, "name": name_map.get(code, "—"),
                "weight": w, "pct": None, "contrib": None,
            })
            continue
        contrib = w * pct
        weighted_return += contrib
        equal_rets.append(pct)
        if pct > 0:
            win += 1
        elif pct < 0:
            lose += 1
        details.append({
            "ts_code": code, "name": name_map.get(code, "—"),
            "weight": w, "pct": pct, "contrib": contrib,
        })

    n_eval = len([d for d in details if d.get("pct") is not None])
    equal_weight_return = sum(equal_rets) / len(equal_rets) if equal_rets else 0.0
    hit_rate = win / n_eval if n_eval else 0.0

    return {
        "date": date,
        "next_date": nd,
        "horizon_days": horizon_days,
        "n_holdings": len(holdings),
        "n_eval": n_eval,
        "weighted_return": weighted_return,
        "equal_weight_return": equal_weight_return,
        "hit_rate": hit_rate,
        "win_count": win,
        "lose_count": lose,
        "details": details,
    }


def evaluate_history(horizon_days: int = 1) -> pd.DataFrame:
    """对 db 中所有信号逐日评估，返回时间序列 DataFrame。

    columns: date, next_date, n_holdings, weighted_return, equal_weight_return,
             hit_rate, win_count, lose_count, equity_weighted, equity_equal
    """
    rows = []
    for d in sig.list_dates():
        r = evaluate_signal(d, horizon_days=horizon_days)
        if r:
            rows.append({
                "date": r["date"],
                "next_date": r["next_date"],
                "horizon_days": r["horizon_days"],
                "n_holdings": r["n_holdings"],
                "weighted_return": r["weighted_return"],
                "equal_weight_return": r["equal_weight_return"],
                "hit_rate": r["hit_rate"],
                "win_count": r["win_count"],
                "lose_count": r["lose_count"],
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    eq_w = 1.0
    eq_e = 1.0
    cum_w, cum_e = [], []
    for _, r in df.iterrows():
        eq_w *= 1 + r["weighted_return"] / 100.0
        eq_e *= 1 + r["equal_weight_return"] / 100.0
        cum_w.append(eq_w)
        cum_e.append(eq_e)
    df["equity_weighted"] = cum_w
    df["equity_equal"] = cum_e
    return df


def persist_history(db_path: str | None = None, horizon_days: int = 1) -> list[dict]:
    """把推荐回看写回 SQLite recommendation_hindsight。"""
    df = evaluate_history(horizon_days=horizon_days)
    if df.empty:
        return []
    path = db_path or str(desktop_db_path())
    now = _now()
    rows: list[dict] = []
    with sqlite3.connect(path, timeout=30.0) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_hindsight (
                id TEXT PRIMARY KEY,
                recommendation_date TEXT NOT NULL,
                horizon_days INTEGER NOT NULL DEFAULT 1,
                next_date TEXT NOT NULL DEFAULT '',
                n_holdings INTEGER NOT NULL DEFAULT 0,
                n_eval INTEGER NOT NULL DEFAULT 0,
                weighted_return REAL,
                equal_weight_return REAL,
                hit_rate REAL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(recommendation_date, horizon_days)
            )
            """
        )
        for _, item in df.iterrows():
            payload = {k: (None if pd.isna(v) else v) for k, v in item.to_dict().items()}
            rec_date = str(payload.get("date") or "")
            row_id = f"rh_{rec_date}_{horizon_days}"
            conn.execute(
                """
                INSERT INTO recommendation_hindsight(
                    id, recommendation_date, horizon_days, next_date, n_holdings, n_eval,
                    weighted_return, equal_weight_return, hit_rate, payload_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recommendation_date, horizon_days) DO UPDATE SET
                    next_date = excluded.next_date,
                    n_holdings = excluded.n_holdings,
                    n_eval = excluded.n_eval,
                    weighted_return = excluded.weighted_return,
                    equal_weight_return = excluded.equal_weight_return,
                    hit_rate = excluded.hit_rate,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    row_id,
                    rec_date,
                    horizon_days,
                    str(payload.get("next_date") or ""),
                    int(payload.get("n_holdings") or 0),
                    int(payload.get("n_eval") or 0),
                    payload.get("weighted_return"),
                    payload.get("equal_weight_return"),
                    payload.get("hit_rate"),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            rows.append(payload)
    return rows


def fetch_benchmark(start: str, end: str, code: str = "000300.SH") -> pd.DataFrame:
    """取基准指数（默认沪深300）区间，返回 trade_date / pct_chg / equity。

    若 RAW_DIR/index_daily 不存在，返回空 DF。
    """
    idx_dir = RAW_DIR / "index_daily"
    if not idx_dir.exists():
        return pd.DataFrame()
    try:
        df = dq.sql(f"""
            SELECT trade_date, pct_chg
            FROM read_parquet('{idx_dir / "*.parquet"}')
            WHERE ts_code = '{code}' AND trade_date BETWEEN '{start}' AND '{end}'
            ORDER BY trade_date
        """)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    eq = 1.0
    cum = []
    for _, r in df.iterrows():
        eq *= 1 + (r["pct_chg"] or 0) / 100.0
        cum.append(eq)
    df["equity"] = cum
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新 daily_recommendation 回看结果")
    parser.add_argument("--persist", action="store_true", help="写入 SQLite recommendation_hindsight")
    parser.add_argument("--db-path", default=None, help="SQLite meta.db 路径")
    parser.add_argument("--horizon-days", type=int, default=1)
    parser.add_argument("--horizons", default="", help="逗号分隔多周期，例如 1,3,5,10,20")
    args = parser.parse_args()
    if args.persist:
        horizons = [int(x) for x in args.horizons.split(",") if x.strip().isdigit()] if args.horizons else [args.horizon_days]
        rows = []
        for horizon in horizons:
            rows.extend(persist_history(args.db_path, horizon))
        print(json.dumps({"rows": len(rows)}, ensure_ascii=False))
    else:
        df = evaluate_history(horizon_days=args.horizon_days)
        print(df.to_json(orient="records", force_ascii=False))


if __name__ == "__main__":
    main()
