"""Build daily market risk state.

The stock-level breadth remains the fallback. When index_daily is available we
also anchor the regime to small-cap index behavior so strategy exposure is not
driven by a noisy all-stock average alone.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra.db import add_column, replace_sql, table_columns, write_transaction
from research.data.storage import duckdb_query as dq


INDEX_ANCHOR_CODES = ("932000.CSI", "399303.SZ", "000852.SH", "000905.SH")
INDEX_LARGE_CODES = ("000300.SH", "000905.SH")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    ensure_table(args.db_path)
    states = build_market_risk_state(args.start, args.end)
    save_market_risk_state(args.db_path, states)
    output_path = args.output or str(data_root() / "market_risk_state_daily.parquet")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    states.to_parquet(output_path, index=False, compression="zstd")
    summary = summarize(states, output_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def ensure_table(db_path: str | None) -> None:
    with write_transaction(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_risk_state_daily (
                trade_date VARCHAR(16) PRIMARY KEY,
                state VARCHAR(64) NOT NULL,
                risk_score DOUBLE,
                market_return DOUBLE,
                market_equity DOUBLE,
                up_ratio DOUBLE,
                down_ratio DOUBLE,
                breadth20 DOUBLE,
                limit_up_count BIGINT,
                limit_down_count BIGINT,
                limit_up_ratio DOUBLE,
                limit_down_ratio DOUBLE,
                limit_down_ratio5 DOUBLE,
                amount DOUBLE,
                amount_chg20 DOUBLE,
                small_large_rel20 DOUBLE,
                index_anchor_code VARCHAR(32),
                index_anchor_ret5 DOUBLE,
                index_anchor_ret20 DOUBLE,
                index_anchor_drawdown20 DOUBLE,
                index_anchor_rel20 DOUBLE,
                drawdown20 DOUBLE,
                drawdown60 DOUBLE,
                drawdown120 DOUBLE,
                trend60 DOUBLE,
                volatility20 DOUBLE,
                universe_count BIGINT,
                reason VARCHAR(512),
                summary_json LONGTEXT,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                KEY idx_market_risk_state_state (state),
                KEY idx_market_risk_state_score (risk_score)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        existing = table_columns(conn, "market_risk_state_daily")
        for name, ddl in [
            ("index_anchor_code", "VARCHAR(32)"),
            ("index_anchor_ret5", "DOUBLE"),
            ("index_anchor_ret20", "DOUBLE"),
            ("index_anchor_drawdown20", "DOUBLE"),
            ("index_anchor_rel20", "DOUBLE"),
        ]:
            if name not in existing:
                add_column(conn, "market_risk_state_daily", name, ddl)


def build_market_risk_state(start: str, end: str) -> pd.DataFrame:
    raw = dq.RAW_DIR
    # Pull a warmup window so rolling metrics are available at start.
    warmup_start = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=260)).strftime("%Y%m%d")
    daily = dq.sql(
        f"""
        SELECT d.trade_date, d.ts_code, d.pct_chg / 100.0 AS ret,
               d.amount * 1000 AS amount,
               db.total_mv * 10000 AS total_mv,
               COALESCE(sb.name, '') AS name
        FROM read_parquet('{raw / "daily" / "*.parquet"}') d
        LEFT JOIN read_parquet('{raw / "daily_basic" / "*.parquet"}') db
          ON d.trade_date = db.trade_date AND d.ts_code = db.ts_code
        LEFT JOIN read_parquet('{raw / "stock_basic" / "data.parquet"}') sb
          ON d.ts_code = sb.ts_code
        WHERE d.trade_date BETWEEN '{warmup_start}' AND '{end}'
          AND d.pct_chg IS NOT NULL
          AND d.amount IS NOT NULL
          AND d.amount > 0
          AND COALESCE(sb.name, '') NOT LIKE '%ST%'
        ORDER BY d.trade_date, d.ts_code
        """
    )
    if daily.empty:
        return pd.DataFrame()
    daily["trade_date"] = daily["trade_date"].astype(str)
    for col in ["ret", "amount", "total_mv"]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna(subset=["ret"])
    daily["is_up"] = daily["ret"] > 0
    daily["is_down"] = daily["ret"] < 0
    daily["is_limit_up"] = daily["ret"] >= 0.095
    daily["is_limit_down"] = daily["ret"] <= -0.095

    daily["mv_rank"] = daily.groupby("trade_date")["total_mv"].rank(pct=True)
    daily["small_ret"] = np.where(daily["mv_rank"] <= 0.30, daily["ret"], np.nan)
    daily["large_ret"] = np.where(daily["mv_rank"] >= 0.70, daily["ret"], np.nan)

    grouped = daily.groupby("trade_date", sort=True)
    state = grouped.agg(
        universe_count=("ts_code", "nunique"),
        market_return=("ret", "mean"),
        median_return=("ret", "median"),
        up_ratio=("is_up", "mean"),
        down_ratio=("is_down", "mean"),
        limit_up_count=("is_limit_up", "sum"),
        limit_down_count=("is_limit_down", "sum"),
        limit_up_ratio=("is_limit_up", "mean"),
        limit_down_ratio=("is_limit_down", "mean"),
        amount=("amount", "sum"),
        small_return=("small_ret", "mean"),
        large_return=("large_ret", "mean"),
    ).reset_index()
    state = state.sort_values("trade_date").reset_index(drop=True)
    state["market_equity"] = (1.0 + state["market_return"].fillna(0.0)).cumprod()
    state["breadth20"] = state["up_ratio"].rolling(20, min_periods=5).mean()
    state["limit_down_ratio5"] = state["limit_down_ratio"].rolling(5, min_periods=1).mean()
    state["amount_chg20"] = state["amount"] / state["amount"].rolling(20, min_periods=5).mean() - 1.0
    state["small_large_rel20"] = (state["small_return"] - state["large_return"]).rolling(20, min_periods=5).sum()
    for window in [20, 60, 120]:
        state[f"drawdown{window}"] = state["market_equity"] / state["market_equity"].rolling(window, min_periods=5).max() - 1.0
    state["trend60"] = state["market_equity"].pct_change(60)
    state["volatility20"] = state["market_return"].rolling(20, min_periods=5).std() * np.sqrt(244.0)
    index_metrics = load_index_anchor_metrics(warmup_start, end)
    if not index_metrics.empty:
        state = state.merge(index_metrics, on="trade_date", how="left")
    for col in ["index_anchor_code", "index_anchor_ret5", "index_anchor_ret20", "index_anchor_drawdown20", "index_anchor_rel20"]:
        if col not in state.columns:
            state[col] = "" if col == "index_anchor_code" else np.nan

    classified = state.apply(classify_row, axis=1, result_type="expand")
    state["state"] = classified["state"]
    state["risk_score"] = classified["risk_score"].astype(float)
    state["reason"] = classified["reason"]
    state["summary_json"] = state.apply(row_summary, axis=1)
    state = state[state["trade_date"].between(start, end)].reset_index(drop=True)
    return state[
        [
            "trade_date", "state", "risk_score", "market_return", "market_equity",
            "up_ratio", "down_ratio", "breadth20", "limit_up_count", "limit_down_count",
            "limit_up_ratio", "limit_down_ratio", "limit_down_ratio5", "amount", "amount_chg20",
            "small_large_rel20", "index_anchor_code", "index_anchor_ret5", "index_anchor_ret20",
            "index_anchor_drawdown20", "index_anchor_rel20", "drawdown20", "drawdown60", "drawdown120", "trend60",
            "volatility20", "universe_count", "reason", "summary_json",
        ]
    ]


def load_index_anchor_metrics(start: str, end: str) -> pd.DataFrame:
    rows = dq.sql(
        f"""
        SELECT ts_code, trade_date, close
        FROM read_parquet('{dq.RAW_DIR / "index_daily" / "*.parquet"}')
        WHERE trade_date BETWEEN '{start}' AND '{end}'
          AND ts_code IN ({quote_sql(INDEX_ANCHOR_CODES + INDEX_LARGE_CODES)})
        ORDER BY trade_date, ts_code
        """
    )
    if rows.empty:
        return pd.DataFrame()
    rows["trade_date"] = rows["trade_date"].astype(str)
    rows["ts_code"] = rows["ts_code"].astype(str)
    rows["close"] = pd.to_numeric(rows["close"], errors="coerce")
    close = rows.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    small_cols = [code for code in INDEX_ANCHOR_CODES if code in close.columns]
    large_code = first_existing_column(close, INDEX_LARGE_CODES)
    if not small_cols:
        return pd.DataFrame()
    small_matrix = close[small_cols]
    small = small_matrix.bfill(axis=1).iloc[:, 0]
    small_code = small_matrix.apply(first_valid_code, axis=1)
    large = close[large_code] if large_code else pd.Series(np.nan, index=close.index)
    out = pd.DataFrame({"trade_date": close.index.astype(str)})
    out["index_anchor_code"] = small_code.to_numpy()
    out["index_anchor_ret5"] = small.pct_change(5).to_numpy()
    out["index_anchor_ret20"] = small.pct_change(20).to_numpy()
    out["index_anchor_drawdown20"] = (small / small.rolling(20, min_periods=5).max() - 1.0).to_numpy()
    out["index_anchor_rel20"] = (small.pct_change(20) - large.pct_change(20)).to_numpy()
    return out.replace([np.inf, -np.inf], np.nan)


def first_existing_column(frame: pd.DataFrame, codes: tuple[str, ...]) -> str:
    for code in codes:
        if code in frame.columns and frame[code].notna().any():
            return code
    return ""


def first_valid_code(row: pd.Series) -> str:
    for code, value in row.items():
        if pd.notna(value):
            return str(code)
    return ""


def quote_sql(values: tuple[str, ...]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


def classify_row(row: pd.Series) -> dict[str, Any]:
    market_return = safe_float(row.get("market_return"))
    breadth20 = safe_float(row.get("breadth20"))
    limit_down = safe_float(row.get("limit_down_ratio"))
    limit_down5 = safe_float(row.get("limit_down_ratio5"))
    amount_chg20 = safe_float(row.get("amount_chg20"))
    rel20 = safe_float(row.get("small_large_rel20"))
    dd20 = safe_float(row.get("drawdown20"))
    dd60 = safe_float(row.get("drawdown60"))
    dd120 = safe_float(row.get("drawdown120"))
    trend60 = safe_float(row.get("trend60"))
    vol20 = safe_float(row.get("volatility20"))
    index_ret5 = safe_float(row.get("index_anchor_ret5"))
    index_ret20 = safe_float(row.get("index_anchor_ret20"))
    index_dd20 = safe_float(row.get("index_anchor_drawdown20"))
    index_rel20 = safe_float(row.get("index_anchor_rel20"))

    reasons: list[str] = []
    risk = 0.0
    risk += score_negative(dd20, -0.04, -0.12) * 24
    risk += score_negative(dd60, -0.08, -0.20) * 18
    risk += score_negative(dd120, -0.10, -0.28) * 12
    risk += score_negative(breadth20 - 0.50, -0.08, -0.22) * 18
    risk += score_positive(limit_down5, 0.003, 0.035) * 14
    risk += score_negative(rel20, -0.03, -0.12) * 8
    risk += score_negative(index_ret20, -0.04, -0.12) * 12
    risk += score_negative(index_dd20, -0.06, -0.15) * 12
    risk += score_negative(index_rel20, -0.03, -0.10) * 8
    risk += score_positive(vol20, 0.22, 0.42) * 6
    risk = float(np.clip(risk, 0.0, 100.0))

    if limit_down >= 0.04 or market_return <= -0.055 or index_ret5 <= -0.055 or index_dd20 <= -0.14 or (dd20 <= -0.12 and breadth20 <= 0.38):
        reasons.append("crash: 跌停扩散/单日急跌/短期回撤与宽度共振")
        state = "crash"
    elif (limit_down5 >= 0.018 and breadth20 <= 0.43) or (amount_chg20 <= -0.28 and vol20 >= 0.26 and breadth20 <= 0.45):
        reasons.append("liquidity_squeeze: 跌停扩散或缩量高波动")
        state = "liquidity_squeeze"
    elif dd60 <= -0.15 and trend60 > 0 and breadth20 >= 0.47:
        reasons.append("post_crash_repair: 中期深回撤后的修复")
        state = "post_crash_repair"
    elif trend60 < 0 or dd60 <= -0.08 or breadth20 <= 0.45 or rel20 <= -0.08 or index_ret20 <= -0.04 or index_rel20 <= -0.06:
        reasons.append("weak: 趋势/宽度/小盘相对强弱偏弱")
        state = "weak"
    else:
        reasons.append("normal")
        state = "normal"

    if dd20 <= -0.08:
        reasons.append(f"20日回撤{dd20:.1%}")
    if breadth20 <= 0.45:
        reasons.append(f"20日宽度{breadth20:.1%}")
    if limit_down5 >= 0.01:
        reasons.append(f"5日跌停占比{limit_down5:.2%}")
    if rel20 <= -0.08:
        reasons.append(f"小盘相对弱{rel20:.1%}")
    if np.isfinite(index_ret20) and index_ret20 <= -0.04:
        reasons.append(f"指数锚点20日{index_ret20:.1%}")
    if np.isfinite(index_rel20) and index_rel20 <= -0.06:
        reasons.append(f"小盘指数相对弱{index_rel20:.1%}")
    return {"state": state, "risk_score": risk, "reason": "；".join(reasons)}


def save_market_risk_state(db_path: str | None, state: pd.DataFrame) -> None:
    if state.empty:
        return
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    columns = [
        "trade_date", "state", "risk_score", "market_return", "market_equity",
        "up_ratio", "down_ratio", "breadth20", "limit_up_count", "limit_down_count",
        "limit_up_ratio", "limit_down_ratio", "limit_down_ratio5", "amount", "amount_chg20",
        "small_large_rel20", "index_anchor_code", "index_anchor_ret5", "index_anchor_ret20",
        "index_anchor_drawdown20", "index_anchor_rel20", "drawdown20", "drawdown60", "drawdown120", "trend60",
        "volatility20", "universe_count", "reason", "summary_json", "created_at", "updated_at",
    ]
    sql = replace_sql("market_risk_state_daily", columns, ["trade_date"])
    params = []
    for row in state.itertuples(index=False):
        params.append(
            (
                str(row.trade_date), str(row.state), f_or_none(row.risk_score), f_or_none(row.market_return),
                f_or_none(row.market_equity), f_or_none(row.up_ratio), f_or_none(row.down_ratio),
                f_or_none(row.breadth20), i_or_none(row.limit_up_count), i_or_none(row.limit_down_count),
                f_or_none(row.limit_up_ratio), f_or_none(row.limit_down_ratio), f_or_none(row.limit_down_ratio5),
                f_or_none(row.amount), f_or_none(row.amount_chg20), f_or_none(row.small_large_rel20),
                str(row.index_anchor_code or ""), f_or_none(row.index_anchor_ret5), f_or_none(row.index_anchor_ret20),
                f_or_none(row.index_anchor_drawdown20), f_or_none(row.index_anchor_rel20),
                f_or_none(row.drawdown20), f_or_none(row.drawdown60), f_or_none(row.drawdown120),
                f_or_none(row.trend60), f_or_none(row.volatility20), i_or_none(row.universe_count),
                str(row.reason or ""), str(row.summary_json or "{}"), now, now,
            )
        )
    with write_transaction(db_path) as conn:
        conn.executemany(sql, params)


def row_summary(row: pd.Series) -> str:
    payload = {
        "median_return": f_or_none(row.get("median_return")),
        "small_return": f_or_none(row.get("small_return")),
        "large_return": f_or_none(row.get("large_return")),
        "index_anchor_code": str(row.get("index_anchor_code") or ""),
        "index_anchor_ret5": f_or_none(row.get("index_anchor_ret5")),
        "index_anchor_ret20": f_or_none(row.get("index_anchor_ret20")),
        "index_anchor_drawdown20": f_or_none(row.get("index_anchor_drawdown20")),
        "index_anchor_rel20": f_or_none(row.get("index_anchor_rel20")),
    }
    return json.dumps(payload, ensure_ascii=False)


def summarize(state: pd.DataFrame, output_path: str) -> dict[str, Any]:
    counts = state["state"].value_counts().to_dict() if not state.empty else {}
    top_risk = state.sort_values("risk_score", ascending=False).head(20).to_dict(orient="records") if not state.empty else []
    return {
        "rows": int(len(state)),
        "start": str(state["trade_date"].min()) if not state.empty else "",
        "end": str(state["trade_date"].max()) if not state.empty else "",
        "state_counts": {str(k): int(v) for k, v in counts.items()},
        "output_path": output_path,
        "top_risk_days": top_risk,
    }


def score_negative(value: float, mild: float, severe: float) -> float:
    if not np.isfinite(value):
        return 0.0
    if value >= mild:
        return 0.0
    if value <= severe:
        return 1.0
    return float((mild - value) / (mild - severe))


def score_positive(value: float, mild: float, severe: float) -> float:
    if not np.isfinite(value):
        return 0.0
    if value <= mild:
        return 0.0
    if value >= severe:
        return 1.0
    return float((value - mild) / (severe - mild))


def safe_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return float("nan")
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def f_or_none(value: Any) -> float | None:
    value = safe_float(value)
    return float(value) if np.isfinite(value) else None


def i_or_none(value: Any) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def data_root() -> Path:
    import os

    return Path(os.getenv("DATA_ROOT", str(ROOT.parent / "data_store"))).expanduser().resolve()


if __name__ == "__main__":
    main()
