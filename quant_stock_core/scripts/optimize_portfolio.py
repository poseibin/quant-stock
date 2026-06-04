"""组合优化时光机。

批量生成候选策略组合，用向量化回放快速筛选 Top 组合，结果写入
SQLite，供 desktop 统一读取。真实逐日撮合时光机用于 Top 组合复核。
"""
from __future__ import annotations

import argparse
import itertools
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

from common.config.desktop_settings import load_portfolio_risk, load_strategy_settings
from common.infra.db import write_transaction
from common.utils import get_logger
from trading.backtest import BacktestConfig, CostModel, run as bt_run
from trading.strategy import registry
from trading.strategy import combiner
from scripts.evaluate_strategies import _weight_exposure

log = get_logger("optimize_portfolio")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--strategies", default="all", help="all / enabled / comma-separated names")
    parser.add_argument("--benchmark", default="000905.SH")
    parser.add_argument("--slippage", type=float, default=0.002)
    parser.add_argument("--objective", choices=["稳健", "平衡", "进攻"], default="平衡")
    parser.add_argument("--max-candidates", type=int, default=40)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--save", default=None, help="run id；结果写入 SQLite")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    names = _resolve_strategy_names(args.strategies)
    payload = optimize(
        names,
        args.start,
        args.end,
        benchmark=args.benchmark,
        slippage=args.slippage,
        objective=args.objective,
        max_candidates=args.max_candidates,
        top_n=args.top_n,
    )
    if args.save:
        db_path = _resolve_db_path(args.db_path)
        save_portfolio_optimization(db_path, args.save, payload)
        log.info(f"组合优化结果已保存到 SQLite: {db_path} run_id={args.save}")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    else:
        rows = pd.DataFrame(payload.get("rows") or [])
        cols = ["rank", "name", "score", "annual_return", "max_drawdown", "sharpe", "calmar", "avg_turnover", "avg_holdings", "strategies"]
        print(rows[[c for c in cols if c in rows.columns]].to_string(index=False))


def optimize(
    names: list[str],
    start: str,
    end: str,
    *,
    benchmark: str,
    slippage: float,
    objective: str,
    max_candidates: int,
    top_n: int,
) -> dict[str, Any]:
    settings = load_strategy_settings()
    risk = load_portfolio_risk()
    panels: dict[str, pd.DataFrame] = {}
    individual: dict[str, dict[str, Any]] = {}

    for name in names:
        try:
            strategy = registry.build(name)
            weights = strategy.generate_target_weights(start, end)
            if weights.empty:
                individual[name] = {"status": "empty"}
                continue
            result = _run_panel(weights, start, end, benchmark, slippage)
            row = {"status": "ok", **result.summary, **_weight_exposure(result.weights)}
            individual[name] = row
            panels[name] = weights
        except Exception as exc:  # noqa: BLE001
            individual[name] = {"status": "error", "error": str(exc)}

    viable = _select_viable(individual)
    candidates = _generate_candidates(viable, individual, objective, max_candidates)

    rows: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates, start=1):
        try:
            weights = _combine_candidate(candidate["weights"], panels, risk)
            if weights.empty:
                continue
            result = _run_panel(weights, start, end, benchmark, slippage)
            row = {
                "candidate_id": f"cand_{idx:03d}",
                "name": candidate["name"],
                "objective": objective,
                "strategies": ",".join(candidate["weights"].keys()),
                "weights": candidate["weights"],
                "status": "ok",
                **result.summary,
                **_weight_exposure(result.weights),
            }
            row["score"] = _score(row, objective)
            row["reason"] = _reason(row)
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "candidate_id": f"cand_{idx:03d}",
                "name": candidate["name"],
                "objective": objective,
                "strategies": ",".join(candidate["weights"].keys()),
                "weights": candidate["weights"],
                "status": "error",
                "error": str(exc),
                "score": -999.0,
            })

    rows = sorted(rows, key=lambda r: float(r.get("score") or -999), reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    return {
        "start": start,
        "end": end,
        "benchmark": benchmark,
        "objective": objective,
        "strategy_count": len(names),
        "viable_count": len(viable),
        "candidate_count": len(rows),
        "top_n": top_n,
        "individual": individual,
        "rows": rows[:top_n],
    }


def _run_panel(weights: pd.DataFrame, start: str, end: str, benchmark: str, slippage: float):
    return bt_run(
        weights,
        BacktestConfig(
            start=start,
            end=end,
            cost=CostModel(slippage=slippage),
            benchmark=benchmark,
            progress=False,
        ),
    )


def _select_viable(individual: dict[str, dict[str, Any]]) -> list[str]:
    viable = []
    for name, row in individual.items():
        if row.get("status") != "ok":
            continue
        annual = float(row.get("annual_return") or 0)
        drawdown = float(row.get("max_drawdown") or 0)
        turnover = float(row.get("avg_turnover") or 0)
        if annual > -0.03 and drawdown > -0.22 and turnover < 0.25:
            viable.append(name)
    return viable


def _generate_candidates(
    viable: list[str],
    individual: dict[str, dict[str, Any]],
    objective: str,
    max_candidates: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        viable,
        key=lambda n: (
            float(individual[n].get("annual_return") or 0),
            float(individual[n].get("sharpe") or 0),
        ),
        reverse=True,
    )
    core = "small_cap_quality" if "small_cap_quality" in ranked else (ranked[0] if ranked else "")
    pool = ranked[:8]
    candidates: list[dict[str, Any]] = []

    def add(name: str, weights: dict[str, float]) -> None:
        if not weights:
            return
        total = sum(max(0.0, float(v)) for v in weights.values())
        if total <= 0:
            return
        norm = {k: round(max(0.0, float(v)) / total, 4) for k, v in weights.items()}
        key = tuple(sorted(norm.items()))
        if any(tuple(sorted(c["weights"].items())) == key for c in candidates):
            return
        candidates.append({"name": name, "weights": norm})

    for name in pool:
        add(f"单策略-{registry.get_label(name)}", {name: 1.0})

    if core:
        for other in pool:
            if other != core:
                add(f"核心增强-{registry.get_label(core)}+{registry.get_label(other)}", {core: 0.65, other: 0.35})

    for combo in itertools.combinations(pool, 2):
        add("双策略等权-" + "+".join(registry.get_label(x) for x in combo), {x: 1.0 for x in combo})
    for combo in itertools.combinations(pool[:6], 3):
        add("三策略等权-" + "+".join(registry.get_label(x) for x in combo), {x: 1.0 for x in combo})
        add("三策略夏普权重-" + "+".join(registry.get_label(x) for x in combo), _metric_weights(combo, individual))

    if objective == "稳健":
        defensive = [x for x in pool if x in {"dividend_low_vol", "garp_quality", "forecast_revision", core}]
        add("稳健低回撤组合", {x: 1.0 for x in defensive if x})
    elif objective == "进攻":
        aggressive = [x for x in pool if x in {"forecast_revision", "trend_quality", "moneyflow_pullback", core}]
        add("小资金进攻组合", {x: 1.0 for x in aggressive if x})
    else:
        balanced = [x for x in pool if x in {"small_cap_quality", "forecast_revision", "garp_quality", "dividend_low_vol"}]
        add("平衡核心组合", {x: 1.0 for x in balanced if x})

    return candidates[:max(1, max_candidates)]


def _metric_weights(combo: tuple[str, ...], individual: dict[str, dict[str, Any]]) -> dict[str, float]:
    scores = {}
    for name in combo:
        row = individual[name]
        sharpe = max(0.05, float(row.get("sharpe") or 0.05))
        dd = abs(float(row.get("max_drawdown") or -0.10))
        scores[name] = sharpe / max(dd, 0.03)
    return scores


def _combine_candidate(weights: dict[str, float], panels: dict[str, pd.DataFrame], risk: dict) -> pd.DataFrame:
    selected = []
    for name, weight in weights.items():
        panel = panels.get(name)
        if panel is not None and not panel.empty:
            selected.append(panel * float(weight))
    if not selected:
        return pd.DataFrame()
    all_dates = sorted(set().union(*[p.index for p in selected]))
    all_codes = sorted(set().union(*[p.columns for p in selected]))
    combined = pd.DataFrame(0.0, index=all_dates, columns=all_codes)
    for panel in selected:
        combined = combined + panel.reindex(index=all_dates, columns=all_codes).ffill().fillna(0.0)
    if risk:
        combined = combiner._apply_market_regime(combined, risk)  # noqa: SLF001
        combined = combiner._apply_portfolio_risk(combined, risk)  # noqa: SLF001
    return combined


def _score(row: dict[str, Any], objective: str) -> float:
    annual = float(row.get("annual_return") or 0)
    sharpe = float(row.get("sharpe") or 0)
    calmar = float(row.get("calmar") or 0)
    drawdown = abs(float(row.get("max_drawdown") or 0))
    turnover = float(row.get("avg_turnover") or 0)
    holdings = float(row.get("avg_holdings") or 0)

    if objective == "稳健":
        score = annual * 0.25 + sharpe * 0.25 + calmar * 0.30 - drawdown * 0.18 - turnover * 0.02
    elif objective == "进攻":
        score = annual * 0.48 + sharpe * 0.18 + calmar * 0.18 - drawdown * 0.11 - turnover * 0.05
    else:
        score = annual * 0.35 + sharpe * 0.22 + calmar * 0.25 - drawdown * 0.13 - turnover * 0.05
    if holdings < 3:
        score -= 0.08
    return float(score)


def _reason(row: dict[str, Any]) -> str:
    annual = float(row.get("annual_return") or 0)
    drawdown = float(row.get("max_drawdown") or 0)
    sharpe = float(row.get("sharpe") or 0)
    if annual > 0 and drawdown > -0.12 and sharpe >= 0.6:
        return "收益、回撤和夏普相对均衡"
    if drawdown <= -0.18:
        return "回撤偏大，需降低权重或继续观察"
    if annual <= 0:
        return "收益不足，暂不建议采用"
    return "表现为正，但需更多窗口验证"


def _resolve_strategy_names(arg: str) -> list[str]:
    names = registry.all_names()
    settings = load_strategy_settings()
    if arg == "all":
        return names
    if arg == "enabled":
        return [n for n in names if settings.get(n, {}).get("enabled", False)]
    wanted = [x.strip() for x in arg.split(",") if x.strip()]
    unknown = sorted(set(wanted) - set(names))
    if unknown:
        raise SystemExit(f"Unknown strategies: {unknown}; registered={names}")
    return wanted


def _resolve_db_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    env = os.getenv("DESKTOP_DB_PATH", "").strip() or os.getenv("DESKTOP_CONFIG_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    data_root = os.getenv("DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root).expanduser().resolve() / "meta.db"
    return (ROOT.parent / "data_store" / "meta.db").resolve()


def save_portfolio_optimization(db_path: Path, run_id: str, payload: dict[str, Any]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = pd.Timestamp.now().isoformat()
    with write_transaction(db_path) as conn:
        _ensure_tables(conn)
        conn.execute("DELETE FROM portfolio_optimization_candidates WHERE run_id = ?", (run_id,))
        conn.execute(
            """
            INSERT INTO portfolio_optimization_runs(
                run_id, start_date, end_date, objective, benchmark, strategy_count,
                viable_count, candidate_count, top_n, generated_at, summary_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(run_id) DO UPDATE SET
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                objective = excluded.objective,
                benchmark = excluded.benchmark,
                strategy_count = excluded.strategy_count,
                viable_count = excluded.viable_count,
                candidate_count = excluded.candidate_count,
                top_n = excluded.top_n,
                generated_at = excluded.generated_at,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                run_id,
                payload.get("start", ""),
                payload.get("end", ""),
                payload.get("objective", ""),
                payload.get("benchmark", ""),
                int(payload.get("strategy_count") or 0),
                int(payload.get("viable_count") or 0),
                int(payload.get("candidate_count") or 0),
                int(payload.get("top_n") or 0),
                generated_at,
                json.dumps(payload, ensure_ascii=False, default=_json_default),
            ),
        )
        for row in payload.get("rows") or []:
            conn.execute(
                """
                INSERT INTO portfolio_optimization_candidates(
                    run_id, candidate_id, rank, name, objective, status, score,
                    strategies, weights_json, annual_return, max_drawdown, sharpe,
                    calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount,
                    reason, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    run_id,
                    row.get("candidate_id", ""),
                    int(row.get("rank") or 0),
                    row.get("name", ""),
                    row.get("objective", ""),
                    row.get("status", ""),
                    float(row.get("score") or 0),
                    row.get("strategies", ""),
                    json.dumps(row.get("weights") or {}, ensure_ascii=False),
                    _float_or_none(row.get("annual_return")),
                    _float_or_none(row.get("max_drawdown")),
                    _float_or_none(row.get("sharpe")),
                    _float_or_none(row.get("calmar")),
                    _float_or_none(row.get("avg_turnover")),
                    _float_or_none(row.get("avg_holdings")),
                    _float_or_none(row.get("avg_total_mv")),
                    _float_or_none(row.get("avg_amount")),
                    row.get("reason", ""),
                    json.dumps(row, ensure_ascii=False, default=_json_default),
                ),
            )


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_optimization_runs (
            run_id TEXT PRIMARY KEY,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            objective TEXT NOT NULL,
            benchmark TEXT NOT NULL DEFAULT '',
            strategy_count INTEGER NOT NULL DEFAULT 0,
            viable_count INTEGER NOT NULL DEFAULT 0,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            top_n INTEGER NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_optimization_candidates (
            run_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            rank INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT '',
            objective TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL DEFAULT 0,
            strategies TEXT NOT NULL DEFAULT '',
            weights_json TEXT NOT NULL DEFAULT '{}',
            annual_return REAL,
            max_drawdown REAL,
            sharpe REAL,
            calmar REAL,
            avg_turnover REAL,
            avg_holdings REAL,
            avg_total_mv REAL,
            avg_amount REAL,
            reason TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(run_id, candidate_id)
        )
        """
    )


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
