"""Historical long-running search for the legacy factor-factory model.

This runner is intentionally conservative: it never enables a model by itself.
It keeps searching across successful base model runs and AutoTune parameter
trials, records durable progress in MySQL, and leaves the final promotion to
the normal admission/activation gates. Desktop production training now goes
through the Profit Arena framework; keep this script for old research only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status as run_status
from common.infra.db import table_exists, write_transaction


TASK_NAME = "factor_optimal_model_search"
# Historical compatibility key, not a desktop production strategy.
STRATEGY = "ml_factor_ranker"
PASS_ADMISSIONS = {"可启用", "限制启用", "已启用"}


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=f"optimal_factor_search_{now_tag()}")
    parser.add_argument("--start", default="20140701")
    parser.add_argument("--end", default="20260612")
    parser.add_argument("--rounds-per-model", type=int, default=30)
    parser.add_argument("--trials-per-round", type=int, default=12)
    parser.add_argument("--max-cycles", type=int, default=999999)
    parser.add_argument("--sleep-seconds", type=int, default=30)
    parser.add_argument("--base-model-run-id", default="", help="只搜索指定基础模型；为空时轮转所有小盘模型")
    parser.add_argument("--use-deepseek", action="store_true")
    parser.add_argument("--stop-on-pass", action="store_true")
    parser.add_argument("--allow-legacy-factor-model", action="store_true", help="显式允许运行历史 ml_factor_ranker 长跑搜索")
    return parser.parse_args()


def successful_models(base_model_run_id: str = "") -> list[dict[str, Any]]:
    with write_transaction() as conn:
        if base_model_run_id:
            rows = conn.execute(
                """
                SELECT run_id, label, updated_at
                FROM factor_model_runs
                WHERE status = 'success' AND run_id = ?
                """,
                (base_model_run_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id, label, updated_at
                FROM factor_model_runs
                WHERE status = 'success'
                  AND run_id LIKE ?
                ORDER BY updated_at DESC
                """,
                ("fr_smallcap_%",),
            ).fetchall()
    models: list[dict[str, Any]] = []
    for row in rows:
        run_id = str(row[0] or "")
        if not run_id:
            continue
        models.append({"run_id": run_id, "label": row[1], "updated_at": row[2]})
    return models


def latest_admission_for_model(model_run_id: str) -> dict[str, Any]:
    with write_transaction() as conn:
        if not table_exists(conn, "eval_strategy_admission"):
            return {}
        row = conn.execute(
            """
            SELECT run_id, admission, COALESCE(admission_score, 0), COALESCE(reason, ''),
                   COALESCE(annual_return, 0), COALESCE(total_return, 0),
                   COALESCE(max_drawdown, 0), COALESCE(sharpe, 0), generated_at
            FROM eval_strategy_admission
            WHERE strategy = ? AND (run_id = ? OR run_id = ?)
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (STRATEGY, f"eval_{model_run_id}", model_run_id),
        ).fetchone()
    if not row:
        return {}
    return {
        "eval_run_id": row[0],
        "admission": row[1],
        "admission_score": float(row[2] or 0),
        "reason": row[3],
        "annual_return": float(row[4] or 0),
        "total_return": float(row[5] or 0),
        "max_drawdown": float(row[6] or 0),
        "sharpe": float(row[7] or 0),
        "generated_at": row[8],
    }


def best_autotune_trial(model_run_id: str = "") -> dict[str, Any]:
    with write_transaction() as conn:
        if not table_exists(conn, "factor_autotune_trials"):
            return {}
        where = "WHERE model_run_id = ?" if model_run_id else ""
        params = (model_run_id,) if model_run_id else ()
        row = conn.execute(
            f"""
            SELECT run_id, trial_id, model_run_id, eval_run_id, admission,
                   COALESCE(admission_score, 0), COALESCE(reason, ''),
                   COALESCE(annual_return, 0), COALESCE(total_return, 0),
                   COALESCE(max_drawdown, 0), COALESCE(sharpe, 0),
                   COALESCE(passed, 0), updated_at
            FROM factor_autotune_trials
            {where}
            ORDER BY passed DESC, admission_score DESC, annual_return DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    if not row:
        return {}
    return {
        "autotune_run_id": row[0],
        "trial_id": row[1],
        "model_run_id": row[2],
        "eval_run_id": row[3],
        "admission": row[4],
        "admission_score": float(row[5] or 0),
        "reason": row[6],
        "annual_return": float(row[7] or 0),
        "total_return": float(row[8] or 0),
        "max_drawdown": float(row[9] or 0),
        "sharpe": float(row[10] or 0),
        "passed": bool(row[11]),
        "updated_at": row[12],
    }


def explored_count(model_run_id: str) -> int:
    with write_transaction() as conn:
        if not table_exists(conn, "factor_autotune_trials"):
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM factor_autotune_trials WHERE model_run_id = ?",
            (model_run_id,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def run_autotune(args: argparse.Namespace, model: dict[str, Any], cycle: int) -> dict[str, Any]:
    autotune_run_id = f"{args.run_id}_c{cycle:03d}_{model['run_id'][:64]}"
    started = now_text()
    return {
        "autotune_run_id": autotune_run_id,
        "model_run_id": model["run_id"],
        "returncode": 2,
        "started_at": started,
        "finished_at": now_text(),
        "output_tail": "Legacy AutoTune has been removed from the desktop production training architecture; use Profit Arena training and the post-update factor snapshot instead.",
    }


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def model_priority(model: dict[str, Any]) -> tuple[int, float, str]:
    admission = latest_admission_for_model(model["run_id"])
    best = best_autotune_trial(model["run_id"])
    passed = 1 if best.get("passed") or str(admission.get("admission") or "") in PASS_ADMISSIONS else 0
    score = max(float(admission.get("admission_score") or 0), float(best.get("admission_score") or 0))
    explored = explored_count(model["run_id"])
    # Keep the search broad: under-explored small-cap base models get attention
    # before squeezing another tiny improvement out of an already saturated run.
    return (-passed, str(explored).zfill(8), -score)


def main() -> int:
    args = parse_args()
    if not args.allow_legacy_factor_model:
        print(json.dumps({
            "success": False,
            "error": "历史因子研究长跑搜索默认禁止运行；如需回看旧实验，请显式传 --allow-legacy-factor-model",
        }, ensure_ascii=False))
        return 2
    run_status.begin(TASK_NAME)
    summary_path = ROOT / "logs" / "longrun" / f"{args.run_id}.summary.json"
    log_path = ROOT / "logs" / "longrun" / f"{args.run_id}.events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    best_seen: dict[str, Any] = best_autotune_trial()
    try:
        for cycle in range(1, int(args.max_cycles) + 1):
            models = successful_models(args.base_model_run_id.strip())
            if not models:
                raise RuntimeError("no successful factor model runs found")
            models = sorted(models, key=model_priority)
            model = models[(cycle - 1) % len(models)]
            run_status.progress(
                TASK_NAME,
                cycle,
                int(args.max_cycles),
                "autotune",
                f"{model['run_id']} explored={explored_count(model['run_id'])}",
            )
            event = {
                "event": "cycle_start",
                "cycle": cycle,
                "model": model,
                "latest_admission": latest_admission_for_model(model["run_id"]),
                "best_before": best_autotune_trial(model["run_id"]),
                "started_at": now_text(),
            }
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

            result = run_autotune(args, model, cycle)
            current_best = best_autotune_trial(model["run_id"])
            global_best = best_autotune_trial()
            if not best_seen or float(global_best.get("admission_score") or 0) >= float(best_seen.get("admission_score") or 0):
                best_seen = global_best
            payload = {
                "run_id": args.run_id,
                "state": "running",
                "cycle": cycle,
                "model_count": len(models),
                "last_model": model,
                "last_autotune": result,
                "current_model_best": current_best,
                "global_best": best_seen,
                "updated_at": now_text(),
            }
            write_summary(summary_path, payload)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "cycle_done", **payload}, ensure_ascii=False, default=str) + "\n")
            if args.stop_on_pass and best_seen.get("passed"):
                payload["state"] = "success"
                payload["reason"] = "found_passed_trial"
                write_summary(summary_path, payload)
                run_status.done(TASK_NAME, "找到通过准入的历史因子研究候选")
                return 0
            time.sleep(max(0, int(args.sleep_seconds)))
    except Exception as exc:
        payload = {
            "run_id": args.run_id,
            "state": "error",
            "error": str(exc),
            "best": best_seen,
            "updated_at": now_text(),
        }
        write_summary(summary_path, payload)
        run_status.error(TASK_NAME, str(exc))
        raise
    run_status.done(TASK_NAME, "最优模型搜索达到最大循环次数")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
