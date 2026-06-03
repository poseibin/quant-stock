from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd


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
class Candidate:
    ts_code: str
    name: str
    industry: str
    latest_date: str
    close: float
    score: float
    flat_score: float
    breakout_score: float
    quality_score: float
    base_low: float
    base_high: float
    base_ratio: float
    base_return: float
    recent_return: float
    limit_up_count: int
    volume_surge: float
    roe: float
    net_margin: float
    debt_to_assets: float
    reasons: list[str]
    bars: list[BreakoutBar]
    projected_bars: list[BreakoutBar]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except Exception:
        return default


def limit_rate(ts_code: str, name: str) -> float:
    code = ts_code or ""
    upper_name = (name or "").upper()
    if "ST" in upper_name:
        return 0.05
    if code.startswith("688") or code.startswith("300"):
        return 0.20
    if code.startswith("8") or code.startswith("4") or ".BJ" in code:
        return 0.30
    return 0.10


def close_volatility(values: pd.Series) -> float:
    returns = values.pct_change().replace([math.inf, -math.inf], pd.NA).dropna()
    if returns.empty:
        return 0.0
    return safe_float(returns.std(ddof=0))


def business_quality_score(row: pd.Series | None) -> float:
    if row is None:
        return 0.0
    roe = clamp01(safe_float(row.get("roe")) / 12.0)
    margin = clamp01(safe_float(row.get("netprofit_margin")) / 12.0)
    debt_raw = safe_float(row.get("debt_to_assets"))
    debt = 0.5 if debt_raw <= 0 else clamp01((85.0 - debt_raw) / 60.0)
    return roe * 0.45 + margin * 0.25 + debt * 0.30


def next_trade_date(value: str) -> str:
    try:
        cur = datetime.strptime(value, "%Y%m%d")
    except ValueError:
        cur = datetime.now()
    cur += timedelta(days=1)
    while cur.weekday() >= 5:
        cur += timedelta(days=1)
    return cur.strftime("%Y%m%d")


def project_limit_up_bars(latest: pd.Series, stock: pd.Series, days: int) -> list[BreakoutBar]:
    rate = limit_rate(str(stock.get("ts_code") or ""), str(stock.get("name") or ""))
    date = str(latest.get("trade_date") or "")
    prev = safe_float(latest.get("close"))
    out: list[BreakoutBar] = []
    for _ in range(days):
        date = next_trade_date(date)
        close = round(prev * (1 + rate), 2)
        out.append(BreakoutBar(date, prev, close, prev, close, rate * 100, True))
        prev = close
    return out


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


def amount_surge(base: pd.DataFrame, recent: pd.DataFrame) -> float:
    base_amount = safe_float(base.tail(120)["amount"].mean())
    recent_amount = safe_float(recent.tail(5)["amount"].mean())
    if base_amount <= 0:
        return 0.0
    return recent_amount / base_amount


def count_limit_ups(recent: pd.DataFrame, stock: pd.Series) -> int:
    rate = limit_rate(str(stock.get("ts_code") or ""), str(stock.get("name") or ""))
    threshold = rate * 100 - 0.5
    count = 0
    for row in recent.itertuples(index=False):
        pct = safe_float(row.pct_chg)
        pre_close = safe_float(row.pre_close)
        close = safe_float(row.close)
        if pct >= threshold or (pre_close > 0 and close / pre_close - 1 >= rate - 0.005):
            count += 1
    return count


def score_one(stock: pd.Series, bars: pd.DataFrame, financial: pd.Series | None, lookback: int, recent_days: int) -> Candidate | None:
    if len(bars) < 260 + recent_days:
        return None
    bars = bars.sort_values("trade_date")
    if len(bars) > lookback + recent_days:
        bars = bars.tail(lookback + recent_days)
    if len(bars) < 260 + recent_days:
        return None
    base = bars.iloc[:-recent_days]
    recent = bars.iloc[-recent_days:]
    closes = base["close"].astype(float)
    base_low = safe_float(closes.min())
    base_high = safe_float(closes.max())
    if base_low <= 0 or base_high <= 0:
        return None
    base_ratio = base_high / base_low
    base_return = safe_float(base.iloc[-1]["close"]) / safe_float(base.iloc[0]["close"], 1.0) - 1
    base_volatility = close_volatility(closes)
    latest = recent.iloc[-1]
    recent_return = safe_float(latest["close"]) / safe_float(recent.iloc[0]["close"], 1.0) - 1
    limit_count = count_limit_ups(recent, stock)
    volume_surge = amount_surge(base, recent)
    breakout_ratio = safe_float(latest["close"]) / base_high

    flat_score = clamp01((2.4 - base_ratio) / 1.1) * 0.45 + clamp01((0.55 - abs(base_return)) / 0.55) * 0.25 + clamp01((0.018 - base_volatility) / 0.018) * 0.30
    breakout_score = clamp01(recent_return / 0.75) * 0.35 + clamp01(limit_count / 5.0) * 0.35 + clamp01((volume_surge - 1.0) / 5.0) * 0.15 + clamp01((breakout_ratio - 1.0) / 0.5) * 0.15
    quality_score = business_quality_score(financial)
    score = 100 * (flat_score * 0.42 + breakout_score * 0.38 + quality_score * 0.20)
    if flat_score < 0.38 or breakout_score < 0.22:
        return None
    if recent_return < 0.05 and limit_count == 0 and breakout_ratio < 1.05:
        return None

    reasons: list[str] = []
    if base_ratio < 1.8:
        reasons.append("长期箱体窄，K线接近水平")
    if abs(base_return) < 0.30:
        reasons.append("多年中枢变化小")
    if limit_count > 0:
        reasons.append("近期出现涨停/接近涨停")
    if volume_surge >= 2.5:
        reasons.append("成交额明显放大")
    roe = safe_float(financial.get("roe") if financial is not None else 0)
    net_margin = safe_float(financial.get("netprofit_margin") if financial is not None else 0)
    debt_to_assets = safe_float(financial.get("debt_to_assets") if financial is not None else 0)
    if roe > 0:
        reasons.append("最新ROE为正")
    if 0 < debt_to_assets < 70:
        reasons.append("资产负债率可控")

    return Candidate(
        ts_code=str(stock.get("ts_code") or ""),
        name=str(stock.get("name") or ""),
        industry=str(stock.get("industry") or ""),
        latest_date=str(latest["trade_date"]),
        close=safe_float(latest["close"]),
        score=score,
        flat_score=flat_score * 100,
        breakout_score=breakout_score * 100,
        quality_score=quality_score * 100,
        base_low=base_low,
        base_high=base_high,
        base_ratio=base_ratio,
        base_return=base_return,
        recent_return=recent_return,
        limit_up_count=limit_count,
        volume_surge=volume_surge,
        roe=roe,
        net_margin=net_margin,
        debt_to_assets=debt_to_assets,
        reasons=reasons,
        bars=to_bars(bars.tail(520)),
        projected_bars=project_limit_up_bars(latest, stock, 5),
    )


def read_inputs(data_path: Path, lookback: int, recent_days: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = data_path / "raw"
    max_bars = lookback + recent_days + 80
    con = duckdb.connect()
    daily = con.execute(
        f"""
        SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg, amount
        FROM (
            SELECT *, row_number() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) AS rn
            FROM read_parquet('{raw / "daily" / "*.parquet"}')
            WHERE close > 0
        )
        WHERE rn <= {max_bars}
        ORDER BY ts_code, trade_date
        """
    ).fetch_df()
    stocks = con.execute(
        f"""
        SELECT ts_code, name, industry, list_status
        FROM read_parquet('{raw / "stock_basic" / "data.parquet"}')
        WHERE list_status = 'L' AND upper(name) NOT LIKE '%ST%'
        """
    ).fetch_df()
    financial = con.execute(
        f"""
        SELECT ts_code, roe, netprofit_margin, debt_to_assets
        FROM (
            SELECT *, row_number() OVER (PARTITION BY ts_code ORDER BY end_date DESC) AS rn
            FROM read_parquet('{raw / "fina_indicator" / "*.parquet"}')
            WHERE ts_code IS NOT NULL
        )
        WHERE rn = 1
        """
    ).fetch_df()
    con.close()
    return stocks, daily, financial


def scan(data_path: Path, lookback: int, recent_days: int, limit: int) -> list[Candidate]:
    stocks, daily, financial = read_inputs(data_path, lookback, recent_days)
    financial_map = {row.ts_code: row for row in financial.itertuples(index=False)}
    daily_groups = {code: group for code, group in daily.groupby("ts_code", sort=False)}
    candidates: list[Candidate] = []
    for stock_tuple in stocks.itertuples(index=False):
        stock = pd.Series(stock_tuple._asdict())
        code = str(stock.get("ts_code") or "")
        bars = daily_groups.get(code)
        if bars is None:
            continue
        fin_tuple = financial_map.get(code)
        fin = pd.Series(fin_tuple._asdict()) if fin_tuple is not None else None
        candidate = score_one(stock, bars, fin, lookback, recent_days)
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:limit]


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS limit_breakout_cache (
            cache_key TEXT NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            ts_code TEXT NOT NULL,
            latest_date TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(cache_key, ts_code)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS limit_breakout_cache_meta (
            cache_key TEXT PRIMARY KEY,
            item_count INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def write_cache(db_path: Path, cache_key: str, candidates: list[Candidate]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    ensure_tables(conn)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute("DELETE FROM limit_breakout_cache WHERE cache_key = ?", (cache_key,))
        conn.execute(
            """INSERT INTO limit_breakout_cache_meta(cache_key,item_count,generated_at,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(cache_key) DO UPDATE SET item_count=excluded.item_count,
               generated_at=excluded.generated_at, updated_at=excluded.updated_at""",
            (cache_key, len(candidates), ts, ts),
        )
        rows = []
        for idx, item in enumerate(candidates, start=1):
            payload = json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":"))
            rows.append((cache_key, idx, item.ts_code, item.latest_date, item.score, payload, ts, ts))
        conn.executemany(
            """INSERT INTO limit_breakout_cache(
                cache_key, rank, ts_code, latest_date, score, payload_json, generated_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            rows,
        )
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--cache-key", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lookback", type=int, default=1250)
    parser.add_argument("--recent-days", type=int, default=20)
    args = parser.parse_args()
    candidates = scan(Path(args.data_path), args.lookback, args.recent_days, args.limit)
    write_cache(Path(args.db_path), args.cache_key, candidates)
    print(json.dumps({"count": len(candidates), "cache_key": args.cache_key}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
