"""Compare two historical factor model training runs.

The goal is to verify whether a retrained legacy factor-factory run is
materially consistent with a prior base run before historical AutoTune or
promotion decisions use it. Desktop production training now uses Profit Arena.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import db


SUMMARY_KEYS = [
    "feature_count",
    "fold_count",
    "oos_rank_ic_mean",
    "oos_ic_win_rate",
    "top20_mean_return",
    "bottom20_mean_return",
    "top_bottom_spread",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run-id", required=True)
    parser.add_argument("--new-run-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = compare_runs(args.base_run_id, args.new_run_id)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print_text_report(report)
    return 0 if report["verdict"]["ok"] else 2


def compare_runs(base_run_id: str, new_run_id: str) -> dict[str, Any]:
    with db.open_db() as conn:
        base_summary = model_summary(conn, base_run_id)
        new_summary = model_summary(conn, new_run_id)
        report = {
            "base_run_id": base_run_id,
            "new_run_id": new_run_id,
            "summary": compare_summary(base_summary, new_summary),
            "features": compare_features(conn, base_run_id, new_run_id),
            "predictions": compare_predictions(conn, base_run_id, new_run_id),
            "latest_predictions": compare_latest_predictions(conn, base_run_id, new_run_id),
            "stress": compare_stress(conn, base_run_id, new_run_id),
            "admission": compare_admission(conn, base_run_id, new_run_id),
        }
    report["verdict"] = verdict(report)
    return report


def model_summary(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status, COALESCE(summary_json, '{}') FROM factor_model_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if not row:
        return {"status": "missing"}
    payload = parse_json(row[1], {})
    payload["status"] = row[0]
    return payload


def compare_summary(base: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in SUMMARY_KEYS:
        b = base.get(key)
        n = new.get(key)
        rows.append({"metric": key, "base": b, "new": n, "delta": numeric_delta(b, n)})
    return rows


def compare_features(conn: Any, base_run_id: str, new_run_id: str, top_n: int = 30) -> dict[str, Any]:
    base = read_features(conn, base_run_id, top_n)
    new = read_features(conn, new_run_id, top_n)
    base_set = set(base["feature"].astype(str)) if not base.empty else set()
    new_set = set(new["feature"].astype(str)) if not new.empty else set()
    merged = base.merge(new, on="feature", how="inner", suffixes=("_base", "_new")) if not base.empty and not new.empty else pd.DataFrame()
    corr = safe_corr(merged["importance_base"], merged["importance_new"]) if not merged.empty else None
    return {
        "base_count": int(len(base)),
        "new_count": int(len(new)),
        "top_overlap": len(base_set & new_set),
        "top_jaccard": jaccard(base_set, new_set),
        "importance_corr": corr,
        "base_only": sorted(base_set - new_set)[:10],
        "new_only": sorted(new_set - base_set)[:10],
    }


def read_features(conn: Any, run_id: str, top_n: int) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT feature, COALESCE(importance, 0), COALESCE(rank_no, 0)
        FROM factor_model_features
        WHERE run_id = ?
        ORDER BY rank_no ASC
        LIMIT ?
        """,
        (run_id, top_n),
    ).fetchall()
    return pd.DataFrame(rows, columns=["feature", "importance", "rank_no"])


def compare_predictions(conn: Any, base_run_id: str, new_run_id: str) -> dict[str, Any]:
    base = read_predictions(conn, base_run_id)
    new = read_predictions(conn, new_run_id)
    return compare_prediction_frames(base, new, ["trade_date", "ts_code"])


def read_predictions(conn: Any, run_id: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT trade_date, ts_code, pred_score, realized_return, pred_rank, test_year
        FROM factor_model_predictions
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    return pd.DataFrame(rows, columns=["trade_date", "ts_code", "pred_score", "realized_return", "pred_rank", "test_year"])


def compare_latest_predictions(conn: Any, base_run_id: str, new_run_id: str) -> dict[str, Any]:
    base = read_latest_predictions(conn, base_run_id)
    new = read_latest_predictions(conn, new_run_id)
    return compare_prediction_frames(base, new, ["trade_date", "ts_code"])


def read_latest_predictions(conn: Any, run_id: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT trade_date, ts_code, pred_score, pred_rank, is_top20
        FROM factor_latest_predictions
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    return pd.DataFrame(rows, columns=["trade_date", "ts_code", "pred_score", "pred_rank", "is_top20"])


def compare_prediction_frames(base: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> dict[str, Any]:
    if base.empty or new.empty:
        return {"base_count": int(len(base)), "new_count": int(len(new)), "overlap": 0, "jaccard": 0.0, "score_corr": None, "rank_corr": None}
    base_key = set(tuple(row) for row in base[keys].astype(str).itertuples(index=False, name=None))
    new_key = set(tuple(row) for row in new[keys].astype(str).itertuples(index=False, name=None))
    merged = base.merge(new, on=keys, how="inner", suffixes=("_base", "_new"))
    return {
        "base_count": int(len(base)),
        "new_count": int(len(new)),
        "overlap": int(len(base_key & new_key)),
        "jaccard": jaccard(base_key, new_key),
        "score_corr": safe_corr(merged["pred_score_base"], merged["pred_score_new"]) if not merged.empty else None,
        "rank_corr": safe_corr(merged["pred_rank_base"], merged["pred_rank_new"]) if "pred_rank_base" in merged.columns and not merged.empty else None,
    }


def compare_stress(conn: Any, base_run_id: str, new_run_id: str) -> list[dict[str, Any]]:
    base = read_stress(conn, base_run_id)
    new = read_stress(conn, new_run_id)
    if base.empty or new.empty:
        return []
    merged = base.merge(new, on=["bucket_type", "bucket_key", "bucket_label"], how="outer", suffixes=("_base", "_new"))
    rows: list[dict[str, Any]] = []
    for row in merged.itertuples(index=False):
        item = row._asdict()
        rows.append({
            "bucket_type": item.get("bucket_type"),
            "bucket_key": item.get("bucket_key"),
            "bucket_label": item.get("bucket_label"),
            "annual_return_base": item.get("annual_return_base"),
            "annual_return_new": item.get("annual_return_new"),
            "annual_return_delta": numeric_delta(item.get("annual_return_base"), item.get("annual_return_new")),
            "max_drawdown_base": item.get("max_drawdown_base"),
            "max_drawdown_new": item.get("max_drawdown_new"),
            "max_drawdown_delta": numeric_delta(item.get("max_drawdown_base"), item.get("max_drawdown_new")),
        })
    rows.sort(key=lambda item: (str(item["bucket_type"]), str(item["bucket_key"])))
    return rows


def read_stress(conn: Any, run_id: str) -> pd.DataFrame:
    rows = conn.execute(
        """
        SELECT bucket_type, bucket_key, bucket_label, annual_return, max_drawdown, sharpe, win_rate
        FROM factor_model_stress_results
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    return pd.DataFrame(rows, columns=["bucket_type", "bucket_key", "bucket_label", "annual_return", "max_drawdown", "sharpe", "win_rate"])


def compare_admission(conn: Any, base_run_id: str, new_run_id: str) -> dict[str, Any]:
    base = read_admission(conn, "eval_" + base_run_id)
    new = read_admission(conn, "eval_" + new_run_id)
    return {
        "base": base,
        "new": new,
        "score_delta": numeric_delta(base.get("admission_score"), new.get("admission_score")),
        "annual_return_delta": numeric_delta(base.get("annual_return"), new.get("annual_return")),
        "max_drawdown_delta": numeric_delta(base.get("max_drawdown"), new.get("max_drawdown")),
    }


def read_admission(conn: Any, eval_run_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT admission, admission_score, reason, annual_return, total_return, max_drawdown, sharpe
        FROM eval_strategy_admission
        WHERE run_id = ? AND strategy = 'ml_factor_ranker'
        """,
        (eval_run_id,),
    ).fetchone()
    if not row:
        return {"admission": "missing"}
    return {
        "admission": row[0],
        "admission_score": float(row[1] or 0),
        "reason": row[2],
        "annual_return": float(row[3] or 0),
        "total_return": float(row[4] or 0),
        "max_drawdown": float(row[5] or 0),
        "sharpe": float(row[6] or 0),
    }


def verdict(report: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    preds = report["predictions"]
    latest = report["latest_predictions"]
    features = report["features"]
    if preds.get("base_count") != preds.get("new_count"):
        issues.append("OOS Top20 prediction row count changed")
    if preds.get("rank_corr") is not None and float(preds["rank_corr"]) < 0.995:
        issues.append("OOS prediction rank correlation below 0.995")
    if latest.get("rank_corr") is not None and float(latest["rank_corr"]) < 0.995:
        issues.append("latest prediction rank correlation below 0.995")
    if float(features.get("top_jaccard") or 0) < 0.80:
        issues.append("top feature overlap below 80%")
    return {"ok": len(issues) == 0, "issues": issues}


def print_text_report(report: dict[str, Any]) -> None:
    print(f"Base: {report['base_run_id']}")
    print(f"New : {report['new_run_id']}")
    print(f"Verdict: {'OK' if report['verdict']['ok'] else 'CHECK'}")
    for issue in report["verdict"]["issues"]:
        print(f"- {issue}")
    print("\nSummary:")
    for row in report["summary"]:
        print(f"- {row['metric']}: {row['base']} -> {row['new']} delta={row['delta']}")
    print("\nFeatures:", report["features"])
    print("Predictions:", report["predictions"])
    print("Latest:", report["latest_predictions"])
    print("Admission:", report["admission"])
    print("\nStress deltas:")
    for row in report["stress"]:
        if abs(float(row.get("annual_return_delta") or 0)) > 1e-6 or abs(float(row.get("max_drawdown_delta") or 0)) > 1e-6:
            print(f"- {row['bucket_type']}/{row['bucket_key']} {row['bucket_label']}: annual {row['annual_return_delta']}, drawdown {row['max_drawdown_delta']}")


def parse_json(raw: Any, default: Any) -> Any:
    try:
        return json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return default


def numeric_delta(base: Any, new: Any) -> float | None:
    try:
        return float(new) - float(base)
    except (TypeError, ValueError):
        return None


def safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    corr = pd.to_numeric(left, errors="coerce").corr(pd.to_numeric(right, errors="coerce"))
    return None if pd.isna(corr) else float(corr)


def jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return float(len(left & right) / len(union)) if union else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
