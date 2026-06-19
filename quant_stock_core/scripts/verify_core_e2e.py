from __future__ import annotations

import argparse
import json

from common.infra import db


def _count(conn: db.ConnectionAdapter, table: str) -> int:
    if not db.table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0] or 0)


def run() -> dict[str, object]:
    report: dict[str, object] = {"checks": {}, "readiness_checks": {}}
    with db.open_db() as conn:
        report["database"] = {"backend": conn.backend, "dsn": db.desktop_db_dsn()}
        counts = {
            "data_daily_bars": _count(conn, "data_daily_bars"),
            "data_stock_basic": _count(conn, "data_stock_basic"),
            "factor_model_runs": _count(conn, "factor_model_runs"),
            "factor_latest_predictions": _count(conn, "factor_latest_predictions"),
            "factor_model_stress_results": _count(conn, "factor_model_stress_results"),
            "strategy_model_active": _count(conn, "strategy_model_active"),
            "factor_store_snapshots": _count(conn, "factor_store_snapshots"),
            "profit_arena_model_runs": _count(conn, "profit_arena_model_runs"),
        }
        report["counts"] = counts
        report["checks"]["base_market_data"] = counts["data_daily_bars"] > 0 and counts["data_stock_basic"] > 0
        report["checks"]["factor_model_artifacts"] = (
            counts["factor_model_runs"] > 0
            and counts["factor_latest_predictions"] > 0
            and counts["factor_model_stress_results"] > 0
        )
        report["checks"]["profit_arena_artifacts"] = counts["factor_store_snapshots"] > 0 and counts["profit_arena_model_runs"] > 0
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
        active_factor = False
        if db.table_exists(conn, "strategy_model_active"):
            active_row = conn.execute(
                "SELECT run_id FROM strategy_model_active WHERE strategy = 'profit_arena_model'"
            ).fetchone()
            active_factor = bool(active_row and active_row[0])
        report["readiness_checks"]["profit_arena_model_active"] = active_factor
        if not active_factor:
            report["profit_arena_model_active_diagnosis"] = "暂无 active 收益擂台模型；请先完成收益擂台训练并启用擂主。"
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
