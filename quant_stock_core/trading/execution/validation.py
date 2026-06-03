"""信号验证

将 SQLite daily_recommendation 表中的历史信号与次日真实行情对比，
计算组合收益、命中率、单股表现，用于策略效果回看。
"""
from __future__ import annotations

import pandas as pd

from common.config import RAW_DIR
from research.data.storage import duckdb_query as dq
from trading.execution import signal as sig
from common.utils import get_logger

log = get_logger("validation")


def _next_trade_date(date: str) -> str | None:
    cal = dq.get_trade_dates()
    if date not in cal:
        return None
    idx = cal.index(date)
    return cal[idx + 1] if idx + 1 < len(cal) else None


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


def evaluate_signal(date: str) -> dict | None:
    """评估单个交易日信号 vs 次日真实表现。"""
    s = sig.load_by_date(date)
    if not s or not s.get("holdings"):
        return None
    nd = _next_trade_date(date)
    if not nd:
        log.info(f"{date} 无次日交易日（可能是最新日），无法评估")
        return None

    holdings = s["holdings"]
    codes = [h["ts_code"] for h in holdings]
    pct_map = _fetch_pct_chg(nd, codes)
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
        "n_holdings": len(holdings),
        "n_eval": n_eval,
        "weighted_return": weighted_return,
        "equal_weight_return": equal_weight_return,
        "hit_rate": hit_rate,
        "win_count": win,
        "lose_count": lose,
        "details": details,
    }


def evaluate_history() -> pd.DataFrame:
    """对 db 中所有信号逐日评估，返回时间序列 DataFrame。

    columns: date, next_date, n_holdings, weighted_return, equal_weight_return,
             hit_rate, win_count, lose_count, equity_weighted, equity_equal
    """
    rows = []
    for d in sig.list_dates():
        r = evaluate_signal(d)
        if r:
            rows.append({
                "date": r["date"],
                "next_date": r["next_date"],
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
