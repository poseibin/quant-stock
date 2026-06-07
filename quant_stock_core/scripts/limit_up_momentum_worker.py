from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra.db import upsert_sql, write_transaction
from common.infra import status as run_status


TASK_NAME = "limit_up_momentum"
SIGNAL_TYPE = "limit_up_momentum"
STRATEGY_VERSION = "v1"


@dataclass
class BreakoutBar:
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    pct_chg: float
    projected: bool = False


@dataclass
class MomentumCandidate:
    ts_code: str
    name: str
    industry: str
    trade_date: str
    close: float
    stage: str
    recommendation: str
    score: float
    chain_potential: float
    end_risk: float
    liquidity_risk: float
    fund_confirmation: float
    limit_up_count: int
    consecutive_boards: int
    next_day_return: float
    return_3d: float
    return_5d: float
    return_10d: float
    max_drawdown_5d: float
    recent_20_return: float
    recent_60_return: float
    turnover_rate: float
    volume_ratio: float
    amount: float
    total_mv: float
    circ_mv: float
    dragon_tiger_net_buy: float
    institution_net_buy: float
    reasons: list[str]
    risks: list[str]
    bars: list[BreakoutBar]
    projected_bars: list[BreakoutBar]


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def limit_threshold(ts_code: str, name: str) -> float:
    if "ST" in str(name).upper():
        return 4.5
    code = str(ts_code)
    if code.startswith("688") or code.startswith("300"):
        return 19.0
    if code.startswith("8") or code.startswith("4") or ".BJ" in code:
        return 28.0
    return 9.2


def read_table(con: duckdb.DuckDBPyConnection, path: Path) -> pd.DataFrame:
    if not path.exists() and "*" not in str(path):
        return pd.DataFrame()
    try:
        return con.execute(f"SELECT * FROM read_parquet('{path}')").fetch_df()
    except Exception:
        return pd.DataFrame()


def latest_daily(data_path: Path, history_days: int) -> pd.DataFrame:
    raw = data_path / "raw"
    max_rows = history_days + 90
    con = duckdb.connect()
    daily = con.execute(
        f"""
        SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol, amount
        FROM (
            SELECT *, row_number() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM read_parquet('{raw / "daily" / "*.parquet"}')
            WHERE close > 0
        )
        WHERE rn <= {max_rows}
        ORDER BY ts_code, trade_date
        """
    ).fetch_df()
    stock = con.execute(
        f"""
        SELECT ts_code, name, industry, list_status
        FROM read_parquet('{raw / "stock_basic" / "data.parquet"}')
        WHERE list_status = 'L' AND upper(name) NOT LIKE '%ST%'
        """
    ).fetch_df()
    basic = read_table(con, raw / "daily_basic" / "*.parquet")
    top_list = read_table(con, raw / "top_list" / "*.parquet")
    top_inst = read_table(con, raw / "top_inst" / "*.parquet")
    con.close()
    return enrich(daily, stock, basic, top_list, top_inst)


def enrich(daily: pd.DataFrame, stock: pd.DataFrame, basic: pd.DataFrame, top_list: pd.DataFrame, top_inst: pd.DataFrame) -> pd.DataFrame:
    df = daily.merge(stock, on="ts_code", how="inner")
    if not basic.empty:
        cols = [c for c in ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "total_mv", "circ_mv"] if c in basic.columns]
        if "ts_code" in cols and "trade_date" in cols:
            df = df.merge(basic[cols], on=["ts_code", "trade_date"], how="left")
    for col in ["turnover_rate", "volume_ratio", "total_mv", "circ_mv"]:
        if col not in df.columns:
            df[col] = 0.0
    if not top_list.empty and "trade_date" in top_list.columns:
        top = top_list.copy()
        for col in ["buy", "sell", "amount"]:
            if col not in top.columns:
                top[col] = 0.0
        top["dragon_tiger_net_buy"] = top["buy"].fillna(0).astype(float) - top["sell"].fillna(0).astype(float)
        top = top.groupby(["ts_code", "trade_date"], as_index=False)["dragon_tiger_net_buy"].sum()
        df = df.merge(top, on=["ts_code", "trade_date"], how="left")
    if "dragon_tiger_net_buy" not in df.columns:
        df["dragon_tiger_net_buy"] = 0.0
    if not top_inst.empty and "trade_date" in top_inst.columns:
        inst = top_inst.copy()
        for col in ["buy", "sell", "buy_amount", "sell_amount"]:
            if col not in inst.columns:
                inst[col] = 0.0
        buy_col = "buy_amount" if "buy_amount" in inst.columns else "buy"
        sell_col = "sell_amount" if "sell_amount" in inst.columns else "sell"
        inst["institution_net_buy"] = inst[buy_col].fillna(0).astype(float) - inst[sell_col].fillna(0).astype(float)
        inst = inst.groupby(["ts_code", "trade_date"], as_index=False)["institution_net_buy"].sum()
        df = df.merge(inst, on=["ts_code", "trade_date"], how="left")
    if "institution_net_buy" not in df.columns:
        df["institution_net_buy"] = 0.0
    df[["dragon_tiger_net_buy", "institution_net_buy"]] = df[["dragon_tiger_net_buy", "institution_net_buy"]].fillna(0.0)
    return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def add_features(group: pd.DataFrame) -> pd.DataFrame:
    g = group.copy()
    threshold = limit_threshold(str(g.iloc[0]["ts_code"]), str(g.iloc[0]["name"]))
    g["is_limit_up"] = g["pct_chg"].astype(float) >= threshold
    g["recent_20_return"] = g["close"].astype(float) / g["close"].shift(20).astype(float) - 1
    g["recent_60_return"] = g["close"].astype(float) / g["close"].shift(60).astype(float) - 1
    g["avg_amount_20"] = g["amount"].astype(float).rolling(20, min_periods=5).mean()
    g["volume_surge"] = g["amount"].astype(float) / g["avg_amount_20"].replace(0, pd.NA)
    g["range_20"] = g["high"].rolling(20, min_periods=5).max() / g["low"].rolling(20, min_periods=5).min() - 1
    g["drawdown_20"] = g["close"] / g["close"].rolling(20, min_periods=5).max() - 1
    g["ma5"] = g["close"].rolling(5, min_periods=3).mean()
    g["ma10"] = g["close"].rolling(10, min_periods=5).mean()
    g["ma20"] = g["close"].rolling(20, min_periods=8).mean()
    g["ma_bull"] = (g["ma5"] >= g["ma10"]) & (g["ma10"] >= g["ma20"])
    g["new_high_60"] = g["close"] >= g["close"].rolling(60, min_periods=20).max()
    g["next_day_return"] = g["close"].shift(-1) / g["close"] - 1
    g["return_3d"] = g["close"].shift(-3) / g["close"] - 1
    g["return_5d"] = g["close"].shift(-5) / g["close"] - 1
    g["return_10d"] = g["close"].shift(-10) / g["close"] - 1
    future_low_5 = pd.concat([g["low"].shift(-i) for i in range(1, 6)], axis=1).min(axis=1)
    g["max_drawdown_5d"] = future_low_5 / g["close"] - 1
    consecutive: list[int] = []
    cur = 0
    for flag in g["is_limit_up"]:
        cur = cur + 1 if bool(flag) else 0
        consecutive.append(cur)
    g["consecutive_boards"] = consecutive
    g["limit_up_count"] = g["is_limit_up"].rolling(10, min_periods=1).sum()
    return g


def recommendation(score: float, end_risk: float, boards: int) -> str:
    if boards >= 4 or end_risk >= 72:
        return "高风险加速"
    if boards >= 2 and score >= 62:
        return "二板确认"
    if boards == 1 and score >= 55:
        return "首板观察"
    return "不追"


def stage(boards: int) -> str:
    if boards <= 1:
        return "首板"
    if boards == 2:
        return "二板"
    return f"{boards}连板"


def next_trade_date(value: str) -> str:
    try:
        cur = datetime.strptime(str(value), "%Y%m%d")
    except ValueError:
        cur = datetime.now()
    cur += timedelta(days=1)
    while cur.weekday() >= 5:
        cur += timedelta(days=1)
    return cur.strftime("%Y%m%d")


def to_bars(df: pd.DataFrame) -> list[BreakoutBar]:
    return [
        BreakoutBar(
            str(row.trade_date),
            safe_float(row.open),
            safe_float(row.high),
            safe_float(row.low),
            safe_float(row.close),
            safe_float(row.pct_chg),
            False,
        )
        for row in df.itertuples(index=False)
    ]


def project_limit_up_bars(row: pd.Series, days: int) -> list[BreakoutBar]:
    rate = limit_threshold(str(row.get("ts_code") or ""), str(row.get("name") or "")) / 100.0
    date = str(row.get("trade_date") or "")
    prev = safe_float(row.get("close"))
    out: list[BreakoutBar] = []
    for _ in range(days):
        date = next_trade_date(date)
        close = round(prev * (1 + rate), 2)
        out.append(BreakoutBar(date, prev, close, prev, close, rate * 100, True))
        prev = close
    return out


def build_candidate(row: pd.Series, bars: pd.DataFrame) -> MomentumCandidate:
    ret20 = safe_float(row.get("recent_20_return"))
    ret60 = safe_float(row.get("recent_60_return"))
    boards = int(safe_float(row.get("consecutive_boards")))
    volume_surge = safe_float(row.get("volume_surge"))
    turnover = safe_float(row.get("turnover_rate"))
    volume_ratio = safe_float(row.get("volume_ratio"))
    total_mv = safe_float(row.get("total_mv"))
    circ_mv = safe_float(row.get("circ_mv"))
    low_position = clamp((0.35 - ret60) / 0.45 * 100)
    trend = 22 if bool(row.get("ma_bull")) else 8
    trend += 18 if bool(row.get("new_high_60")) else 0
    volume = clamp((volume_surge - 1.0) / 4.0 * 100) * 0.45 + clamp(volume_ratio / 3.0 * 100) * 0.25 + clamp(turnover / 18.0 * 100) * 0.30
    small_cap = clamp((2200000 - circ_mv) / 1800000 * 100) if circ_mv > 0 else 40
    chain = clamp(low_position * 0.28 + trend * 0.26 + volume * 0.26 + small_cap * 0.20)
    if boards == 2:
        chain += 8
    if boards >= 3:
        chain -= (boards - 2) * 8
    end_risk = clamp(max(ret20, 0) / 0.75 * 55 + max(boards - 2, 0) * 18 + max(turnover - 18, 0) * 2)
    liquidity_risk = clamp((3.0 - volume_surge) / 3.0 * 45 + (60000 - circ_mv) / 60000 * 25 if circ_mv > 0 else 35)
    fund = clamp(max(safe_float(row.get("dragon_tiger_net_buy")), 0) / 50000 * 55 + max(safe_float(row.get("institution_net_buy")), 0) / 30000 * 45)
    score = clamp(chain * 0.52 + fund * 0.16 + (100 - end_risk) * 0.22 + (100 - liquidity_risk) * 0.10)
    rec = recommendation(score, end_risk, boards)
    reasons: list[str] = []
    risks: list[str] = []
    if boards == 1:
        reasons.append("首板事件，适合观察次日承接")
    elif boards == 2:
        reasons.append("二板确认，连板情绪更强")
    else:
        reasons.append(f"{boards}连板，进入加速阶段")
    if ret60 < 0.25:
        reasons.append("60日位置不高")
    if volume_surge >= 2:
        reasons.append("首板放量明显")
    if bool(row.get("ma_bull")):
        reasons.append("均线结构偏多")
    if fund > 20:
        reasons.append("龙虎榜/机构资金有确认")
    if ret20 > 0.55:
        risks.append("近20日涨幅偏高")
    if boards >= 3:
        risks.append("连板末端波动加大")
    if turnover > 25:
        risks.append("换手过高，分歧加剧")
    if liquidity_risk > 65:
        risks.append("流动性风险偏高")
    return MomentumCandidate(
        ts_code=str(row.get("ts_code") or ""),
        name=str(row.get("name") or ""),
        industry=str(row.get("industry") or ""),
        trade_date=str(row.get("trade_date") or ""),
        close=safe_float(row.get("close")),
        stage=stage(boards),
        recommendation=rec,
        score=score,
        chain_potential=clamp(chain),
        end_risk=end_risk,
        liquidity_risk=liquidity_risk,
        fund_confirmation=fund,
        limit_up_count=int(safe_float(row.get("limit_up_count"))),
        consecutive_boards=boards,
        next_day_return=safe_float(row.get("next_day_return")),
        return_3d=safe_float(row.get("return_3d")),
        return_5d=safe_float(row.get("return_5d")),
        return_10d=safe_float(row.get("return_10d")),
        max_drawdown_5d=safe_float(row.get("max_drawdown_5d")),
        recent_20_return=ret20,
        recent_60_return=ret60,
        turnover_rate=turnover,
        volume_ratio=volume_ratio,
        amount=safe_float(row.get("amount")),
        total_mv=total_mv,
        circ_mv=circ_mv,
        dragon_tiger_net_buy=safe_float(row.get("dragon_tiger_net_buy")),
        institution_net_buy=safe_float(row.get("institution_net_buy")),
        reasons=reasons,
        risks=risks,
        bars=to_bars(bars.tail(520)),
        projected_bars=project_limit_up_bars(row, 5),
    )


def scan(data_path: Path, lookback: int, history_days: int, limit: int, on_progress=None) -> list[MomentumCandidate]:
    df = latest_daily(data_path, history_days)
    if df.empty:
        return []
    stock_groups = list(df.groupby("ts_code", sort=False))
    featured_parts = []
    if on_progress:
        on_progress(0, len(stock_groups), "feature")
    for idx, (_, group) in enumerate(stock_groups, start=1):
        featured_parts.append(add_features(group))
        if on_progress and (idx == 1 or idx == len(stock_groups) or idx % 200 == 0):
            on_progress(idx, len(stock_groups), "feature")
    featured = pd.concat(featured_parts, ignore_index=True)
    latest_dates = sorted(featured["trade_date"].dropna().unique())
    recent_dates = set(latest_dates[-lookback:])
    events = featured[(featured["trade_date"].isin(recent_dates)) & (featured["is_limit_up"])].copy()
    if events.empty:
        return []
    groups = {code: group for code, group in featured.groupby("ts_code", sort=False)}
    items: list[MomentumCandidate] = []
    if on_progress:
        on_progress(0, len(events), "event")
    for idx, (_, row) in enumerate(events.iterrows(), start=1):
        code = str(row.get("ts_code") or "")
        group = groups.get(code, pd.DataFrame())
        bars = group[group["trade_date"] <= row["trade_date"]] if not group.empty else group
        items.append(build_candidate(row, bars))
        if on_progress and (idx == 1 or idx == len(events) or idx % 100 == 0):
            on_progress(idx, len(events), "event")
    items = [item for item in items if item.recommendation != "不追" or item.score >= 45]
    items.sort(key=lambda item: (item.trade_date, item.score), reverse=True)
    deduped: list[MomentumCandidate] = []
    seen: set[str] = set()
    for item in items:
        if item.ts_code in seen:
            continue
        seen.add(item.ts_code)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def ensure_tables(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_limit_momentum_cache (
            cache_key TEXT NOT NULL, rank INTEGER NOT NULL DEFAULT 0, ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL, generated_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(cache_key, ts_code)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS market_limit_momentum_cache_meta (
            cache_key TEXT PRIMARY KEY, item_count INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )"""
    )
    ensure_prediction_tables(conn)


def ensure_prediction_tables(conn) -> None:
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
        """CREATE INDEX IF NOT EXISTS idx_market_limit_signal_predictions_type_date
           ON market_limit_signal_predictions(signal_type, signal_date)"""
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


def write_cache(db_path: Path, cache_key: str, items: list[MomentumCandidate]) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with write_transaction(db_path) as conn:
        ensure_tables(conn)
        conn.execute("DELETE FROM market_limit_momentum_cache WHERE cache_key = ?", (cache_key,))
        conn.execute(
            upsert_sql(
                "market_limit_momentum_cache_meta",
                ["cache_key", "item_count", "generated_at", "updated_at"],
                ["cache_key"],
                ["item_count", "generated_at", "updated_at"],
            ),
            (cache_key, len(items), ts, ts),
        )
        rows = []
        for idx, item in enumerate(items, start=1):
            payload = json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":"))
            rows.append((cache_key, idx, item.ts_code, item.trade_date, item.score, payload, ts, ts))
        conn.executemany(
            """INSERT INTO market_limit_momentum_cache(
                cache_key, rank, ts_code, trade_date, score, payload_json, generated_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            rows,
        )
        prediction_rows = []
        for idx, item in enumerate(items, start=1):
            payload = json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":"))
            pred_id = f"{SIGNAL_TYPE}:{cache_key}:{item.ts_code}:{item.trade_date}"
            prediction_rows.append((
                pred_id, SIGNAL_TYPE, STRATEGY_VERSION, cache_key, cache_key, idx,
                item.ts_code, item.name, item.industry, item.trade_date, item.close, item.score,
                item.recommendation, payload, "{}", "", ts, ts,
            ))
        conn.executemany(
            upsert_sql(
                "market_limit_signal_predictions",
                [
                    "id", "signal_type", "strategy_version", "parameter_key", "cache_key",
                    "rank", "ts_code", "name", "industry", "signal_date", "signal_price",
                    "score", "recommendation", "payload_json", "outcome_json", "evaluated_at",
                    "created_at", "updated_at",
                ],
                ["signal_type", "parameter_key", "ts_code", "signal_date"],
                [
                    "rank", "name", "industry", "signal_price", "score",
                    "recommendation", "payload_json", "outcome_json", "evaluated_at", "updated_at",
                ],
            ),
            prediction_rows,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--cache-key", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--history-days", type=int, default=760)
    args = parser.parse_args()
    try:
        run_status.begin(TASK_NAME)
        run_status.progress(TASK_NAME, 1, 100, "load", "读取涨停与基础行情")
        def report_scan(idx: int, total: int, phase: str) -> None:
            stage = "feature" if phase == "feature" else "event"
            name = "计算股票特征" if phase == "feature" else "构建涨停事件候选"
            pct_idx = 2
            if total > 0 and phase == "feature":
                pct_idx = 2 + int((idx / total) * 54)
            elif total > 0:
                pct_idx = 56 + int((idx / total) * 40)
            run_status.progress(TASK_NAME, min(pct_idx, 96), 100, stage, f"{name} {idx}/{total}")

        items = scan(Path(args.data_path), args.lookback, args.history_days, args.limit, report_scan)
        run_status.progress(TASK_NAME, 98, 100, "persist", f"写入 {len(items)} 个短线候选")
        write_cache(Path(args.db_path), args.cache_key, items)
        run_status.progress(TASK_NAME, 100, 100, "done", "刷新页面缓存")
        run_status.done(TASK_NAME, f"已生成 {len(items)} 个涨停推荐候选")
        print(json.dumps({"count": len(items), "cache_key": args.cache_key}, ensure_ascii=False), flush=True)
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
