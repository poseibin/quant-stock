#!/usr/bin/env python3
"""Validate trained strategy-model artifacts for desktop task pipelines."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from common.infra.db import open_db, replace_sql


def ensure_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_model_validation_results (
            strategy VARCHAR(64) NOT NULL,
            run_id VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL,
            summary_json LONGTEXT,
            error TEXT,
            created_at VARCHAR(64) NOT NULL,
            updated_at VARCHAR(64) NOT NULL,
            PRIMARY KEY(strategy, run_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def one(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    return row[0] if len(row) == 1 else row


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def parse_json(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(str(value))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def file_exists(path_text: str) -> bool:
    path_text = str(path_text or "").strip()
    return bool(path_text) and Path(path_text).exists()


def validate_limit_model(conn: Any, strategy: str, run_id: str) -> dict[str, Any]:
    prefix = "limit_up" if strategy == "limit_up_model" else "limit_breakout"
    run_table = f"{prefix}_model_runs"
    feature_table = f"{prefix}_model_features"
    pred_table = f"{prefix}_model_predictions"
    slice_table = f"{prefix}_model_tm_slices"

    row = one(
        conn,
        f"""
        SELECT status, COALESCE(feature_count, 0), COALESCE(model_path, ''), COALESCE(summary_json, '')
        FROM {run_table}
        WHERE run_id = ?
        """,
        (run_id,),
    )
    if row is None:
        raise RuntimeError(f"{strategy} run not found: {run_id}")
    status, feature_count, model_path, summary_json = row
    summary = parse_json(summary_json)
    prediction_count = as_int(one(conn, f"SELECT COUNT(*) FROM {pred_table} WHERE run_id = ?", (run_id,)))
    latest_count = as_int(one(conn, f"SELECT COUNT(*) FROM {pred_table} WHERE run_id = ? AND is_latest = 1", (run_id,)))
    feature_rows = as_int(one(conn, f"SELECT COUNT(*) FROM {feature_table} WHERE run_id = ?", (run_id,)))
    slice_count = as_int(one(conn, f"SELECT COUNT(*) FROM {slice_table} WHERE run_id = ?", (run_id,)))
    latest_date = one(conn, f"SELECT COALESCE(MAX(trade_date), '') FROM {pred_table} WHERE run_id = ? AND is_latest = 1", (run_id,)) or ""
    checks = {
        "run_success": str(status) == "success",
        "has_features": as_int(feature_count) > 0 and feature_rows > 0,
        "has_predictions": prediction_count > 0,
        "has_latest_predictions": latest_count > 0,
        "has_time_machine_slices": slice_count > 0,
        "model_file_exists": file_exists(str(model_path)),
    }
    warnings: list[str] = []
    if as_float(summary.get("top_excess_return")) <= 0:
        warnings.append("top_excess_return_non_positive")
    if as_float(summary.get("rank_ic")) < -0.02:
        warnings.append("rank_ic_too_low")
    return {
        "strategy": strategy,
        "run_id": run_id,
        "status": "success",
        "checks": checks,
        "warnings": warnings,
        "feature_count": as_int(feature_count),
        "feature_rows": feature_rows,
        "prediction_count": prediction_count,
        "latest_count": latest_count,
        "latest_date": latest_date,
        "time_machine_slice_count": slice_count,
        "model_path": str(model_path or ""),
        "summary": summary,
    }


def validate_t0_daily(conn: Any, run_id: str) -> dict[str, Any]:
    row = one(
        conn,
        """
        SELECT status, COALESCE(candidate_count, 0), COALESCE(backtest_count, 0), COALESCE(summary_json, '')
        FROM t0_daily_runs
        WHERE run_id = ?
        """,
        (run_id,),
    )
    if row is None:
        raise RuntimeError(f"t0_daily run not found: {run_id}")
    status, candidate_count, backtest_count, summary_json = row
    summary = parse_json(summary_json)
    model_summary = summary.get("model") if isinstance(summary.get("model"), dict) else {}
    candidate_rows = as_int(one(conn, "SELECT COUNT(*) FROM t0_daily_candidates WHERE run_id = ?", (run_id,)))
    backtest_rows = as_int(one(conn, "SELECT COUNT(*) FROM t0_daily_backtests WHERE run_id = ?", (run_id,)))
    latest_date = one(conn, "SELECT COALESCE(MAX(trade_date), '') FROM t0_daily_candidates WHERE run_id = ?", (run_id,)) or ""
    model_path = str(model_summary.get("model_path") or "")
    checks = {
        "run_success": str(status) == "success",
        "has_candidates": as_int(candidate_count) > 0 and candidate_rows > 0,
        "has_backtests": as_int(backtest_count) > 0 and backtest_rows > 0,
        "has_model_summary": bool(model_summary),
        "model_file_exists": file_exists(model_path),
    }
    warnings: list[str] = []
    if as_float(model_summary.get("top10_avg_edge")) <= 0:
        warnings.append("top10_avg_edge_non_positive")
    if as_float(model_summary.get("rank_ic")) < -0.02:
        warnings.append("rank_ic_too_low")
    return {
        "strategy": "t0_daily",
        "run_id": run_id,
        "status": "success",
        "checks": checks,
        "warnings": warnings,
        "candidate_count": as_int(candidate_count),
        "candidate_rows": candidate_rows,
        "backtest_count": as_int(backtest_count),
        "backtest_rows": backtest_rows,
        "latest_date": latest_date,
        "model_path": model_path,
        "model": model_summary,
    }


def write_result(conn: Any, strategy: str, run_id: str, status: str, summary: dict[str, Any], error: str = "") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        replace_sql(
            "strategy_model_validation_results",
            ["strategy", "run_id", "status", "summary_json", "error", "created_at", "updated_at"],
            ["strategy", "run_id"],
        ),
        (strategy, run_id, status, json.dumps(summary, ensure_ascii=False), error, now, now),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate strategy model training artifacts")
    parser.add_argument("--strategy", required=True, choices=["limit_up_model", "limit_breakout_model", "t0_daily"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-path", default="")
    args = parser.parse_args()
    with open_db() as conn:
        ensure_table(conn)
        try:
            if args.strategy == "t0_daily":
                summary = validate_t0_daily(conn, args.run_id)
            else:
                summary = validate_limit_model(conn, args.strategy, args.run_id)
            failed = [name for name, ok in summary.get("checks", {}).items() if not ok]
            if failed:
                raise RuntimeError("validation failed: " + ", ".join(failed))
            write_result(conn, args.strategy, args.run_id, "success", summary)
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        except Exception as exc:
            summary = {"strategy": args.strategy, "run_id": args.run_id, "status": "failed", "error": str(exc)}
            write_result(conn, args.strategy, args.run_id, "failed", summary, str(exc))
            print(json.dumps(summary, ensure_ascii=False))
            raise


if __name__ == "__main__":
    raise SystemExit(main())
