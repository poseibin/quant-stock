"""批量策略评估。

用于把候选策略放到同一个样本窗口里横向比较：
- 收益 / 回撤 / 夏普 / Calmar / 换手
- 平均持仓数
- 平均市值与成交额暴露
- 与 small_cap_quality 的持仓重合度和收益相关性

默认会评估所有已注册策略，包括 disabled 的候选策略；是否进入实盘组合
由 desktop SQLite 配置中的 enabled 决定。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import BACKTEST_DIR
from common.config.desktop_settings import load_strategy_settings
from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from trading.backtest import BacktestConfig, CostModel, run as bt_run
from trading.strategy import registry

log = get_logger("evaluate_strategies")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--strategies", default="all", help="all / enabled / comma-separated names")
    parser.add_argument("--benchmark", default="000905.SH")
    parser.add_argument("--slippage", type=float, default=0.002)
    parser.add_argument("--baseline", default="small_cap_quality")
    parser.add_argument("--save", default=None, help="保存 run id；结果写入 SQLite strategy_evaluation 表")
    parser.add_argument("--append-save", action="store_true", help="追加保存单个策略结果，不清空同 run_id 已有记录")
    parser.add_argument("--db-path", default=None, help="SQLite 路径，默认 DESKTOP_DB_PATH 或 DATA_ROOT/meta.db")
    parser.add_argument("--export-files", action="store_true", help="额外导出 JSON/CSV 到 backtest_results/<save>/")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    names = _resolve_strategy_names(args.strategies)
    eval_names = list(names)
    if args.baseline not in eval_names:
        eval_names.append(args.baseline)
    results = evaluate(
        eval_names,
        args.start,
        args.end,
        benchmark=args.benchmark,
        slippage=args.slippage,
        baseline=args.baseline,
    )
    requested = set(names)
    results = [row for row in results if str(row.get("strategy") or "") in requested]

    payload = {
        "start": args.start,
        "end": args.end,
        "benchmark": args.benchmark,
        "baseline": args.baseline,
        "rows": results,
    }
    if args.save:
        db_path = _resolve_db_path(args.db_path)
        save_strategy_evaluation(db_path, args.save, payload, delete_existing=not args.append_save)
        log.info(f"策略评估结果已保存到 SQLite: {db_path} run_id={args.save}")
        if args.export_files:
            out_dir = BACKTEST_DIR / args.save
            out_dir.mkdir(parents=True, exist_ok=True)
            with (out_dir / "strategy_evaluation.json").open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, default=_json_default)
            pd.DataFrame(results).to_csv(out_dir / "strategy_evaluation.csv", index=False)
            log.info(f"策略评估导出文件已保存到 {out_dir}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    else:
        df = pd.DataFrame(results)
        if df.empty:
            print("No strategy produced holdings.")
        else:
            cols = [
                "strategy", "label", "enabled", "status", "admission", "admission_score", "reason", "total_return", "annual_return",
                "max_drawdown", "sharpe", "calmar", "avg_turnover", "avg_holdings",
                "avg_total_mv", "avg_amount", "monthly_win_rate", "worst_month_return",
                "overlap_with_baseline", "corr_with_baseline",
            ]
            print(df[[c for c in cols if c in df.columns]].to_string(index=False))


def evaluate(
    names: list[str],
    start: str,
    end: str,
    *,
    benchmark: str,
    slippage: float,
    baseline: str,
) -> list[dict[str, Any]]:
    settings = load_strategy_settings()
    rows: list[dict[str, Any]] = []
    returns_by_name: dict[str, pd.Series] = {}
    weights_by_name: dict[str, pd.DataFrame] = {}

    for name in names:
        row: dict[str, Any] = {
            "strategy": name,
            "label": registry.get_label(name),
            "enabled": bool(settings.get(name, {}).get("enabled", False)),
            "status": "ok",
        }
        try:
            strategy = registry.build(name)
            weights = strategy.generate_target_weights(start, end)
            if weights.empty:
                row["status"] = "empty"
                rows.append(row)
                continue
            cfg = BacktestConfig(
                start=start,
                end=end,
                cost=CostModel(slippage=slippage),
                benchmark=benchmark,
                progress=False,
            )
            result = bt_run(weights, cfg)
            row.update(result.summary)
            row.update(_weight_exposure(result.weights))
            row.update(_return_stability(result.returns))
            returns_by_name[name] = result.returns
            weights_by_name[name] = result.weights
        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)
        rows.append(row)

    if baseline in returns_by_name or baseline in weights_by_name:
        base_ret = returns_by_name.get(baseline)
        base_w = weights_by_name.get(baseline)
        for row in rows:
            name = row["strategy"]
            if row.get("status") != "ok" or name == baseline:
                continue
            if base_ret is not None and name in returns_by_name:
                row["corr_with_baseline"] = _return_corr(returns_by_name[name], base_ret)
            if base_w is not None and name in weights_by_name:
                row["overlap_with_baseline"] = _avg_weight_overlap(weights_by_name[name], base_w)

    for row in rows:
        row.update(_admission_decision(row, is_baseline=row.get("strategy") == baseline))

    return rows


def _resolve_strategy_names(arg: str) -> list[str]:
    names = registry.all_names()
    if arg == "all":
        return names
    if arg == "enabled":
        settings = load_strategy_settings()
        return [n for n in names if settings.get(n, {}).get("enabled", False)]
    wanted = [x.strip() for x in arg.split(",") if x.strip()]
    unknown = sorted(set(wanted) - set(names))
    if unknown:
        raise SystemExit(f"Unknown strategies: {unknown}; registered={names}")
    return wanted


def _weight_exposure(weights: pd.DataFrame) -> dict[str, float]:
    active = weights.where(weights > 1e-8, 0.0)
    if active.empty:
        return {"avg_holdings": 0.0, "avg_total_mv": 0.0, "avg_amount": 0.0}
    avg_holdings = float((active > 0).sum(axis=1).mean())
    long_rows = (
        active.stack()
        .rename("weight")
        .reset_index()
        .rename(columns={"level_0": "trade_date", "level_1": "ts_code"})
    )
    long_rows = long_rows[long_rows["weight"] > 1e-8]
    if long_rows.empty:
        return {"avg_holdings": avg_holdings, "avg_total_mv": 0.0, "avg_amount": 0.0}
    dates = sorted(long_rows["trade_date"].astype(str).unique())
    codes = sorted(long_rows["ts_code"].astype(str).unique())
    daily_basic = dq.sql(f"""
        SELECT trade_date, ts_code, total_mv * 10000 AS total_mv
        FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
        WHERE trade_date IN ({_quote(dates)})
          AND ts_code IN ({_quote(codes)})
    """)
    amount = dq.sql(f"""
        SELECT trade_date, ts_code, amount * 1000 AS amount
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date IN ({_quote(dates)})
          AND ts_code IN ({_quote(codes)})
    """)
    expo = long_rows.merge(daily_basic, on=["trade_date", "ts_code"], how="left")
    expo = expo.merge(amount, on=["trade_date", "ts_code"], how="left")
    return {
        "avg_holdings": avg_holdings,
        "avg_total_mv": _weighted_average(expo, "total_mv"),
        "avg_amount": _weighted_average(expo, "amount"),
    }


def _weighted_average(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    ok = df[col].notna() & df["weight"].notna()
    if not ok.any():
        return 0.0
    w = df.loc[ok, "weight"].astype(float)
    v = df.loc[ok, col].astype(float)
    denom = float(w.sum())
    return float((v * w).sum() / denom) if denom > 0 else 0.0


def _return_corr(left: pd.Series, right: pd.Series) -> float:
    idx = left.index.intersection(right.index)
    if len(idx) < 5:
        return 0.0
    corr = left.loc[idx].corr(right.loc[idx])
    return 0.0 if pd.isna(corr) else float(corr)


def _avg_weight_overlap(left: pd.DataFrame, right: pd.DataFrame) -> float:
    dates = left.index.intersection(right.index)
    if len(dates) == 0:
        return 0.0
    cols = left.columns.union(right.columns)
    l = left.reindex(index=dates, columns=cols, fill_value=0.0)
    r = right.reindex(index=dates, columns=cols, fill_value=0.0)
    overlap = pd.concat([l.stack(), r.stack()], axis=1).min(axis=1)
    by_date = overlap.groupby(level=0).sum()
    return float(by_date.mean()) if not by_date.empty else 0.0


def _return_stability(returns: pd.Series) -> dict[str, float | int]:
    if returns.empty:
        return {
            "month_count": 0,
            "monthly_win_rate": 0.0,
            "worst_month_return": 0.0,
            "positive_3m_rate": 0.0,
        }
    series = returns.copy()
    series.index = pd.to_datetime(series.index)
    monthly = (1.0 + series).resample("ME").prod() - 1.0
    monthly = monthly.dropna()
    if monthly.empty:
        return {
            "month_count": 0,
            "monthly_win_rate": 0.0,
            "worst_month_return": 0.0,
            "positive_3m_rate": 0.0,
        }
    rolling_3m = (1.0 + monthly).rolling(3).apply(lambda values: float(values.prod() - 1.0), raw=False).dropna()
    return {
        "month_count": int(len(monthly)),
        "monthly_win_rate": float((monthly > 0).mean()),
        "worst_month_return": float(monthly.min()),
        "positive_3m_rate": float((rolling_3m > 0).mean()) if not rolling_3m.empty else 0.0,
    }


def _admission_decision(row: dict[str, Any], *, is_baseline: bool) -> dict[str, Any]:
    if row.get("status") == "empty":
        return _admission_payload("继续观察", 20.0, {}, "样本期未生成持仓")
    if row.get("status") != "ok":
        return _admission_payload("暂不启用", 0.0, {}, str(row.get("error") or "评估失败"))

    annual_return = float(row.get("annual_return") or 0.0)
    max_drawdown = float(row.get("max_drawdown") or 0.0)
    sharpe = float(row.get("sharpe") or 0.0)
    calmar = float(row.get("calmar") or 0.0)
    turnover = float(row.get("avg_turnover") or 0.0)
    avg_amount = float(row.get("avg_amount") or 0.0)
    avg_total_mv = float(row.get("avg_total_mv") or 0.0)
    overlap = float(row.get("overlap_with_baseline") or 0.0)
    corr = float(row.get("corr_with_baseline") or 0.0)
    monthly_win_rate = float(row.get("monthly_win_rate") or 0.0)
    worst_month = float(row.get("worst_month_return") or 0.0)
    positive_3m_rate = float(row.get("positive_3m_rate") or 0.0)
    n_days = int(row.get("n_days") or 0)
    month_count = int(row.get("month_count") or 0)

    components = {
        "return_score": _linear_score(annual_return, -0.03, 0.22),
        "drawdown_score": _drawdown_score(max_drawdown),
        "risk_adjusted_score": 0.55 * _linear_score(sharpe, 0.0, 1.2) + 0.45 * _linear_score(calmar, 0.0, 1.5),
        "cost_score": _turnover_score(turnover),
        "capacity_score": _capacity_score(avg_amount, avg_total_mv),
        "stability_score": 0.45 * _linear_score(monthly_win_rate, 0.35, 0.68)
        + 0.35 * _linear_score(positive_3m_rate, 0.30, 0.78)
        + 0.20 * _drawdown_score(worst_month),
        "independence_score": 100.0 if is_baseline else 0.55 * _inverse_linear_score(corr, 0.45, 0.85)
        + 0.45 * _inverse_linear_score(overlap, 0.18, 0.48),
    }
    weights = {
        "return_score": 0.20,
        "drawdown_score": 0.18,
        "risk_adjusted_score": 0.22,
        "cost_score": 0.12,
        "capacity_score": 0.08,
        "stability_score": 0.12,
        "independence_score": 0.08,
    }
    score = sum(components[key] * weight for key, weight in weights.items())

    hard_reasons: list[str] = []
    if n_days and n_days < 120:
        hard_reasons.append("交易日样本不足")
    if month_count and month_count < 6:
        hard_reasons.append("月度样本不足")
    if annual_return <= 0:
        hard_reasons.append("年化收益未转正")
    if max_drawdown < -0.28:
        hard_reasons.append("最大回撤超过硬风控线")
    if sharpe < 0:
        hard_reasons.append("夏普为负")

    if hard_reasons:
        admission = "暂不启用"
    elif score >= 75:
        admission = "可启用"
    elif score >= 60:
        admission = "限制启用"
    elif score >= 42:
        admission = "继续观察"
    else:
        admission = "暂不启用"

    return _admission_payload(admission, score, components, _admission_reason(components, hard_reasons))


def _admission_payload(admission: str, score: float, components: dict[str, float], reason: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admission": admission,
        "admission_score": round(float(score), 2),
        "reason": reason,
    }
    for key, value in components.items():
        payload[key] = round(float(value), 2)
    return payload


def _admission_reason(components: dict[str, float], hard_reasons: list[str]) -> str:
    if hard_reasons:
        return "；".join(hard_reasons)
    ranked = sorted(components.items(), key=lambda item: item[1])
    strong = [f"{_score_label(key)}较好" for key, value in sorted(components.items(), key=lambda item: item[1], reverse=True)[:2] if value >= 75]
    weak = [f"{_score_label(key)}偏弱" for key, value in ranked[:2] if value < 65]
    parts = strong + weak
    return "；".join(parts) if parts else "收益、风险、成本、稳定性和组合独立性整体达标"


def _score_label(key: str) -> str:
    labels = {
        "return_score": "收益质量",
        "drawdown_score": "回撤控制",
        "risk_adjusted_score": "风险调整收益",
        "cost_score": "换手成本",
        "capacity_score": "容量",
        "stability_score": "稳定性",
        "independence_score": "组合独立性",
    }
    return labels.get(key, key)


def _linear_score(value: float, floor: float, cap: float) -> float:
    if cap <= floor:
        return 0.0
    return max(0.0, min(100.0, (value - floor) / (cap - floor) * 100.0))


def _inverse_linear_score(value: float, good: float, bad: float) -> float:
    if bad <= good:
        return 0.0
    return max(0.0, min(100.0, (bad - value) / (bad - good) * 100.0))


def _drawdown_score(value: float) -> float:
    drawdown = abs(min(value, 0.0))
    if drawdown <= 0.08:
        return 100.0
    if drawdown <= 0.18:
        return 60.0 + _inverse_linear_score(drawdown, 0.08, 0.18) * 0.35
    if drawdown <= 0.35:
        return _inverse_linear_score(drawdown, 0.18, 0.35) * 50.0
    return 0.0


def _turnover_score(turnover: float) -> float:
    if turnover <= 0.05:
        return 100.0
    if turnover <= 0.20:
        return 65.0 + _inverse_linear_score(turnover, 0.05, 0.20) * 0.35
    if turnover <= 0.50:
        return _inverse_linear_score(turnover, 0.20, 0.50) * 55.0
    return 0.0


def _capacity_score(avg_amount: float, avg_total_mv: float) -> float:
    amount_score = 55.0 if avg_amount <= 0 else _linear_score(avg_amount, 50_000_000, 600_000_000)
    mv_score = 55.0 if avg_total_mv <= 0 else _linear_score(avg_total_mv, 3_000_000_000, 20_000_000_000)
    return 0.65 * amount_score + 0.35 * mv_score


def _quote(items: list[str]) -> str:
    return ",".join(f"'{x}'" for x in items)


def _resolve_db_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env = os.getenv("DESKTOP_DB_PATH", "").strip() or os.getenv("DESKTOP_CONFIG_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    data_root = os.getenv("DATA_ROOT", "").strip()
    if data_root:
        return (Path(data_root).expanduser().resolve() / "meta.db")
    return (ROOT.parent / "data_store" / "meta.db").resolve()


def save_strategy_evaluation(db_path: Path, run_id: str, payload: dict[str, Any], *, delete_existing: bool = True) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = pd.Timestamp.now().isoformat()
    start = str(payload.get("start") or "")
    end = str(payload.get("end") or "")
    benchmark = str(payload.get("benchmark") or "")
    baseline = str(payload.get("baseline") or "")
    rows = list(payload.get("rows") or [])
    with sqlite3.connect(str(db_path), timeout=30.0) as conn:
        _ensure_strategy_evaluation_table(conn)
        if delete_existing:
            conn.execute("DELETE FROM strategy_evaluation WHERE run_id = ?", (run_id,))
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_payload = json.dumps(row, ensure_ascii=False, default=_json_default)
            columns = [
                "run_id", "strategy", "label", "enabled", "status", "admission", "admission_score", "reason",
                "start_date", "end_date", "benchmark", "baseline",
                "total_return", "annual_return", "annual_volatility", "sharpe", "max_drawdown",
                "calmar", "win_rate", "n_days", "month_count", "monthly_win_rate", "worst_month_return",
                "positive_3m_rate", "avg_turnover", "avg_holdings", "avg_total_mv", "avg_amount",
                "overlap_with_baseline", "corr_with_baseline", "return_score", "drawdown_score",
                "risk_adjusted_score", "cost_score", "capacity_score", "stability_score",
                "independence_score", "error", "generated_at", "payload_json", "created_at", "updated_at",
            ]
            values = [
                run_id,
                str(row.get("strategy") or ""),
                str(row.get("label") or ""),
                1 if bool(row.get("enabled")) else 0,
                str(row.get("status") or ""),
                str(row.get("admission") or ""),
                _float_or_none(row.get("admission_score")),
                str(row.get("reason") or ""),
                start,
                end,
                benchmark,
                baseline,
                _float_or_none(row.get("total_return")),
                _float_or_none(row.get("annual_return")),
                _float_or_none(row.get("annual_volatility")),
                _float_or_none(row.get("sharpe")),
                _float_or_none(row.get("max_drawdown")),
                _float_or_none(row.get("calmar")),
                _float_or_none(row.get("win_rate")),
                _int_or_none(row.get("n_days")),
                _int_or_none(row.get("month_count")),
                _float_or_none(row.get("monthly_win_rate")),
                _float_or_none(row.get("worst_month_return")),
                _float_or_none(row.get("positive_3m_rate")),
                _float_or_none(row.get("avg_turnover")),
                _float_or_none(row.get("avg_holdings")),
                _float_or_none(row.get("avg_total_mv")),
                _float_or_none(row.get("avg_amount")),
                _float_or_none(row.get("overlap_with_baseline")),
                _float_or_none(row.get("corr_with_baseline")),
                _float_or_none(row.get("return_score")),
                _float_or_none(row.get("drawdown_score")),
                _float_or_none(row.get("risk_adjusted_score")),
                _float_or_none(row.get("cost_score")),
                _float_or_none(row.get("capacity_score")),
                _float_or_none(row.get("stability_score")),
                _float_or_none(row.get("independence_score")),
                str(row.get("error") or ""),
                generated_at,
                row_payload,
                pd.Timestamp.now().isoformat(),
                pd.Timestamp.now().isoformat(),
            ]
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT OR REPLACE INTO strategy_evaluation ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )


def _ensure_strategy_evaluation_table(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'strategy_evaluation'"
    ).fetchone()
    if existing:
        cols = {
            str(row[1]).lower()
            for row in conn.execute("PRAGMA table_info(strategy_evaluation)").fetchall()
        }
        if "run_id" not in cols:
            conn.execute("ALTER TABLE strategy_evaluation RENAME TO strategy_evaluation_legacy")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_evaluation (
            run_id TEXT NOT NULL,
            strategy TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '',
            admission TEXT NOT NULL DEFAULT '',
            admission_score REAL,
            reason TEXT NOT NULL DEFAULT '',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            benchmark TEXT NOT NULL DEFAULT '',
            baseline TEXT NOT NULL DEFAULT '',
            total_return REAL,
            annual_return REAL,
            annual_volatility REAL,
            sharpe REAL,
            max_drawdown REAL,
            calmar REAL,
            win_rate REAL,
            n_days INTEGER,
            month_count INTEGER,
            monthly_win_rate REAL,
            worst_month_return REAL,
            positive_3m_rate REAL,
            avg_turnover REAL,
            avg_holdings REAL,
            avg_total_mv REAL,
            avg_amount REAL,
            overlap_with_baseline REAL,
            corr_with_baseline REAL,
            return_score REAL,
            drawdown_score REAL,
            risk_adjusted_score REAL,
            cost_score REAL,
            capacity_score REAL,
            stability_score REAL,
            independence_score REAL,
            error TEXT NOT NULL DEFAULT '',
            generated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(run_id, strategy)
        )
        """
    )
    _ensure_columns(
        conn,
        "strategy_evaluation",
        {
            "admission_score": "REAL",
            "month_count": "INTEGER",
            "monthly_win_rate": "REAL",
            "worst_month_return": "REAL",
            "positive_3m_rate": "REAL",
            "return_score": "REAL",
            "drawdown_score": "REAL",
            "risk_adjusted_score": "REAL",
            "cost_score": "REAL",
            "capacity_score": "REAL",
            "stability_score": "REAL",
            "independence_score": "REAL",
        },
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_run ON strategy_evaluation(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_strategy ON strategy_evaluation(strategy)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_admission ON strategy_evaluation(admission)")


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        str(row[1]).lower()
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl in columns.items():
        if name.lower() not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
