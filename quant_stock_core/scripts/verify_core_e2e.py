from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from common.infra import db
from scripts.limit_breakout_worker import BreakoutBar, Candidate, write_cache as write_breakout_cache
from scripts.limit_up_momentum_worker import MomentumCandidate, write_cache as write_momentum_cache


def _count(conn: db.ConnectionAdapter, table: str) -> int:
    if not db.table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0] or 0)


def _cleanup(cache_key: str) -> None:
    with db.write_transaction() as conn:
        for table in ("market_limit_breakout_cache", "market_limit_breakout_cache_meta"):
            if db.table_exists(conn, table):
                conn.execute(f"DELETE FROM {table} WHERE cache_key = ?", (cache_key,))
        for table in ("market_limit_momentum_cache", "market_limit_momentum_cache_meta"):
            if db.table_exists(conn, table):
                conn.execute(f"DELETE FROM {table} WHERE cache_key = ?", (cache_key,))
        if db.table_exists(conn, "market_limit_signal_predictions"):
            conn.execute("DELETE FROM market_limit_signal_predictions WHERE parameter_key = ?", (cache_key,))


def _bar(date: str) -> BreakoutBar:
    return BreakoutBar(
        trade_date=date,
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        pct_chg=2.0,
    )


def _write_worker_smoke(cache_key: str) -> dict[str, object]:
    _cleanup(cache_key)
    try:
        write_breakout_cache(
            Path("."),
            cache_key,
            [
                Candidate(
                    ts_code="600101.SH",
                    name="E2E横盘",
                    industry="测试",
                    latest_date="20260611",
                    close=10.2,
                    score=80.0,
                    flat_score=0.8,
                    breakout_score=0.7,
                    quality_score=0.6,
                    base_low=9.5,
                    base_high=10.5,
                    base_ratio=0.1,
                    base_return=0.02,
                    recent_return=0.05,
                    limit_up_count=1,
                    volume_surge=1.8,
                    roe=12.0,
                    net_margin=8.0,
                    debt_to_assets=45.0,
                    reasons=["e2e"],
                    bars=[_bar("20260611")],
                    projected_bars=[],
                )
            ],
        )
        write_momentum_cache(
            None,
            cache_key,
            [
                MomentumCandidate(
                    ts_code="600102.SH",
                    name="E2E涨停",
                    industry="测试",
                    trade_date="20260611",
                    close=12.3,
                    stage="watch",
                    recommendation="可试仓",
                    score=76.0,
                    chain_potential=72.0,
                    end_risk=20.0,
                    liquidity_risk=15.0,
                    fund_confirmation=68.0,
                    limit_up_count=2,
                    consecutive_boards=1,
                    next_day_return=0.01,
                    return_3d=0.03,
                    return_5d=0.05,
                    return_10d=0.08,
                    max_drawdown_5d=-0.04,
                    recent_20_return=0.16,
                    recent_60_return=0.22,
                    turnover_rate=4.2,
                    volume_ratio=1.6,
                    amount=120000.0,
                    total_mv=500000.0,
                    circ_mv=300000.0,
                    dragon_tiger_net_buy=0.0,
                    institution_net_buy=0.0,
                    reasons=["e2e"],
                    risks=[],
                    bars=[_bar("20260611")],
                    projected_bars=[],
                )
            ],
        )
        with db.open_db() as conn:
            breakout_cols = db.table_columns(conn, "market_limit_breakout_cache")
            momentum_cols = db.table_columns(conn, "market_limit_momentum_cache")
            breakout_count = conn.execute(
                "SELECT COUNT(*) FROM market_limit_breakout_cache WHERE cache_key = ? AND rank_no = 1",
                (cache_key,),
            ).fetchone()[0]
            momentum_count = conn.execute(
                "SELECT COUNT(*) FROM market_limit_momentum_cache WHERE cache_key = ? AND rank_no = 1",
                (cache_key,),
            ).fetchone()[0]
            prediction_count = conn.execute(
                "SELECT COUNT(*) FROM market_limit_signal_predictions WHERE parameter_key = ?",
                (cache_key,),
            ).fetchone()[0]
        return {
            "ok": "rank_no" in breakout_cols and "rank" not in breakout_cols
            and "rank_no" in momentum_cols and "rank" not in momentum_cols
            and int(breakout_count) == 1
            and int(momentum_count) == 1
            and int(prediction_count) == 2,
            "breakout_cache_rows": int(breakout_count),
            "momentum_cache_rows": int(momentum_count),
            "prediction_rows": int(prediction_count),
        }
    finally:
        _cleanup(cache_key)


def run() -> dict[str, object]:
    cache_key = f"e2e:{uuid4().hex}"
    report: dict[str, object] = {"checks": {}, "readiness_checks": {}}
    with db.open_db() as conn:
        report["database"] = {"backend": conn.backend, "dsn": db.desktop_db_dsn()}
        counts = {
            "data_daily_bars": _count(conn, "data_daily_bars"),
            "data_stock_basic": _count(conn, "data_stock_basic"),
            "factor_model_runs": _count(conn, "factor_model_runs"),
            "factor_latest_predictions": _count(conn, "factor_latest_predictions"),
            "factor_model_stress_results": _count(conn, "factor_model_stress_results"),
            "eval_strategy_admission": _count(conn, "eval_strategy_admission"),
            "strategy_model_active": _count(conn, "strategy_model_active"),
            "factor_autotune_runs": _count(conn, "factor_autotune_runs"),
            "factor_autotune_trials": _count(conn, "factor_autotune_trials"),
        }
        report["counts"] = counts
        report["checks"]["base_market_data"] = counts["data_daily_bars"] > 0 and counts["data_stock_basic"] > 0
        report["checks"]["factor_model_artifacts"] = (
            counts["factor_model_runs"] > 0
            and counts["factor_latest_predictions"] > 0
            and counts["factor_model_stress_results"] > 0
            and counts["eval_strategy_admission"] > 0
        )
        latest_admission = None
        if db.table_exists(conn, "eval_strategy_admission"):
            latest_admission = conn.execute(
                """
                SELECT run_id, admission, COALESCE(admission_score, 0), COALESCE(reason, ''),
                       COALESCE(annual_return, 0), COALESCE(max_drawdown, 0),
                       COALESCE(effective_start, ''), COALESCE(effective_end, '')
                FROM eval_strategy_admission
                WHERE strategy = 'ml_factor_ranker'
                ORDER BY generated_at DESC
                LIMIT 1
                """
            ).fetchone()
        if latest_admission:
            report["latest_factor_admission"] = {
                "run_id": latest_admission[0],
                "admission": latest_admission[1],
                "admission_score": float(latest_admission[2] or 0),
                "reason": latest_admission[3],
                "annual_return": float(latest_admission[4] or 0),
                "max_drawdown": float(latest_admission[5] or 0),
                "effective_start": latest_admission[6],
                "effective_end": latest_admission[7],
            }
        latest_autotune = None
        if db.table_exists(conn, "factor_autotune_runs"):
            latest_autotune = conn.execute(
                """
                SELECT run_id, base_model_run_id, status, COALESCE(best_trial_id, ''),
                       COALESCE(best_admission, ''), COALESCE(best_score, 0),
                       COALESCE(summary_json, '{}'), updated_at
                FROM factor_autotune_runs
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        if latest_autotune:
            latest_trials = []
            if db.table_exists(conn, "factor_autotune_trials"):
                trial_rows = conn.execute(
                    """
                    SELECT trial_id, source, admission, COALESCE(admission_score, 0),
                           COALESCE(annual_return, 0), COALESCE(max_drawdown, 0),
                           COALESCE(reason, ''), COALESCE(passed, 0)
                    FROM factor_autotune_trials
                    WHERE run_id = ?
                    ORDER BY round_no ASC, trial_id ASC
                    LIMIT 5
                    """,
                    (latest_autotune[0],),
                ).fetchall()
                latest_trials = [
                    {
                        "trial_id": row[0],
                        "source": row[1],
                        "admission": row[2],
                        "admission_score": float(row[3] or 0),
                        "annual_return": float(row[4] or 0),
                        "max_drawdown": float(row[5] or 0),
                        "reason": row[6],
                        "passed": bool(int(row[7] or 0)),
                    }
                    for row in trial_rows
                ]
            report["latest_factor_autotune"] = {
                "run_id": latest_autotune[0],
                "base_model_run_id": latest_autotune[1],
                "status": latest_autotune[2],
                "best_trial_id": latest_autotune[3],
                "best_admission": latest_autotune[4],
                "best_score": float(latest_autotune[5] or 0),
                "summary_json": latest_autotune[6],
                "updated_at": latest_autotune[7],
                "trials": latest_trials,
            }
        active_factor = False
        if db.table_exists(conn, "strategy_model_active"):
            active_row = conn.execute(
                "SELECT run_id FROM strategy_model_active WHERE strategy = 'ml_factor_ranker'"
            ).fetchone()
            active_factor = bool(active_row and active_row[0])
        report["readiness_checks"]["factor_model_active"] = active_factor
        if not active_factor:
            if latest_autotune:
                report["factor_model_active_diagnosis"] = (
                    f"暂无 active 通用模型；最近 AutoTune {latest_autotune[0]} "
                    f"状态 {latest_autotune[2]}，最佳准入 {latest_autotune[4] or '-'}。"
                )
            else:
                report["factor_model_active_diagnosis"] = "暂无 active 通用模型；尚无 AutoTune 运行记录。"
        for table in ("market_limit_breakout_cache", "market_limit_momentum_cache"):
            if db.table_exists(conn, table):
                cols = db.table_columns(conn, table)
                report["checks"][f"{table}_rank_no_schema"] = "rank_no" in cols and "rank" not in cols
            else:
                report["checks"][f"{table}_rank_no_schema"] = False
    worker = _write_worker_smoke(cache_key)
    report["worker_cache_smoke"] = worker
    report["checks"]["worker_cache_smoke"] = bool(worker["ok"])
    report["ok"] = all(bool(value) for value in report["checks"].values())
    report["readiness_ok"] = all(bool(value) for value in report["readiness_checks"].values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify core Python + MySQL end-to-end health.")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--strict-active", action="store_true", help="fail when no active tradable model is configured")
    args = parser.parse_args()
    report = run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            print("\nE2E verification failed. See checks=false above.")
        elif args.strict_active and not report["readiness_ok"]:
            print("\nE2E readiness failed. System health is ok, but no active tradable model is configured.")
    if not report["ok"]:
        return 1
    if args.strict_active and not report["readiness_ok"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
