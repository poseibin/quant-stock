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
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config.desktop_settings import load_strategy_settings
from common.infra.db import add_column, db_backend, replace_sql, table_columns, table_exists, write_transaction
from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from trading.backtest import BacktestConfig, CostModel, run as bt_run
from trading.backtest.metrics import summary as metric_summary
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
    parser.add_argument("--save", default=None, help="保存 run id；结果写入 SQLite eval_strategy_admission 表")
    parser.add_argument("--append-save", action="store_true", help="追加保存单个策略结果，不清空同 run_id 已有记录")
    parser.add_argument("--db-path", default=None, help="SQLite 路径，默认 DESKTOP_DB_PATH 或 DATA_ROOT/meta.db")
    parser.add_argument("--strategy-version-mode", choices=["active", "latest"], default="latest", help="策略参数版本：评估默认 latest，实盘推股默认 active")
    parser.add_argument("--strategy-version-json", default="{}", help="指定策略版本，如 {\"small_cap_quality\": 3}")
    parser.add_argument("--export-files", action="store_true", help="额外导出 JSON/CSV 到 backtest_results/<save>/")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    os.environ["QUANT_STRATEGY_VERSION_MODE"] = args.strategy_version_mode
    os.environ["QUANT_STRATEGY_VERSION_JSON"] = args.strategy_version_json

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
        save_eval_strategy_admission(db_path, args.save, payload, delete_existing=not args.append_save)
        log.info(f"策略评估结果已保存到 {db_backend()}: {db_path} run_id={args.save}")
        if args.export_files:
            log.info("--export-files 已废弃：策略评估结果统一写入 SQLite，不再导出 JSON/CSV")

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
            "strategy_version": settings.get(name, {}).get("_version"),
            "strategy_version_mode": settings.get(name, {}).get("_version_mode"),
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
            row.update(_effective_period_metrics(result))
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


def _effective_period_metrics(result) -> dict[str, Any]:
    weights = result.weights
    returns = result.returns
    if weights.empty or returns.empty:
        return {}
    active_mask = weights.where(weights > 1e-8, 0.0).sum(axis=1) > 1e-8
    if not active_mask.any():
        return {}
    active_start = str(active_mask[active_mask].index[0])
    active_end = str(active_mask[active_mask].index[-1])
    effective_returns = returns.loc[active_start:active_end]
    effective_weights = weights.loc[active_start:active_end]
    if effective_returns.empty:
        return {}
    full_summary = {f"full_{key}": value for key, value in result.summary.items()}
    benchmark = result.benchmark.loc[effective_returns.index.intersection(result.benchmark.index)] if result.benchmark is not None else None
    effective_summary = metric_summary(effective_returns, weights=effective_weights, benchmark=benchmark)
    full_summary.update(effective_summary)
    full_summary["effective_start"] = active_start
    full_summary["effective_end"] = active_end
    full_summary["effective_n_days"] = int(len(effective_returns))
    return full_summary


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
    active_days = active.sum(axis=1) > 1e-8
    if active_days.any():
        active = active.loc[active_days[active_days].index[0]:active_days[active_days].index[-1]]
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
    nonzero = series.abs() > 1e-12
    if nonzero.any():
        series = series.loc[nonzero[nonzero].index[0]:nonzero[nonzero].index[-1]]
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
    # Strategy admission is the research funnel into walk-forward testing, not
    # final live approval. Keep drawdown visible, but do not let a naked
    # long-only stress test veto every potentially useful alpha sleeve.
    weights = {
        "return_score": 0.30,
        "drawdown_score": 0.05,
        "risk_adjusted_score": 0.15,
        "cost_score": 0.12,
        "capacity_score": 0.06,
        "stability_score": 0.20,
        "independence_score": 0.12,
    }
    score = sum(components[key] * weight for key, weight in weights.items())

    caution_reasons: list[str] = []
    reject_reasons: list[str] = []
    if n_days and n_days < 120:
        caution_reasons.append("交易日样本不足")
    if month_count and month_count < 6:
        caution_reasons.append("月度样本不足")
    if annual_return <= 0:
        reject_reasons.append("年化收益未转正")
    if max_drawdown < -0.28:
        caution_reasons.append("裸策略回撤超过实盘线")
    if sharpe < 0:
        reject_reasons.append("夏普为负")

    if annual_return <= 0 and sharpe < 0:
        admission = "暂不启用"
    elif caution_reasons and score >= 55 and annual_return >= 0.06 and sharpe >= 0.25:
        admission = "限制启用"
    elif caution_reasons and score >= 38 and annual_return > 0:
        admission = "继续观察"
    elif reject_reasons:
        admission = "暂不启用"
    elif score >= 75:
        admission = "可启用"
    elif score >= 60:
        admission = "限制启用"
    elif score >= 42:
        admission = "继续观察"
    else:
        admission = "暂不启用"

    return _admission_payload(admission, score, components, _admission_reason(components, reject_reasons + caution_reasons))


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
        return _inverse_linear_score(drawdown, 0.18, 0.35) * 0.50
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


def save_eval_strategy_admission(db_path: Path, run_id: str, payload: dict[str, Any], *, delete_existing: bool = True) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = pd.Timestamp.now().isoformat()
    start = str(payload.get("start") or "")
    end = str(payload.get("end") or "")
    benchmark = str(payload.get("benchmark") or "")
    baseline = str(payload.get("baseline") or "")
    rows = list(payload.get("rows") or [])
    with write_transaction(db_path) as conn:
        _ensure_eval_strategy_admission_table(conn)
        if delete_existing:
            conn.execute("DELETE FROM eval_strategy_admission WHERE run_id = ?", (run_id,))
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
                "effective_start", "effective_end", "effective_n_days",
                "full_total_return", "full_annual_return", "full_annual_volatility", "full_sharpe",
                "full_max_drawdown", "full_calmar", "full_win_rate", "full_n_days", "full_avg_turnover",
                "overlap_with_baseline", "corr_with_baseline", "return_score", "drawdown_score",
                "risk_adjusted_score", "cost_score", "capacity_score", "stability_score",
                "independence_score", "strategy_version", "strategy_version_mode",
                "error", "generated_at", "payload_json", "created_at", "updated_at",
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
                str(row.get("effective_start") or ""),
                str(row.get("effective_end") or ""),
                _int_or_none(row.get("effective_n_days")),
                _float_or_none(row.get("full_total_return")),
                _float_or_none(row.get("full_annual_return")),
                _float_or_none(row.get("full_annual_volatility")),
                _float_or_none(row.get("full_sharpe")),
                _float_or_none(row.get("full_max_drawdown")),
                _float_or_none(row.get("full_calmar")),
                _float_or_none(row.get("full_win_rate")),
                _int_or_none(row.get("full_n_days")),
                _float_or_none(row.get("full_avg_turnover")),
                _float_or_none(row.get("overlap_with_baseline")),
                _float_or_none(row.get("corr_with_baseline")),
                _float_or_none(row.get("return_score")),
                _float_or_none(row.get("drawdown_score")),
                _float_or_none(row.get("risk_adjusted_score")),
                _float_or_none(row.get("cost_score")),
                _float_or_none(row.get("capacity_score")),
                _float_or_none(row.get("stability_score")),
                _float_or_none(row.get("independence_score")),
                _int_or_none(row.get("strategy_version")),
                str(row.get("strategy_version_mode") or ""),
                str(row.get("error") or ""),
                generated_at,
                row_payload,
                pd.Timestamp.now().isoformat(),
                pd.Timestamp.now().isoformat(),
            ]
            conn.execute(
                replace_sql("eval_strategy_admission", columns, ["run_id", "strategy"]),
                values,
            )


def _ensure_eval_strategy_admission_table(conn) -> None:
    if table_exists(conn, "eval_strategy_admission"):
        cols = table_columns(conn, "eval_strategy_admission")
        if "run_id" not in cols:
            if conn.backend == "mysql":
                conn.execute("RENAME TABLE eval_strategy_admission TO eval_strategy_admission_legacy")
            else:
                conn.execute("ALTER TABLE eval_strategy_admission RENAME TO eval_strategy_admission_legacy")
    if conn.backend == "mysql":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_strategy_admission (
                run_id VARCHAR(255) NOT NULL,
                strategy VARCHAR(255) NOT NULL,
                label VARCHAR(255) NOT NULL DEFAULT '',
                enabled BIGINT NOT NULL DEFAULT 0,
                status VARCHAR(255) NOT NULL DEFAULT '',
                admission VARCHAR(255) NOT NULL DEFAULT '',
                admission_score DOUBLE,
                reason LONGTEXT NOT NULL,
                start_date VARCHAR(64) NOT NULL,
                end_date VARCHAR(64) NOT NULL,
                benchmark VARCHAR(255) NOT NULL DEFAULT '',
                baseline VARCHAR(255) NOT NULL DEFAULT '',
                total_return DOUBLE,
                annual_return DOUBLE,
                annual_volatility DOUBLE,
                sharpe DOUBLE,
                max_drawdown DOUBLE,
                calmar DOUBLE,
                win_rate DOUBLE,
                n_days BIGINT,
                month_count BIGINT,
                monthly_win_rate DOUBLE,
                worst_month_return DOUBLE,
                positive_3m_rate DOUBLE,
                avg_turnover DOUBLE,
                avg_holdings DOUBLE,
                avg_total_mv DOUBLE,
                avg_amount DOUBLE,
                effective_start VARCHAR(64) NOT NULL DEFAULT '',
                effective_end VARCHAR(64) NOT NULL DEFAULT '',
                effective_n_days BIGINT,
                full_total_return DOUBLE,
                full_annual_return DOUBLE,
                full_annual_volatility DOUBLE,
                full_sharpe DOUBLE,
                full_max_drawdown DOUBLE,
                full_calmar DOUBLE,
                full_win_rate DOUBLE,
                full_n_days BIGINT,
                full_avg_turnover DOUBLE,
                overlap_with_baseline DOUBLE,
                corr_with_baseline DOUBLE,
                return_score DOUBLE,
                drawdown_score DOUBLE,
                risk_adjusted_score DOUBLE,
                cost_score DOUBLE,
                capacity_score DOUBLE,
                stability_score DOUBLE,
                independence_score DOUBLE,
                strategy_version BIGINT,
                strategy_version_mode VARCHAR(255),
                error LONGTEXT NOT NULL,
                generated_at VARCHAR(64) NOT NULL,
                payload_json LONGTEXT NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(run_id, strategy)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    else:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_strategy_admission (
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
                effective_start TEXT NOT NULL DEFAULT '',
                effective_end TEXT NOT NULL DEFAULT '',
                effective_n_days INTEGER,
                full_total_return REAL,
                full_annual_return REAL,
                full_annual_volatility REAL,
                full_sharpe REAL,
                full_max_drawdown REAL,
                full_calmar REAL,
                full_win_rate REAL,
                full_n_days INTEGER,
                full_avg_turnover REAL,
                overlap_with_baseline REAL,
                corr_with_baseline REAL,
                return_score REAL,
                drawdown_score REAL,
                risk_adjusted_score REAL,
                cost_score REAL,
                capacity_score REAL,
                stability_score REAL,
                independence_score REAL,
                strategy_version INTEGER,
                strategy_version_mode TEXT,
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
        "eval_strategy_admission",
        {
            "admission_score": "REAL",
            "month_count": "INTEGER",
            "monthly_win_rate": "REAL",
            "worst_month_return": "REAL",
            "positive_3m_rate": "REAL",
            "effective_start": "TEXT NOT NULL DEFAULT ''",
            "effective_end": "TEXT NOT NULL DEFAULT ''",
            "effective_n_days": "INTEGER",
            "full_total_return": "REAL",
            "full_annual_return": "REAL",
            "full_annual_volatility": "REAL",
            "full_sharpe": "REAL",
            "full_max_drawdown": "REAL",
            "full_calmar": "REAL",
            "full_win_rate": "REAL",
            "full_n_days": "INTEGER",
            "full_avg_turnover": "REAL",
            "return_score": "REAL",
            "drawdown_score": "REAL",
            "risk_adjusted_score": "REAL",
            "cost_score": "REAL",
            "capacity_score": "REAL",
            "stability_score": "REAL",
            "independence_score": "REAL",
            "strategy_version": "INTEGER",
            "strategy_version_mode": "TEXT",
        },
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_run ON eval_strategy_admission(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_strategy ON eval_strategy_admission(strategy)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_admission ON eval_strategy_admission(admission)")


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    existing = table_columns(conn, table)
    for name, ddl in columns.items():
        if name.lower() not in existing:
            add_column(conn, table, name, ddl)


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
