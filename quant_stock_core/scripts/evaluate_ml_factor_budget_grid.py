"""Parallel budget grid evaluator for ml_factor_ranker.

This script does not train a new model. It searches portfolio construction
parameters around the active factor model and records each trial in
eval_strategy_admission for normal admission comparison.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config.desktop_settings import load_strategy_settings


def parse_csv_floats(raw: str) -> list[float]:
    out: list[float] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def parse_csv_ints(raw: str) -> list[int]:
    return [int(value) for value in parse_csv_floats(raw)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="20100101")
    parser.add_argument("--end", default="20260612")
    parser.add_argument("--run-prefix", default=f"budget_grid_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--ranks", default="0.945,0.95,0.955")
    parser.add_argument("--holdings", default="18,20,22")
    parser.add_argument("--single-weights", default="0.064,0.066,0.0665,0.067,0.068,0.07")
    parser.add_argument("--industry-weights", default="0.14,0.16,0.18")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_trials(args: argparse.Namespace) -> list[dict[str, Any]]:
    ranks = parse_csv_floats(args.ranks)
    holdings = parse_csv_ints(args.holdings)
    singles = parse_csv_floats(args.single_weights)
    industries = parse_csv_floats(args.industry_weights)
    trials: list[dict[str, Any]] = []
    idx = 1
    for rank in ranks:
        for holding in holdings:
            for single in singles:
                for industry in industries:
                    trials.append({
                        "trial_no": idx,
                        "eval_run_id": f"{args.run_prefix}_{idx:03d}",
                        "min_pred_rank": rank,
                        "n_holdings": holding,
                        "max_single_weight": single,
                        "max_industry_weight": industry,
                    })
                    idx += 1
    if args.limit and args.limit > 0:
        return trials[: int(args.limit)]
    return trials


def run_trial(base_cfg: dict[str, Any], args_dict: dict[str, Any], trial: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(base_cfg)
    cfg.setdefault("selection", {})["min_pred_rank"] = float(trial["min_pred_rank"])
    cfg.setdefault("position", {})["n_holdings"] = int(trial["n_holdings"])
    cfg["position"]["max_single_weight"] = float(trial["max_single_weight"])
    cfg["position"]["max_industry_weight"] = float(trial["max_industry_weight"])
    cfg.setdefault("filters", {}).pop("crash_warning_candidates", None)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["QUANT_STRATEGY_OVERRIDES_JSON"] = json.dumps({"ml_factor_ranker": cfg}, ensure_ascii=False)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "evaluate_strategies.py"),
        "--start",
        str(args_dict["start"]),
        "--end",
        str(args_dict["end"]),
        "--strategies",
        "ml_factor_ranker",
        "--baseline",
        "small_cap_quality",
        "--save",
        str(trial["eval_run_id"]),
        "--strategy-version-mode",
        "active",
        "--json",
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT.parent), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = dict(trial)
    result["returncode"] = proc.returncode
    if proc.returncode != 0:
        result["error"] = (proc.stderr or proc.stdout)[-2000:]
        return result
    try:
        payload = json.loads(proc.stdout)
        row = (payload.get("rows") or [{}])[0]
    except Exception as exc:
        result["error"] = f"parse output failed: {exc}"
        result["stdout_tail"] = proc.stdout[-2000:]
        return result
    for key in [
        "admission", "admission_score", "annual_return", "total_return",
        "max_drawdown", "sharpe", "avg_holdings", "avg_turnover",
        "monthly_win_rate", "positive_3m_rate", "worst_month_return",
        "reason",
    ]:
        result[key] = row.get(key)
    return result


def sort_key(row: dict[str, Any]) -> tuple[float, float, float]:
    return (
        float(row.get("admission_score") or -999),
        float(row.get("sharpe") or -999),
        float(row.get("annual_return") or -999),
    )


def main() -> int:
    args = parse_args()
    base_cfg = load_strategy_settings().get("ml_factor_ranker") or {}
    trials = build_trials(args)
    args_dict = {"start": args.start, "end": args.end}
    results: list[dict[str, Any]] = []
    executor = futures.ProcessPoolExecutor(max_workers=max(1, int(args.workers)))
    try:
        future_map = {executor.submit(run_trial, base_cfg, args_dict, trial): trial for trial in trials}
        for future in futures.as_completed(future_map):
            result = future.result()
            results.append(result)
            if not args.json:
                print(format_row(result), flush=True)
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True, cancel_futures=False)
    results.sort(key=sort_key, reverse=True)
    if args.json:
        print(json.dumps({"count": len(results), "best": results[:10], "results": results}, ensure_ascii=False, indent=2))
    else:
        print("\nBEST", flush=True)
        for row in results[:10]:
            print(format_row(row), flush=True)
    return 0 if results and not results[0].get("error") else 1


def format_row(row: dict[str, Any]) -> str:
    if row.get("error"):
        return f"{row['eval_run_id']} ERROR {row.get('error')}"
    return (
        f"{row['eval_run_id']} score={float(row.get('admission_score') or 0):.2f} "
        f"admission={row.get('admission')} rank={row.get('min_pred_rank')} "
        f"hold={row.get('n_holdings')} single={row.get('max_single_weight')} "
        f"industry={row.get('max_industry_weight')} annual={float(row.get('annual_return') or 0):.4f} "
        f"dd={float(row.get('max_drawdown') or 0):.4f} sharpe={float(row.get('sharpe') or 0):.3f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
