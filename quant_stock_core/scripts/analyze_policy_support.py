from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import upsert_sql, write_transaction


TASK_NAME = "policy_support_analysis"
WEIGHT_INDUSTRIES = ("银行", "证券", "保险", "多元金融", "全国地产", "电信运营", "石油", "煤炭", "电力", "运输")
POLICY_INDUSTRIES = ("银行", "证券", "保险", "电信运营", "石油", "煤炭", "电力", "运输", "建筑", "钢铁", "央企")


@dataclass
class Signal:
    trade_date: str
    signal_level: str
    total_score: float
    market_stress_score: float
    support_score: float
    institution_score: float
    weight_support_score: float
    direction: str
    reason: str
    evidence_json: str


@dataclass
class Candidate:
    trade_date: str
    ts_code: str
    name: str
    industry: str
    candidate_type: str
    score: float
    pct_chg: float
    amount_ratio: float
    turnover_rate: float
    institution_net_buy: float
    reason: str


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


def parquet_expr(data_root: Path, dataset: str) -> str:
    dataset_dir = data_root / "raw" / dataset
    files = sorted(dataset_dir.glob("*.parquet"))
    if not files:
        raise RuntimeError(f"缺少 {dataset} 数据，请先在数据管理更新 {dataset}")
    return str(dataset_dir / "*.parquet")


def read_tables(data_root: Path, lookback: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run_status.progress(TASK_NAME, 1, 5, "read", "读取行情数据")
    daily_path = parquet_expr(data_root, "daily")
    stock_path = parquet_expr(data_root, "stock_basic")
    basic_path = parquet_expr(data_root, "daily_basic")
    top_inst_dir = data_root / "raw" / "top_inst"
    top_inst_path = str(top_inst_dir / "*.parquet") if list(top_inst_dir.glob("*.parquet")) else ""
    con = duckdb.connect(":memory:")
    try:
        dates = con.execute(f"""
            SELECT DISTINCT CAST(trade_date AS VARCHAR) AS trade_date
            FROM read_parquet('{daily_path}')
            ORDER BY trade_date DESC
            LIMIT {int(lookback)}
        """).fetchdf()["trade_date"].astype(str).tolist()
        if not dates:
            raise RuntimeError("daily 数据为空")
        min_date = min(dates)
        daily = con.execute(f"""
            SELECT
                d.ts_code,
                CAST(d.trade_date AS VARCHAR) AS trade_date,
                CAST(d.open AS DOUBLE) AS open,
                CAST(d.high AS DOUBLE) AS high,
                CAST(d.low AS DOUBLE) AS low,
                CAST(d.close AS DOUBLE) AS close,
                CAST(d.pre_close AS DOUBLE) AS pre_close,
                CAST(d.pct_chg AS DOUBLE) AS pct_chg,
                CAST(d.amount AS DOUBLE) AS amount,
                COALESCE(s.name, '') AS name,
                COALESCE(s.industry, '') AS industry,
                COALESCE(s.market, '') AS market,
                COALESCE(s.list_status, '') AS list_status,
                COALESCE(CAST(b.turnover_rate AS DOUBLE), 0) AS turnover_rate,
                COALESCE(CAST(b.total_mv AS DOUBLE), 0) AS total_mv,
                COALESCE(CAST(b.circ_mv AS DOUBLE), 0) AS circ_mv
            FROM read_parquet('{daily_path}') d
            LEFT JOIN read_parquet('{stock_path}') s ON d.ts_code = s.ts_code
            LEFT JOIN read_parquet('{basic_path}') b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE CAST(d.trade_date AS VARCHAR) >= '{min_date}'
              AND COALESCE(s.list_status, 'L') = 'L'
              AND COALESCE(s.name, '') NOT LIKE '%ST%'
        """).fetchdf()
        top_inst = pd.DataFrame()
        if top_inst_path:
            top_inst = con.execute(f"""
                SELECT
                    ts_code,
                    CAST(trade_date AS VARCHAR) AS trade_date,
                    COALESCE(SUM(CAST(net_buy AS DOUBLE)), 0) AS institution_net_buy
                FROM read_parquet('{top_inst_path}')
                WHERE CAST(trade_date AS VARCHAR) >= '{min_date}'
                GROUP BY ts_code, trade_date
            """).fetchdf()
        return daily, top_inst, pd.DataFrame({"trade_date": dates})
    finally:
        con.close()


def latest_metrics(daily: pd.DataFrame, top_inst: pd.DataFrame) -> tuple[Signal, list[Candidate]]:
    run_status.progress(TASK_NAME, 2, 5, "score", "计算市场压力和承接")
    daily = daily.copy()
    daily["trade_date"] = daily["trade_date"].astype(str)
    latest_date = str(daily["trade_date"].max())
    today = daily[daily["trade_date"] == latest_date].copy()
    if today.empty:
        raise RuntimeError("未找到最新交易日行情")
    today["amount"] = today["amount"].map(safe_float)
    today["pct_chg"] = today["pct_chg"].map(safe_float)
    today["total_mv"] = today["total_mv"].map(safe_float)
    daily = daily.sort_values(["ts_code", "trade_date"])
    daily["amount_ma20"] = daily.groupby("ts_code")["amount"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean())
    daily["close_ma20"] = daily.groupby("ts_code")["close"].transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean())
    latest = daily[daily["trade_date"] == latest_date].copy()
    latest["amount_ratio"] = latest.apply(lambda r: safe_float(r["amount"]) / max(safe_float(r["amount_ma20"]), 1.0), axis=1)
    latest["recover_ratio"] = latest.apply(lambda r: (safe_float(r["close"]) - safe_float(r["low"])) / max(safe_float(r["high"]) - safe_float(r["low"]), 0.01), axis=1)
    latest["near_ma20"] = latest.apply(lambda r: safe_float(r["close"]) / max(safe_float(r["close_ma20"]), 0.01) - 1, axis=1)

    weighted = latest.sort_values("total_mv", ascending=False).head(300)
    market_drop = -safe_float((latest["pct_chg"] < 0).mean()) * 100
    avg_pct = safe_float(latest["pct_chg"].mean())
    weak_ratio = safe_float((latest["pct_chg"] <= -2).mean())
    market_stress_score = clamp((-avg_pct) * 18 + weak_ratio * 50 + max(0, -market_drop - 50) * 0.25)

    weighted_avg = safe_float(weighted["pct_chg"].mean())
    all_avg = safe_float(latest["pct_chg"].mean())
    weight_support_score = clamp((weighted_avg - all_avg + 1.2) * 24)
    recover_score = clamp(safe_float((latest["recover_ratio"] > 0.65).mean()) * 100)
    volume_hold_score = clamp(safe_float(((latest["amount_ratio"] > 1.5) & (latest["pct_chg"] > -1.2)).mean()) * 130)
    support_score = clamp(recover_score * 0.45 + volume_hold_score * 0.35 + weight_support_score * 0.20)

    institution_score = 0.0
    inst_map: dict[tuple[str, str], float] = {}
    if not top_inst.empty:
        run_status.progress(TASK_NAME, 3, 5, "score", "计算机构席位痕迹")
        top_inst["institution_net_buy"] = top_inst["institution_net_buy"].map(safe_float)
        recent_dates = sorted(daily["trade_date"].unique())[-5:]
        inst_recent = top_inst[top_inst["trade_date"].isin(recent_dates)]
        pos_count = int((inst_recent["institution_net_buy"] > 0).sum()) if not inst_recent.empty else 0
        net_buy = safe_float(inst_recent["institution_net_buy"].sum()) if not inst_recent.empty else 0.0
        institution_score = clamp(pos_count * 8 + max(0.0, net_buy) / 100_000_000 * 5)
        inst_map = {(str(r.ts_code), str(r.trade_date)): safe_float(r.institution_net_buy) for r in top_inst.itertuples(index=False)}

    total_score = clamp(market_stress_score * 0.32 + support_score * 0.35 + institution_score * 0.18 + weight_support_score * 0.15)
    if total_score >= 70:
        level = "high"
    elif total_score >= 45:
        level = "medium"
    else:
        level = "low"

    direction = infer_direction(latest)
    reasons = [
        f"市场平均涨跌幅 {all_avg:.2f}%",
        f"权重股相对全市场 {weighted_avg - all_avg:+.2f}pct",
        f"强承接股票占比 {safe_float((latest['recover_ratio'] > 0.65).mean()) * 100:.1f}%",
    ]
    if institution_score > 0:
        reasons.append(f"近5日龙虎榜机构痕迹分 {institution_score:.1f}")
    evidence = {
        "latest_date": latest_date,
        "avg_pct": all_avg,
        "weighted_avg_pct": weighted_avg,
        "weak_ratio": weak_ratio,
        "recover_ratio": safe_float((latest["recover_ratio"] > 0.65).mean()),
        "volume_hold_ratio": safe_float(((latest["amount_ratio"] > 1.5) & (latest["pct_chg"] > -1.2)).mean()),
    }
    signal = Signal(
        trade_date=latest_date,
        signal_level=level,
        total_score=round(total_score, 2),
        market_stress_score=round(market_stress_score, 2),
        support_score=round(support_score, 2),
        institution_score=round(institution_score, 2),
        weight_support_score=round(weight_support_score, 2),
        direction=direction,
        reason="；".join(reasons),
        evidence_json=json.dumps(evidence, ensure_ascii=False),
    )

    candidates = score_candidates(latest, inst_map, latest_date)
    return signal, candidates


def infer_direction(latest: pd.DataFrame) -> str:
    industry_scores: list[tuple[str, float]] = []
    for industry, group in latest.groupby("industry"):
        name = str(industry or "").strip()
        if not name:
            continue
        if not any(key in name for key in POLICY_INDUSTRIES):
            continue
        score = safe_float(group["pct_chg"].mean()) + safe_float((group["amount_ratio"] > 1.3).mean()) * 2
        industry_scores.append((name, score))
    industry_scores.sort(key=lambda x: x[1], reverse=True)
    top = [name for name, _ in industry_scores[:3]]
    if top:
        return " / ".join(top)
    return "宽基ETF / 沪深300权重"


def score_candidates(latest: pd.DataFrame, inst_map: dict[tuple[str, str], float], latest_date: str) -> list[Candidate]:
    out: list[Candidate] = []
    for row in latest.itertuples(index=False):
        name = str(getattr(row, "name", "") or "")
        industry = str(getattr(row, "industry", "") or "")
        ts_code = str(getattr(row, "ts_code", "") or "")
        pct = safe_float(getattr(row, "pct_chg", 0))
        amount_ratio = safe_float(getattr(row, "amount_ratio", 0))
        recover_ratio = safe_float(getattr(row, "recover_ratio", 0))
        total_mv = safe_float(getattr(row, "total_mv", 0))
        turnover = safe_float(getattr(row, "turnover_rate", 0))
        inst_buy = inst_map.get((ts_code, latest_date), 0.0)
        is_policy_industry = any(key in industry for key in POLICY_INDUSTRIES)
        is_weight = total_mv >= 600_0000
        if not is_policy_industry and not is_weight and inst_buy <= 0:
            continue
        score = 0.0
        score += clamp((pct + 2.0) * 12, 0, 35)
        score += clamp((amount_ratio - 1.0) * 18, 0, 25)
        score += clamp(recover_ratio * 20, 0, 20)
        score += 10 if is_policy_industry else 0
        score += 8 if is_weight else 0
        score += clamp(inst_buy / 50_000_000 * 8, 0, 18)
        if score < 45:
            continue
        reason_bits = []
        if pct > 0:
            reason_bits.append(f"逆势/强势 {pct:.2f}%")
        if amount_ratio >= 1.5:
            reason_bits.append(f"成交额放大 {amount_ratio:.1f}x")
        if recover_ratio >= 0.65:
            reason_bits.append("日内收回跌幅")
        if is_policy_industry:
            reason_bits.append("政策资金偏好行业")
        if inst_buy > 0:
            reason_bits.append(f"机构净买 {inst_buy / 10000:.0f}万")
        candidate_type = "权重承接" if is_weight else "政策行业"
        if inst_buy > 0:
            candidate_type = "机构确认"
        out.append(Candidate(
            trade_date=latest_date,
            ts_code=ts_code,
            name=name,
            industry=industry,
            candidate_type=candidate_type,
            score=round(clamp(score), 2),
            pct_chg=round(pct, 2),
            amount_ratio=round(amount_ratio, 2),
            turnover_rate=round(turnover, 2),
            institution_net_buy=round(inst_buy, 2),
            reason="；".join(reason_bits),
        ))
    out.sort(key=lambda item: item.score, reverse=True)
    return out[:80]


def ensure_tables(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_policy_support_signals (
            trade_date TEXT PRIMARY KEY,
            signal_level TEXT NOT NULL,
            total_score REAL NOT NULL DEFAULT 0,
            market_stress_score REAL NOT NULL DEFAULT 0,
            support_score REAL NOT NULL DEFAULT 0,
            institution_score REAL NOT NULL DEFAULT 0,
            weight_support_score REAL NOT NULL DEFAULT 0,
            direction TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_policy_support_candidates (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            candidate_type TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL DEFAULT 0,
            pct_chg REAL NOT NULL DEFAULT 0,
            amount_ratio REAL NOT NULL DEFAULT 0,
            turnover_rate REAL NOT NULL DEFAULT 0,
            institution_net_buy REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(trade_date, ts_code)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_policy_support_candidates_score ON monitor_policy_support_candidates(trade_date, score DESC)")


def write_results(signal: Signal, candidates: list[Candidate]) -> None:
    run_status.progress(TASK_NAME, 4, 5, "write", "写入数据库")
    updated_at = now()
    with write_transaction(None) as conn:
        ensure_tables(conn)
        signal_columns = [
            "trade_date", "signal_level", "total_score", "market_stress_score", "support_score",
            "institution_score", "weight_support_score", "direction", "reason", "evidence_json", "updated_at",
        ]
        conn.execute(
            upsert_sql(
                "monitor_policy_support_signals",
                signal_columns,
                ["trade_date"],
                [
                    "signal_level", "total_score", "market_stress_score", "support_score",
                    "institution_score", "weight_support_score", "direction", "reason",
                    "evidence_json", "updated_at",
                ],
            ),
            (
                signal.trade_date,
                signal.signal_level,
                signal.total_score,
                signal.market_stress_score,
                signal.support_score,
                signal.institution_score,
                signal.weight_support_score,
                signal.direction,
                signal.reason,
                signal.evidence_json,
                updated_at,
            ),
        )
        conn.execute("DELETE FROM monitor_policy_support_candidates WHERE trade_date = ?", (signal.trade_date,))
        for item in candidates:
            conn.execute(
                """
                INSERT INTO monitor_policy_support_candidates(
                    trade_date, ts_code, name, industry, candidate_type, score, pct_chg,
                    amount_ratio, turnover_rate, institution_net_buy, reason, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    item.trade_date,
                    item.ts_code,
                    item.name,
                    item.industry,
                    item.candidate_type,
                    item.score,
                    item.pct_chg,
                    item.amount_ratio,
                    item.turnover_rate,
                    item.institution_net_buy,
                    item.reason,
                    updated_at,
                ),
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="")
    parser.add_argument("--lookback", type=int, default=80)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    data_root = Path(args.data_root).expanduser().resolve() if args.data_root else Path.cwd().parent / "data_store"
    try:
        run_status.begin(TASK_NAME)
        daily, top_inst, _ = read_tables(data_root, max(40, args.lookback))
        signal, candidates = latest_metrics(daily, top_inst)
        write_results(signal, candidates)
        run_status.progress(TASK_NAME, 5, 5, "done", f"{signal.signal_level} {signal.total_score}")
        run_status.done(TASK_NAME, f"{signal.trade_date} {signal.signal_level} {signal.total_score}")
        if args.json:
            print(json.dumps({"signal": asdict(signal), "candidates": [asdict(c) for c in candidates]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
