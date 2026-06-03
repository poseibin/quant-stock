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
    parser.add_argument("--db-path", default=None, help="SQLite 路径，默认 DESKTOP_DB_PATH 或 DATA_ROOT/meta.db")
    parser.add_argument("--export-files", action="store_true", help="额外导出 JSON/CSV 到 backtest_results/<save>/")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    names = _resolve_strategy_names(args.strategies)
    results = evaluate(
        names,
        args.start,
        args.end,
        benchmark=args.benchmark,
        slippage=args.slippage,
        baseline=args.baseline,
    )

    payload = {
        "start": args.start,
        "end": args.end,
        "benchmark": args.benchmark,
        "baseline": args.baseline,
        "rows": results,
    }
    if args.save:
        db_path = _resolve_db_path(args.db_path)
        save_strategy_evaluation(db_path, args.save, payload)
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
                "strategy", "label", "enabled", "status", "admission", "reason", "total_return", "annual_return",
                "max_drawdown", "sharpe", "calmar", "avg_turnover", "avg_holdings",
                "avg_total_mv", "avg_amount", "overlap_with_baseline", "corr_with_baseline",
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


def _admission_decision(row: dict[str, Any], *, is_baseline: bool) -> dict[str, str]:
    if row.get("status") == "empty":
        return {"admission": "继续观察", "reason": "样本期未生成持仓"}
    if row.get("status") != "ok":
        return {"admission": "暂不启用", "reason": str(row.get("error") or "评估失败")}

    annual_return = float(row.get("annual_return") or 0.0)
    max_drawdown = float(row.get("max_drawdown") or 0.0)
    sharpe = float(row.get("sharpe") or 0.0)
    calmar = float(row.get("calmar") or 0.0)
    turnover = float(row.get("avg_turnover") or 0.0)
    overlap = float(row.get("overlap_with_baseline") or 0.0)
    corr = float(row.get("corr_with_baseline") or 0.0)

    if annual_return <= 0 or max_drawdown < -0.18:
        return {"admission": "暂不启用", "reason": "收益或回撤未达准入线"}
    if turnover > 0.20:
        return {"admission": "继续观察", "reason": "换手偏高，需验证成本敏感性"}
    if not is_baseline and (overlap > 0.35 or corr > 0.75):
        return {"admission": "继续观察", "reason": "与基准策略相关性偏高"}
    if sharpe >= 0.6 and calmar >= 0.8:
        return {"admission": "可启用", "reason": "收益回撤和独立性达标"}
    return {"admission": "继续观察", "reason": "表现为正，但需更多窗口验证"}


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


def save_strategy_evaluation(db_path: Path, run_id: str, payload: dict[str, Any]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = pd.Timestamp.now().isoformat()
    start = str(payload.get("start") or "")
    end = str(payload.get("end") or "")
    benchmark = str(payload.get("benchmark") or "")
    baseline = str(payload.get("baseline") or "")
    rows = list(payload.get("rows") or [])
    with sqlite3.connect(str(db_path), timeout=30.0) as conn:
        _ensure_strategy_evaluation_table(conn)
        conn.execute("DELETE FROM strategy_evaluation WHERE run_id = ?", (run_id,))
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_payload = json.dumps(row, ensure_ascii=False, default=_json_default)
            conn.execute(
                """
                INSERT INTO strategy_evaluation (
                    run_id, strategy, label, enabled, status, admission, reason,
                    start_date, end_date, benchmark, baseline,
                    total_return, annual_return, annual_volatility, sharpe, max_drawdown,
                    calmar, win_rate, n_days, avg_turnover, avg_holdings, avg_total_mv,
                    avg_amount, overlap_with_baseline, corr_with_baseline, error,
                    generated_at, payload_json, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, datetime('now'), datetime('now')
                )
                """,
                (
                    run_id,
                    str(row.get("strategy") or ""),
                    str(row.get("label") or ""),
                    1 if bool(row.get("enabled")) else 0,
                    str(row.get("status") or ""),
                    str(row.get("admission") or ""),
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
                    _float_or_none(row.get("avg_turnover")),
                    _float_or_none(row.get("avg_holdings")),
                    _float_or_none(row.get("avg_total_mv")),
                    _float_or_none(row.get("avg_amount")),
                    _float_or_none(row.get("overlap_with_baseline")),
                    _float_or_none(row.get("corr_with_baseline")),
                    str(row.get("error") or ""),
                    generated_at,
                    row_payload,
                ),
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
            avg_turnover REAL,
            avg_holdings REAL,
            avg_total_mv REAL,
            avg_amount REAL,
            overlap_with_baseline REAL,
            corr_with_baseline REAL,
            error TEXT NOT NULL DEFAULT '',
            generated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(run_id, strategy)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_run ON strategy_evaluation(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_strategy ON strategy_evaluation(strategy)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_admission ON strategy_evaluation(admission)")


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
