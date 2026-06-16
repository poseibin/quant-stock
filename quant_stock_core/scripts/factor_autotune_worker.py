from __future__ import annotations

import argparse
import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request, error

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config.desktop_settings import load_strategy, load_strategy_settings
from common.infra import status as run_status
from common.infra.db import replace_sql, table_exists, upsert_sql, write_transaction
from scripts import evaluate_strategies


TASK_NAME = "factor_autotune"
STRATEGY = "ml_factor_ranker"
ALLOWED_ADMISSIONS = {"可启用", "限制启用", "已启用"}
DEFAULT_MAX_ROUNDS = 12
DEFAULT_TRIALS_PER_ROUND = 6
MAX_ROUNDS_CAP = 30
TRIALS_PER_ROUND_CAP = 12

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "selection.min_pred_rank": (0.94, 0.99),
    "position.n_holdings": (8, 40),
    "position.max_single_weight": (0.015, 0.20),
    "position.max_industry_weight": (0.06, 0.20),
    "filters.market_regime.risk_state.weak_exposure": (0.05, 0.35),
    "filters.market_regime.risk_state.post_crash_repair_exposure": (0.0, 0.60),
    "filters.market_regime.risk_state.crash_exposure": (0.0, 0.10),
    "filters.market_regime.risk_state.liquidity_squeeze_exposure": (0.0, 0.10),
    "filters.market_regime.weak_exposure": (0.05, 0.35),
    "filters.market_regime.bear_exposure": (0.0, 0.20),
    "filters.market_regime.crisis_exposure": (0.0, 0.10),
    "filters.stress_controls.stress_min_amount_mult": (1.0, 3.0),
    "filters.stress_controls.max_ret20": (0.08, 0.35),
    "filters.stress_controls.max_vol20": (0.30, 0.80),
    "filters.stress_controls.max_amount_chg20": (1.0, 4.0),
    "filters.stress_controls.max_turnover_rate": (6.0, 20.0),
    "filters.stress_controls.ret20_penalty": (0.05, 0.50),
    "filters.stress_controls.vol20_penalty": (0.04, 0.25),
    "filters.stress_controls.turnover_penalty": (0.04, 0.25),
    "filters.stress_controls.weak_base_penalty": (0.0, 0.10),
    "filters.stress_controls.crash_drawdown_penalty": (0.05, 0.35),
    "filters.index_anchor_warning.lookback_days": (3, 20),
    "filters.index_anchor_warning.warning_exposure": (0.0, 0.75),
    "filters.index_anchor_warning.severe_exposure": (0.0, 0.25),
    "filters.index_anchor_warning.repair_exposure": (0.0, 0.75),
    "filters.index_anchor_warning.ret5_warning": (-0.070, -0.015),
    "filters.index_anchor_warning.ret5_severe": (-0.100, -0.030),
    "filters.index_anchor_warning.ret20_warning": (-0.140, -0.030),
    "filters.index_anchor_warning.ret20_severe": (-0.220, -0.060),
    "filters.index_anchor_warning.drawdown20_warning": (-0.160, -0.030),
    "filters.index_anchor_warning.drawdown20_severe": (-0.260, -0.080),
    "filters.index_anchor_warning.rel20_warning": (-0.140, -0.020),
    "filters.index_anchor_warning.rel20_severe": (-0.220, -0.050),
    "filters.index_anchor_warning.ret5_overheat": (0.06, 0.25),
    "filters.index_anchor_warning.ret20_overheat": (0.12, 0.50),
    "filters.index_anchor_warning.overheat_exposure": (0.0, 0.80),
    "filters.index_anchor_warning.overheat_cooldown_days": (1, 15),
    "filters.index_anchor_warning.risk_score_warning": (10, 45),
    "filters.index_anchor_warning.risk_score_severe": (25, 75),
    "filters.index_anchor_warning.cooldown_days": (1, 20),
    "filters.index_anchor_warning.severe_cooldown_days": (2, 35),
    "filters.index_anchor_warning.recovery_days": (0, 15),
    "filters.crash_gate.lookback_days": (5, 40),
    "filters.crash_gate.cooldown_days": (1, 30),
    "filters.crash_gate.cash_exposure": (0.0, 0.30),
    "filters.crash_exit.cooldown_days": (1, 30),
    "filters.crash_exit.lookback_days": (1, 20),
    "filters.crash_exit.exit_exposure": (0.0, 0.30),
    "filters.crash_exit.liquidity_squeeze_exposure": (0.0, 0.40),
    "filters.crash_exit.min_exit_days": (0, 20),
    "filters.crash_exit.max_exit_days": (1, 60),
    "filters.crash_warning_model.warning_threshold": (0.50, 0.95),
    "filters.crash_warning_model.severe_threshold": (0.60, 0.99),
    "filters.crash_warning_model.warning_exposure": (0.30, 1.0),
    "filters.crash_warning_model.severe_exposure": (0.05, 0.80),
    "filters.crash_warning_model.cooldown_days": (1, 20),
    "filters.crash_warning_model.severe_cooldown_days": (2, 35),
    "filters.crash_warning_model.pre_warning_threshold": (0.50, 0.95),
    "filters.crash_warning_model.pre_warning_min_days": (1, 4),
    "filters.crash_warning_model.pre_warning_exposure": (0.0, 1.0),
    "filters.crash_warning_model.pre_warning_cooldown_days": (3, 30),
    "filters.crash_warning_model.overheat_prob_threshold": (0.25, 0.95),
    "filters.crash_warning_model.overheat_ret20": (0.12, 0.45),
    "filters.crash_warning_model.overheat_breadth20": (0.45, 0.70),
    "filters.crash_warning_model.overheat_exposure": (0.0, 1.0),
    "filters.crash_warning_model.overheat_cooldown_days": (3, 30),
    "filters.crash_warning_model.weak_prob_threshold": (0.25, 0.95),
    "filters.crash_warning_model.weak_ret5": (-0.080, -0.005),
    "filters.crash_warning_model.weak_breadth20": (0.35, 0.55),
    "filters.crash_warning_model.weak_exposure": (0.0, 1.0),
    "filters.crash_warning_model.weak_cooldown_days": (3, 30),
}

INT_PARAMS = {
    "position.n_holdings",
    "filters.crash_gate.lookback_days",
    "filters.crash_gate.cooldown_days",
    "filters.index_anchor_warning.lookback_days",
    "filters.index_anchor_warning.cooldown_days",
    "filters.index_anchor_warning.severe_cooldown_days",
    "filters.index_anchor_warning.recovery_days",
    "filters.index_anchor_warning.overheat_cooldown_days",
    "filters.crash_exit.cooldown_days",
    "filters.crash_exit.lookback_days",
    "filters.crash_exit.min_exit_days",
    "filters.crash_exit.max_exit_days",
    "filters.crash_warning_model.cooldown_days",
    "filters.crash_warning_model.severe_cooldown_days",
    "filters.crash_warning_model.pre_warning_min_days",
    "filters.crash_warning_model.pre_warning_cooldown_days",
    "filters.crash_warning_model.overheat_cooldown_days",
    "filters.crash_warning_model.weak_cooldown_days",
}

BOOLEAN_PARAMS = {
    "filters.stress_controls.enabled",
    "filters.crash_gate.enabled",
    "filters.crash_gate.hold_previous",
    "filters.crash_exit.enabled",
    "filters.crash_warning_model.enabled",
    "filters.index_anchor_warning.enabled",
    "filters.market_regime.daily_risk_overlay",
    "filters.market_regime.risk_state.enabled",
    "filters.market_regime.risk_state_only",
}

CATEGORICAL_PARAMS: dict[str, set[str]] = {
    "filters.crash_gate.mode": {"cash", "skip_rebalance", "recovery_confirm"},
    "filters.crash_warning_model.prob_column": {
        "shock_prob",
        "market_risk_prob",
        "smallcap_ecology_risk_prob",
        "style_shift_prob",
        "liquidity_squeeze_prob",
        "final_smallcap_risk",
    },
}

STRING_PARAMS = {
    "filters.crash_warning_model.run_id",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    cur = data
    parts = path.split(".")
    for part in parts[:-1]:
        next_value = cur.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cur[part] = next_value
        cur = next_value
    cur[parts[-1]] = value


def clamp_param(path: str, value: Any) -> Any:
    if path in BOOLEAN_PARAMS:
        return bool(value)
    if path in CATEGORICAL_PARAMS:
        text = str(value or "").strip()
        allowed = CATEGORICAL_PARAMS[path]
        return text if text in allowed else sorted(allowed)[0]
    if path in STRING_PARAMS:
        return str(value or "").strip()
    if path not in PARAM_BOUNDS:
        return value
    low, high = PARAM_BOUNDS[path]
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = low
    numeric = max(low, min(high, numeric))
    if path in INT_PARAMS:
        return int(round(numeric))
    return round(float(numeric), 6)


def sanitize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in flatten_patch(patch).items():
        if path in PARAM_BOUNDS or path in BOOLEAN_PARAMS or path in CATEGORICAL_PARAMS or path in STRING_PARAMS:
            set_path(out, path, clamp_param(path, value))
    return out


def param_key(patch: dict[str, Any]) -> str:
    normalized = sanitize_patch(patch)
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def flatten_patch(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (data or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten_patch(value, path))
        else:
            out[path] = value
    return out


def patch_from_flat(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in values.items():
        if path in PARAM_BOUNDS or path in BOOLEAN_PARAMS or path in CATEGORICAL_PARAMS or path in STRING_PARAMS:
            set_path(out, path, clamp_param(path, value))
    return out


def ensure_tables() -> None:
    with write_transaction() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS factor_autotune_runs (
                run_id VARCHAR(255) PRIMARY KEY,
                base_model_run_id VARCHAR(255) NOT NULL,
                start_date VARCHAR(16) NOT NULL,
                end_date VARCHAR(16) NOT NULL,
                status VARCHAR(32) NOT NULL,
                best_trial_id VARCHAR(255) NOT NULL DEFAULT '',
                best_model_run_id VARCHAR(255) NOT NULL DEFAULT '',
                best_admission VARCHAR(64) NOT NULL DEFAULT '',
                best_score DOUBLE,
                summary_json LONGTEXT NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS factor_autotune_trials (
                run_id VARCHAR(255) NOT NULL,
                trial_id VARCHAR(255) NOT NULL,
                round_no BIGINT NOT NULL DEFAULT 0,
                source VARCHAR(64) NOT NULL DEFAULT '',
                model_run_id VARCHAR(255) NOT NULL DEFAULT '',
                eval_run_id VARCHAR(255) NOT NULL DEFAULT '',
                params_json LONGTEXT NOT NULL,
                llm_direction_json LONGTEXT NOT NULL,
                admission VARCHAR(64) NOT NULL DEFAULT '',
                admission_score DOUBLE,
                reason LONGTEXT NOT NULL,
                annual_return DOUBLE,
                total_return DOUBLE,
                max_drawdown DOUBLE,
                sharpe DOUBLE,
                stress_bad_event_count BIGINT NOT NULL DEFAULT 0,
                stress_crash_state_failed BIGINT NOT NULL DEFAULT 0,
                stress_weak_drawdown_failed BIGINT NOT NULL DEFAULT 0,
                passed BIGINT NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(run_id, trial_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_autotune_trials_run_round ON factor_autotune_trials(run_id, round_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_autotune_trials_passed ON factor_autotune_trials(passed)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_autotune_trials_score ON factor_autotune_trials(admission_score)")


def latest_model_run_id() -> str:
    with write_transaction() as conn:
        row = conn.execute(
            "SELECT run_id FROM factor_model_runs WHERE status = ? ORDER BY updated_at DESC LIMIT 1",
            ("success",),
        ).fetchone()
    return str(row[0]) if row and row[0] else ""


def latest_admission(base_model_run_id: str) -> dict[str, Any]:
    eval_id = f"eval_{base_model_run_id}"
    with write_transaction() as conn:
        if not table_exists(conn, "eval_strategy_admission"):
            return {}
        row = conn.execute(
            """
            SELECT run_id, admission, COALESCE(admission_score, 0), COALESCE(reason, ''),
                   COALESCE(annual_return, 0), COALESCE(total_return, 0), COALESCE(max_drawdown, 0),
                   COALESCE(sharpe, 0), COALESCE(effective_start, ''), COALESCE(effective_end, ''),
                   COALESCE(JSON_EXTRACT(payload_json, '$.stress_bad_event_count') + 0, 0),
                   COALESCE(JSON_EXTRACT(payload_json, '$.stress_crash_state_failed') + 0, 0),
                   COALESCE(JSON_EXTRACT(payload_json, '$.stress_weak_drawdown_failed') + 0, 0),
                   COALESCE(payload_json, '{}')
            FROM eval_strategy_admission
            WHERE strategy = ? AND (run_id = ? OR run_id = ?)
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (STRATEGY, eval_id, base_model_run_id),
        ).fetchone()
    if not row:
        return {}
    return {
        "run_id": row[0],
        "admission": row[1],
        "admission_score": float(row[2] or 0),
        "reason": row[3],
        "annual_return": float(row[4] or 0),
        "total_return": float(row[5] or 0),
        "max_drawdown": float(row[6] or 0),
        "sharpe": float(row[7] or 0),
        "effective_start": row[8],
        "effective_end": row[9],
        "stress_bad_event_count": int(row[10] or 0),
        "stress_crash_state_failed": bool(int(row[11] or 0)),
        "stress_weak_drawdown_failed": bool(int(row[12] or 0)),
        "payload": parse_json(row[13], {}),
    }


def stress_rows(base_model_run_id: str) -> list[dict[str, Any]]:
    with write_transaction() as conn:
        if not table_exists(conn, "factor_model_stress_results"):
            return []
        rows = conn.execute(
            """
            SELECT bucket_type, bucket_key, bucket_label, start_date, end_date,
                   COALESCE(annual_return, 0), COALESCE(max_drawdown, 0), COALESCE(sharpe, 0), COALESCE(win_rate, 0)
            FROM factor_model_stress_results
            WHERE run_id = ?
            ORDER BY bucket_type, bucket_key
            """,
            (base_model_run_id,),
        ).fetchall()
    return [
        {
            "bucket_type": row[0],
            "bucket_key": row[1],
            "bucket_label": row[2],
            "start_date": row[3],
            "end_date": row[4],
            "annual_return": float(row[5] or 0),
            "max_drawdown": float(row[6] or 0),
            "sharpe": float(row[7] or 0),
            "win_rate": float(row[8] or 0),
        }
        for row in rows
    ]


def parse_json(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return default


def load_explored_param_keys(base_model_run_id: str, current_run_id: str = "") -> set[str]:
    with write_transaction() as conn:
        ensure_tables_in_conn(conn)
        rows = conn.execute(
            """
            SELECT COALESCE(params_json, '{}')
            FROM factor_autotune_trials
            WHERE COALESCE(params_json, '{}') <> '{}'
            """,
        ).fetchall()
    keys: set[str] = set()
    for row in rows:
        params = parse_json(row[0], {})
        if isinstance(params, dict):
            keys.add(param_key(params))
    return keys


def load_historical_trials(base_model_run_id: str, current_run_id: str = "", limit: int = 180) -> list[dict[str, Any]]:
    with write_transaction() as conn:
        ensure_tables_in_conn(conn)
        rows = conn.execute(
            """
            SELECT run_id, trial_id, round_no, source, model_run_id, COALESCE(params_json, '{}'),
                   COALESCE(admission, ''), COALESCE(admission_score, 0),
                   COALESCE(reason, ''), COALESCE(annual_return, 0),
                   COALESCE(total_return, 0), COALESCE(max_drawdown, 0),
                   COALESCE(sharpe, 0), COALESCE(stress_bad_event_count, 0),
                   COALESCE(stress_crash_state_failed, 0),
                   COALESCE(stress_weak_drawdown_failed, 0),
                   COALESCE(passed, 0), updated_at
            FROM factor_autotune_trials
            ORDER BY passed DESC, admission_score DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        params = parse_json(row[5], {})
        item = {
            "run_id": row[0],
            "trial_id": row[1],
            "round_no": int(row[2] or 0),
            "source": row[3],
            "model_run_id": row[4],
            "params": params if isinstance(params, dict) else {},
            "admission": row[6],
            "admission_score": float(row[7] or 0),
            "reason": row[8],
            "annual_return": float(row[9] or 0),
            "total_return": float(row[10] or 0),
            "max_drawdown": float(row[11] or 0),
            "sharpe": float(row[12] or 0),
            "stress_bad_event_count": int(row[13] or 0),
            "stress_crash_state_failed": bool(row[14]),
            "stress_weak_drawdown_failed": bool(row[15]),
            "passed": bool(row[16]),
            "updated_at": row[17],
        }
        item["score"] = trial_score(item)
        out.append(item)
    return out


def filter_unexplored(candidates: list[dict[str, Any]], explored_keys: set[str], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = sanitize_patch(candidate)
        key = param_key(candidate)
        if key in explored_keys:
            continue
        explored_keys.add(key)
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def historical_trial_context(trials: list[dict[str, Any]], limit: int = 40) -> dict[str, Any]:
    ordered = sorted(trials, key=trial_score, reverse=True)
    failed_reasons: dict[str, int] = {}
    for row in trials:
        reason = str(row.get("reason") or "").strip()[:80] or "未记录"
        failed_reasons[reason] = failed_reasons.get(reason, 0) + 1
    return {
        "explored_count": len(trials),
        "passed_count": sum(1 for row in trials if row.get("passed")),
        "best_trials": [compact_trial(row) for row in ordered[: min(8, len(ordered))]],
        "worst_trials": [compact_trial(row) for row in sorted(trials, key=trial_score)[: min(5, len(trials))]],
        "recent_trials": [compact_trial(row) for row in trials[:limit]],
        "top_failed_reasons": sorted(
            [{"reason": reason, "count": count} for reason, count in failed_reasons.items()],
            key=lambda item: item["count"],
            reverse=True,
        )[:10],
    }


def historical_seed_candidates(trials: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for trial in sorted(trials, key=trial_score, reverse=True):
        params = trial.get("params")
        if isinstance(params, dict) and params:
            seeds.append(sanitize_patch(params))
        if len(seeds) >= 6:
            break

    candidates: list[dict[str, Any]] = []
    for seed in seeds:
        candidates.append(seed)
        rank = get_path(seed, "selection.min_pred_rank")
        if rank is not None:
            rank = float(rank)
            for delta in (-0.005, 0.005, 0.010):
                variant = deepcopy(seed)
                set_path(variant, "selection.min_pred_rank", rank + delta)
                candidates.append(sanitize_patch(variant))
        holdings = get_path(seed, "position.n_holdings")
        if holdings is not None:
            holdings = int(holdings)
            for delta in (-4, 4):
                variant = deepcopy(seed)
                set_path(variant, "position.n_holdings", holdings + delta)
                candidates.append(sanitize_patch(variant))
        weak = get_path(seed, "filters.market_regime.risk_state.weak_exposure")
        if weak is not None:
            weak = float(weak)
            for delta in (-0.04, 0.04, 0.08):
                variant = deepcopy(seed)
                set_path(variant, "filters.market_regime.risk_state.weak_exposure", weak + delta)
                set_path(variant, "filters.market_regime.weak_exposure", weak + delta)
                candidates.append(sanitize_patch(variant))
        penalty = get_path(seed, "filters.stress_controls.crash_drawdown_penalty")
        if penalty is not None:
            penalty = float(penalty)
            for delta in (-0.04, 0.04):
                variant = deepcopy(seed)
                set_path(variant, "filters.stress_controls.crash_drawdown_penalty", penalty + delta)
                candidates.append(sanitize_patch(variant))
        max_exit = get_path(seed, "filters.crash_exit.max_exit_days")
        if max_exit is not None:
            max_exit = int(max_exit)
            for delta in (-4, 4, 8):
                variant = deepcopy(seed)
                set_path(variant, "filters.crash_exit.max_exit_days", max_exit + delta)
                candidates.append(sanitize_patch(variant))
        anchor_exposure = get_path(seed, "filters.index_anchor_warning.warning_exposure")
        if anchor_exposure is not None:
            anchor_exposure = float(anchor_exposure)
            for delta in (-0.08, 0.08):
                variant = deepcopy(seed)
                set_path(variant, "filters.index_anchor_warning.enabled", True)
                set_path(variant, "filters.index_anchor_warning.warning_exposure", anchor_exposure + delta)
                candidates.append(sanitize_patch(variant))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = param_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return deduped


def generate_rule_candidates(base_cfg: dict[str, Any], admission: dict[str, Any], limit: int, round_no: int = 1) -> list[dict[str, Any]]:
    reason = str(admission.get("reason") or "")
    annual = float(admission.get("annual_return") or 0)
    drawdown = float(admission.get("max_drawdown") or 0)
    status = str(admission.get("admission") or "")
    current_rank = float(get_path(base_cfg, "selection.min_pred_rank", 0.96) or 0.96)
    current_n = int(get_path(base_cfg, "position.n_holdings", 24) or 24)
    current_single = float(get_path(base_cfg, "position.max_single_weight", 0.035) or 0.035)
    current_industry = float(get_path(base_cfg, "position.max_industry_weight", 0.12) or 0.12)
    current_risk_run_id = str(get_path(base_cfg, "filters.crash_warning_model.run_id", "") or "")
    current_prob_column = str(get_path(base_cfg, "filters.crash_warning_model.prob_column", "shock_prob") or "shock_prob")

    candidates: list[dict[str, Any]] = []

    defensive_base = {
        "selection.min_pred_rank": max(current_rank, 0.97),
        "position.n_holdings": min(current_n, 20),
        "position.max_single_weight": min(current_single, 0.03),
        "position.max_industry_weight": min(current_industry, 0.10),
        "filters.stress_controls.enabled": True,
        "filters.crash_gate.enabled": True,
        "filters.crash_exit.enabled": True,
        "filters.market_regime.risk_state.weak_exposure": 0.18,
        "filters.market_regime.risk_state.crash_exposure": 0.0,
        "filters.market_regime.risk_state.liquidity_squeeze_exposure": 0.0,
        "filters.market_regime.weak_exposure": 0.18,
        "filters.market_regime.bear_exposure": 0.05,
        "filters.market_regime.crisis_exposure": 0.0,
        "filters.stress_controls.stress_min_amount_mult": 2.0,
        "filters.stress_controls.max_ret20": 0.16,
        "filters.stress_controls.max_vol20": 0.50,
        "filters.stress_controls.max_turnover_rate": 10.0,
        "filters.stress_controls.weak_base_penalty": 0.04,
        "filters.stress_controls.crash_drawdown_penalty": 0.22,
        "filters.index_anchor_warning.enabled": True,
        "filters.index_anchor_warning.lookback_days": 8,
        "filters.index_anchor_warning.warning_exposure": 0.35,
        "filters.index_anchor_warning.severe_exposure": 0.0,
        "filters.index_anchor_warning.repair_exposure": 0.30,
        "filters.index_anchor_warning.ret5_warning": -0.035,
        "filters.index_anchor_warning.ret5_severe": -0.055,
        "filters.index_anchor_warning.ret20_warning": -0.060,
        "filters.index_anchor_warning.ret20_severe": -0.100,
        "filters.index_anchor_warning.drawdown20_warning": -0.080,
        "filters.index_anchor_warning.drawdown20_severe": -0.140,
        "filters.index_anchor_warning.rel20_warning": -0.050,
        "filters.index_anchor_warning.rel20_severe": -0.085,
        "filters.index_anchor_warning.ret5_overheat": 0.12,
        "filters.index_anchor_warning.ret20_overheat": 0.28,
        "filters.index_anchor_warning.overheat_exposure": 0.35,
        "filters.index_anchor_warning.overheat_cooldown_days": 3,
        "filters.index_anchor_warning.risk_score_warning": 22.0,
        "filters.index_anchor_warning.risk_score_severe": 45.0,
        "filters.index_anchor_warning.cooldown_days": 5,
        "filters.index_anchor_warning.severe_cooldown_days": 10,
        "filters.index_anchor_warning.recovery_days": 3,
        "filters.crash_gate.lookback_days": 20,
        "filters.crash_gate.cooldown_days": 12,
        "filters.crash_gate.mode": "recovery_confirm",
        "filters.crash_gate.hold_previous": False,
        "filters.crash_gate.cash_exposure": 0.0,
        "filters.crash_exit.cooldown_days": 12,
        "filters.crash_exit.lookback_days": 5,
        "filters.crash_exit.exit_exposure": 0.0,
        "filters.crash_exit.liquidity_squeeze_exposure": 0.0,
        "filters.crash_exit.min_exit_days": 2,
        "filters.crash_exit.max_exit_days": 12,
        "filters.crash_warning_model.enabled": True,
        "filters.crash_warning_model.run_id": current_risk_run_id,
        "filters.crash_warning_model.prob_column": current_prob_column,
        "filters.crash_warning_model.warning_threshold": 0.70,
        "filters.crash_warning_model.severe_threshold": 0.88,
        "filters.crash_warning_model.warning_exposure": 0.70,
        "filters.crash_warning_model.severe_exposure": 0.25,
        "filters.crash_warning_model.cooldown_days": 3,
        "filters.crash_warning_model.severe_cooldown_days": 8,
        "filters.crash_warning_model.pre_warning_threshold": 0.68,
        "filters.crash_warning_model.pre_warning_min_days": 1,
        "filters.crash_warning_model.pre_warning_exposure": 0.0,
        "filters.crash_warning_model.pre_warning_cooldown_days": 12,
        "filters.crash_warning_model.overheat_prob_threshold": 0.35,
        "filters.crash_warning_model.overheat_ret20": 0.26,
        "filters.crash_warning_model.overheat_breadth20": 0.54,
        "filters.crash_warning_model.overheat_exposure": 0.05,
        "filters.crash_warning_model.overheat_cooldown_days": 10,
        "filters.crash_warning_model.weak_prob_threshold": 0.45,
        "filters.crash_warning_model.weak_ret5": -0.02,
        "filters.crash_warning_model.weak_breadth20": 0.48,
        "filters.crash_warning_model.weak_exposure": 0.0,
        "filters.crash_warning_model.weak_cooldown_days": 12,
    }
    if current_risk_run_id and current_prob_column != "shock_prob":
        early_regime_grid = [
            (0.82, 0.94, 0.90, 0.55, 0.80, 0.70, 4, 8, 0.955, 28),
            (0.86, 0.96, 0.90, 0.50, 0.80, 0.65, 3, 7, 0.960, 32),
            (0.88, 0.97, 0.95, 0.60, 0.80, 0.70, 2, 6, 0.965, 28),
            (0.90, 0.98, 0.95, 0.65, 0.80, 0.75, 2, 5, 0.970, 24),
            (0.92, 0.985, 1.0, 0.70, 0.80, 0.80, 1, 4, 0.975, 24),
            (0.78, 0.93, 0.85, 0.45, 0.75, 0.60, 5, 10, 0.950, 32),
        ]
        for (
            warning_threshold,
            severe_threshold,
            warning_exposure,
            severe_exposure,
            pre_warning_threshold,
            weak_exposure,
            cooldown_days,
            severe_cooldown_days,
            rank,
            n_holdings,
        ) in early_regime_grid:
            candidates.append(patch_from_flat({
                **defensive_base,
                "selection.min_pred_rank": rank,
                "position.n_holdings": n_holdings,
                "position.max_single_weight": 0.04,
                "position.max_industry_weight": 0.20,
                "filters.market_regime.daily_risk_overlay": False,
                "filters.market_regime.risk_state.enabled": False,
                "filters.index_anchor_warning.enabled": False,
                "filters.crash_gate.enabled": False,
                "filters.crash_exit.enabled": False,
                "filters.crash_warning_model.enabled": True,
                "filters.crash_warning_model.run_id": current_risk_run_id,
                "filters.crash_warning_model.prob_column": current_prob_column,
                "filters.crash_warning_model.warning_threshold": warning_threshold,
                "filters.crash_warning_model.severe_threshold": severe_threshold,
                "filters.crash_warning_model.warning_exposure": warning_exposure,
                "filters.crash_warning_model.severe_exposure": severe_exposure,
                "filters.crash_warning_model.cooldown_days": cooldown_days,
                "filters.crash_warning_model.severe_cooldown_days": severe_cooldown_days,
                "filters.crash_warning_model.pre_warning_threshold": pre_warning_threshold,
                "filters.crash_warning_model.pre_warning_min_days": 2,
                "filters.crash_warning_model.pre_warning_exposure": min(warning_exposure, 0.80),
                "filters.crash_warning_model.pre_warning_cooldown_days": cooldown_days,
                "filters.crash_warning_model.weak_prob_threshold": warning_threshold,
                "filters.crash_warning_model.weak_ret5": -0.06,
                "filters.crash_warning_model.weak_breadth20": 0.42,
                "filters.crash_warning_model.weak_exposure": weak_exposure,
                "filters.crash_warning_model.weak_cooldown_days": cooldown_days,
                "filters.crash_warning_model.overheat_prob_threshold": 0.55,
                "filters.crash_warning_model.overheat_ret20": 0.30,
                "filters.crash_warning_model.overheat_breadth20": 0.62,
                "filters.crash_warning_model.overheat_exposure": 0.75,
                "filters.crash_warning_model.overheat_cooldown_days": 3,
            }))
    candidates.append(patch_from_flat(defensive_base))

    crash_cash_base = {
        **defensive_base,
        "filters.market_regime.daily_risk_overlay": True,
        "filters.index_anchor_warning.warning_exposure": 0.20,
        "filters.index_anchor_warning.severe_exposure": 0.0,
        "filters.index_anchor_warning.repair_exposure": 0.20,
        "filters.index_anchor_warning.cooldown_days": 8,
        "filters.index_anchor_warning.severe_cooldown_days": 16,
        "filters.market_regime.risk_state.enabled": True,
        "filters.market_regime.risk_state_only": True,
        "filters.market_regime.risk_state.weak_exposure": 0.08,
        "filters.market_regime.risk_state.post_crash_repair_exposure": 0.18,
        "filters.market_regime.risk_state.liquidity_squeeze_exposure": 0.0,
        "filters.market_regime.risk_state.crash_exposure": 0.0,
        "filters.market_regime.weak_exposure": 0.08,
        "filters.market_regime.bear_exposure": 0.0,
        "filters.market_regime.crisis_exposure": 0.0,
        "filters.crash_gate.mode": "cash",
        "filters.crash_gate.hold_previous": False,
        "filters.crash_gate.cash_exposure": 0.0,
        "filters.crash_gate.lookback_days": 5,
        "filters.crash_gate.cooldown_days": 3,
        "filters.crash_exit.lookback_days": 3,
        "filters.crash_exit.exit_exposure": 0.0,
        "filters.crash_exit.liquidity_squeeze_exposure": 0.0,
        "filters.crash_exit.min_exit_days": 2,
        "filters.crash_exit.max_exit_days": 25,
    }
    candidates.append(patch_from_flat(crash_cash_base))

    if "股灾" in reason or bool(admission.get("stress_crash_state_failed")):
        candidates.append(patch_from_flat({
            **defensive_base,
            "selection.min_pred_rank": max(current_rank, 0.975),
            "position.n_holdings": min(current_n, 16),
            "position.max_single_weight": min(current_single, 0.025),
            "filters.market_regime.daily_risk_overlay": True,
            "filters.index_anchor_warning.warning_exposure": 0.15,
            "filters.index_anchor_warning.severe_exposure": 0.0,
            "filters.index_anchor_warning.ret5_warning": -0.030,
            "filters.index_anchor_warning.ret5_severe": -0.050,
            "filters.index_anchor_warning.ret5_overheat": 0.10,
            "filters.index_anchor_warning.ret20_overheat": 0.24,
            "filters.index_anchor_warning.overheat_exposure": 0.20,
            "filters.index_anchor_warning.overheat_cooldown_days": 5,
            "filters.index_anchor_warning.cooldown_days": 10,
            "filters.index_anchor_warning.severe_cooldown_days": 20,
            "filters.market_regime.risk_state.weak_exposure": 0.14,
            "filters.market_regime.risk_state.crash_exposure": 0.0,
            "filters.stress_controls.max_vol20": 0.45,
            "filters.crash_gate.mode": "cash",
            "filters.crash_gate.hold_previous": False,
            "filters.crash_gate.cash_exposure": 0.0,
            "filters.crash_gate.lookback_days": 5,
            "filters.crash_gate.cooldown_days": 18,
            "filters.crash_exit.cooldown_days": 18,
            "filters.crash_exit.exit_exposure": 0.0,
        }))

    if "弱市" in reason or bool(admission.get("stress_weak_drawdown_failed")):
        candidates.append(patch_from_flat({
            **defensive_base,
            "filters.market_regime.daily_risk_overlay": True,
            "filters.market_regime.risk_state.enabled": True,
            "filters.index_anchor_warning.warning_exposure": 0.30,
            "filters.index_anchor_warning.repair_exposure": 0.35,
            "filters.index_anchor_warning.ret20_warning": -0.050,
            "filters.index_anchor_warning.rel20_warning": -0.040,
            "filters.market_regime.risk_state.weak_exposure": 0.10,
            "filters.market_regime.risk_state.post_crash_repair_exposure": 0.20,
            "filters.market_regime.weak_exposure": 0.10,
            "filters.stress_controls.stress_min_amount_mult": 2.4,
            "filters.stress_controls.max_ret20": 0.12,
            "filters.stress_controls.max_vol20": 0.42,
            "filters.stress_controls.max_turnover_rate": 8.0,
            "filters.stress_controls.weak_base_penalty": 0.07,
        }))

    if "压力段" in reason or int(admission.get("stress_bad_event_count") or 0) > 0:
        candidates.append(patch_from_flat({
            **defensive_base,
            "selection.min_pred_rank": max(current_rank, 0.98),
            "position.max_single_weight": min(current_single, 0.025),
            "position.max_industry_weight": min(current_industry, 0.08),
            "filters.market_regime.daily_risk_overlay": True,
            "filters.index_anchor_warning.warning_exposure": 0.15,
            "filters.index_anchor_warning.severe_exposure": 0.0,
            "filters.index_anchor_warning.risk_score_warning": 18.0,
            "filters.index_anchor_warning.risk_score_severe": 38.0,
            "filters.crash_gate.mode": "cash",
            "filters.crash_gate.hold_previous": False,
            "filters.crash_gate.cash_exposure": 0.0,
            "filters.stress_controls.ret20_penalty": 0.36,
            "filters.stress_controls.vol20_penalty": 0.18,
            "filters.stress_controls.turnover_penalty": 0.16,
        }))

    if annual < 0.04 and drawdown > -0.18 and "暂不启用" in status:
        candidates.append(patch_from_flat({
            "selection.min_pred_rank": min(current_rank, 0.955),
            "position.n_holdings": min(max(current_n + 4, 24), 32),
            "position.max_single_weight": min(max(current_single, 0.03), 0.04),
            "filters.market_regime.risk_state.weak_exposure": 0.22,
            "filters.market_regime.risk_state.crash_exposure": 0.0,
            "filters.stress_controls.enabled": True,
            "filters.crash_gate.enabled": True,
            "filters.crash_exit.enabled": True,
        }))

    if not reason or "样本期未生成持仓" in reason:
        candidates.append(patch_from_flat({
            "selection.min_pred_rank": min(current_rank, 0.95),
            "position.n_holdings": max(current_n, 28),
            "filters.stress_controls.max_vol20": 0.65,
            "filters.stress_controls.max_turnover_rate": 15.0,
            "filters.stress_controls.stress_min_amount_mult": 1.5,
        }))

    overheat_grid = [
        (0.20, 0.00, 15, 0.00),
        (0.22, 0.10, 12, 0.00),
        (0.24, 0.15, 10, 0.05),
        (0.28, 0.20, 8, 0.08),
        (0.32, 0.25, 6, 0.12),
        (0.35, 0.25, 5, 0.15),
        (0.38, 0.35, 5, 0.15),
    ]
    for idx, (ret20_overheat, overheat_exposure, overheat_cooldown, weak_exposure) in enumerate(overheat_grid):
        candidates.append(patch_from_flat({
            **defensive_base,
            "selection.min_pred_rank": [0.94, 0.95, 0.96][idx % 3],
            "position.n_holdings": [40, 36, 32][idx % 3],
            "position.max_single_weight": [0.05, 0.06, 0.06][idx % 3],
            "position.max_industry_weight": [0.20, 0.24, 0.24][idx % 3],
            "filters.market_regime.daily_risk_overlay": True,
            "filters.market_regime.risk_state.enabled": True,
            "filters.market_regime.risk_state.weak_exposure": weak_exposure,
            "filters.market_regime.risk_state.post_crash_repair_exposure": 0.80,
            "filters.market_regime.risk_state.crash_exposure": 0.0,
            "filters.market_regime.risk_state.liquidity_squeeze_exposure": 0.0,
            "filters.market_regime.weak_exposure": weak_exposure,
            "filters.market_regime.bear_exposure": 0.0,
            "filters.market_regime.crisis_exposure": 0.0,
            "filters.stress_controls.enabled": False,
            "filters.index_anchor_warning.enabled": True,
            "filters.index_anchor_warning.warning_exposure": 0.35,
            "filters.index_anchor_warning.severe_exposure": 0.0,
            "filters.index_anchor_warning.repair_exposure": 0.75,
            "filters.index_anchor_warning.ret5_warning": -0.040,
            "filters.index_anchor_warning.ret5_severe": -0.065,
            "filters.index_anchor_warning.ret20_warning": -0.080,
            "filters.index_anchor_warning.ret20_severe": -0.130,
            "filters.index_anchor_warning.drawdown20_warning": -0.100,
            "filters.index_anchor_warning.drawdown20_severe": -0.160,
            "filters.index_anchor_warning.rel20_warning": -0.070,
            "filters.index_anchor_warning.rel20_severe": -0.110,
            "filters.index_anchor_warning.ret5_overheat": 0.12,
            "filters.index_anchor_warning.ret20_overheat": ret20_overheat,
            "filters.index_anchor_warning.overheat_exposure": overheat_exposure,
            "filters.index_anchor_warning.overheat_cooldown_days": overheat_cooldown,
            "filters.index_anchor_warning.risk_score_warning": 32.0,
            "filters.index_anchor_warning.risk_score_severe": 55.0,
            "filters.index_anchor_warning.cooldown_days": 4,
            "filters.index_anchor_warning.severe_cooldown_days": 10,
            "filters.index_anchor_warning.recovery_days": 2,
            "filters.crash_gate.enabled": False,
            "filters.crash_exit.enabled": False,
        }))

    if current_risk_run_id and current_prob_column != "shock_prob":
        smallcap_regime_grid = [
            (0.82, 0.94, 0.90, 0.55, 0.80, 0.70, 4, 8),
            (0.86, 0.96, 0.90, 0.50, 0.80, 0.65, 3, 7),
            (0.88, 0.97, 0.95, 0.60, 0.80, 0.70, 2, 6),
            (0.90, 0.98, 0.95, 0.65, 0.80, 0.75, 2, 5),
            (0.92, 0.985, 1.0, 0.70, 0.80, 0.80, 1, 4),
            (0.78, 0.93, 0.85, 0.45, 0.75, 0.60, 5, 10),
        ]
        for idx, (
            warning_threshold,
            severe_threshold,
            warning_exposure,
            severe_exposure,
            pre_warning_threshold,
            weak_exposure,
            cooldown_days,
            severe_cooldown_days,
        ) in enumerate(smallcap_regime_grid):
            candidates.append(patch_from_flat({
                **defensive_base,
                "selection.min_pred_rank": [0.955, 0.96, 0.965][idx % 3],
                "position.n_holdings": [24, 28, 32][idx % 3],
                "position.max_single_weight": [0.035, 0.04, 0.045][idx % 3],
                "position.max_industry_weight": 0.20,
                "filters.market_regime.daily_risk_overlay": False,
                "filters.market_regime.risk_state.enabled": False,
                "filters.index_anchor_warning.enabled": False,
                "filters.stress_controls.enabled": True,
                "filters.crash_gate.enabled": False,
                "filters.crash_exit.enabled": False,
                "filters.crash_warning_model.enabled": True,
                "filters.crash_warning_model.run_id": current_risk_run_id,
                "filters.crash_warning_model.prob_column": current_prob_column,
                "filters.crash_warning_model.warning_threshold": warning_threshold,
                "filters.crash_warning_model.severe_threshold": severe_threshold,
                "filters.crash_warning_model.warning_exposure": warning_exposure,
                "filters.crash_warning_model.severe_exposure": severe_exposure,
                "filters.crash_warning_model.cooldown_days": cooldown_days,
                "filters.crash_warning_model.severe_cooldown_days": severe_cooldown_days,
                "filters.crash_warning_model.pre_warning_threshold": pre_warning_threshold,
                "filters.crash_warning_model.pre_warning_min_days": 2,
                "filters.crash_warning_model.pre_warning_exposure": min(warning_exposure, 0.80),
                "filters.crash_warning_model.pre_warning_cooldown_days": cooldown_days,
                "filters.crash_warning_model.weak_prob_threshold": warning_threshold,
                "filters.crash_warning_model.weak_ret5": -0.06,
                "filters.crash_warning_model.weak_breadth20": 0.42,
                "filters.crash_warning_model.weak_exposure": weak_exposure,
                "filters.crash_warning_model.weak_cooldown_days": cooldown_days,
                "filters.crash_warning_model.overheat_prob_threshold": 0.55,
                "filters.crash_warning_model.overheat_ret20": 0.30,
                "filters.crash_warning_model.overheat_breadth20": 0.62,
                "filters.crash_warning_model.overheat_exposure": 0.75,
                "filters.crash_warning_model.overheat_cooldown_days": 3,
            }))

    concentration_grid = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    for idx, max_single in enumerate(concentration_grid):
        candidates.append(patch_from_flat({
            **defensive_base,
            "selection.min_pred_rank": [0.98, 0.985][idx % 2],
            "position.n_holdings": 24,
            "position.max_single_weight": max_single,
            "position.max_industry_weight": 0.25,
            "filters.market_regime.daily_risk_overlay": True,
            "filters.market_regime.risk_state.enabled": True,
            "filters.market_regime.risk_state.weak_exposure": 0.05,
            "filters.market_regime.risk_state.post_crash_repair_exposure": 0.20,
            "filters.market_regime.risk_state.crash_exposure": 0.0,
            "filters.market_regime.risk_state.liquidity_squeeze_exposure": 0.0,
            "filters.market_regime.weak_exposure": 0.05,
            "filters.market_regime.bear_exposure": 0.0,
            "filters.market_regime.crisis_exposure": 0.0,
            "filters.stress_controls.enabled": True,
            "filters.stress_controls.crash_drawdown_penalty": 0.35,
            "filters.stress_controls.weak_base_penalty": 0.05,
            "filters.index_anchor_warning.enabled": True,
            "filters.index_anchor_warning.warning_exposure": [0.05, 0.10, 0.15][idx % 3],
            "filters.index_anchor_warning.severe_exposure": 0.0,
            "filters.index_anchor_warning.repair_exposure": 0.25,
            "filters.index_anchor_warning.ret5_warning": -0.025,
            "filters.index_anchor_warning.ret5_severe": -0.040,
            "filters.index_anchor_warning.ret20_warning": -0.045,
            "filters.index_anchor_warning.ret20_severe": -0.075,
            "filters.index_anchor_warning.drawdown20_warning": -0.060,
            "filters.index_anchor_warning.drawdown20_severe": -0.100,
            "filters.index_anchor_warning.rel20_warning": -0.035,
            "filters.index_anchor_warning.rel20_severe": -0.060,
            "filters.index_anchor_warning.ret5_overheat": 0.08,
            "filters.index_anchor_warning.ret20_overheat": 0.18,
            "filters.index_anchor_warning.overheat_exposure": [0.0, 0.05, 0.10][idx % 3],
            "filters.index_anchor_warning.overheat_cooldown_days": 8,
            "filters.index_anchor_warning.risk_score_warning": 14.0,
            "filters.index_anchor_warning.risk_score_severe": 30.0,
            "filters.index_anchor_warning.cooldown_days": 12,
            "filters.index_anchor_warning.severe_cooldown_days": 24,
            "filters.index_anchor_warning.recovery_days": 4,
            "filters.crash_gate.enabled": True,
            "filters.crash_gate.mode": "cash",
            "filters.crash_gate.hold_previous": False,
            "filters.crash_gate.cash_exposure": 0.0,
            "filters.crash_gate.lookback_days": 5,
            "filters.crash_gate.cooldown_days": 20,
            "filters.crash_exit.enabled": True,
            "filters.crash_exit.lookback_days": 3,
            "filters.crash_exit.cooldown_days": 20,
            "filters.crash_exit.exit_exposure": 0.0,
            "filters.crash_exit.liquidity_squeeze_exposure": 0.0,
            "filters.crash_exit.min_exit_days": 2,
            "filters.crash_exit.max_exit_days": 30,
        }))

    rank_grid = [0.95, 0.955, 0.96, 0.965, 0.97, 0.975, 0.98, 0.985, 0.99]
    holdings_grid = [12, 16, 20, 24, 28, 32, 36]
    single_grid = [0.02, 0.025, 0.03, 0.035, 0.04]
    weak_grid = [0.08, 0.10, 0.14, 0.18, 0.22, 0.28]
    cooldown_grid = [8, 12, 16, 20, 24]
    start_idx = max(0, round_no - 1) * max(1, limit)
    for offset in range(max(limit * 4, 16)):
        idx = start_idx + offset
        rank = max(current_rank, rank_grid[idx % len(rank_grid)]) if drawdown <= -0.18 else rank_grid[idx % len(rank_grid)]
        n_holdings = holdings_grid[(idx // len(rank_grid)) % len(holdings_grid)]
        max_single = single_grid[(idx // (len(rank_grid) * len(holdings_grid))) % len(single_grid)]
        weak_exposure = weak_grid[(idx // (len(rank_grid) * len(holdings_grid) * len(single_grid))) % len(weak_grid)]
        cooldown = cooldown_grid[(idx // (len(rank_grid) * len(holdings_grid) * len(single_grid) * len(weak_grid))) % len(cooldown_grid)]
        candidates.append(patch_from_flat({
            **defensive_base,
            "selection.min_pred_rank": rank,
            "position.n_holdings": n_holdings,
            "position.max_single_weight": max_single,
            "position.max_industry_weight": min(current_industry, max(max_single * 4, 0.08)),
            "filters.market_regime.daily_risk_overlay": idx % 2 == 0,
            "filters.index_anchor_warning.enabled": True,
            "filters.index_anchor_warning.warning_exposure": [0.15, 0.25, 0.35, 0.50][idx % 4],
            "filters.index_anchor_warning.severe_exposure": [0.0, 0.05, 0.10][idx % 3],
            "filters.index_anchor_warning.repair_exposure": [0.20, 0.35, 0.50][idx % 3],
            "filters.index_anchor_warning.ret5_warning": [-0.030, -0.035, -0.045][idx % 3],
            "filters.index_anchor_warning.ret5_severe": [-0.050, -0.060, -0.075][idx % 3],
            "filters.index_anchor_warning.ret5_overheat": [0.08, 0.12, 0.18][idx % 3],
            "filters.index_anchor_warning.ret20_overheat": [0.18, 0.28, 0.40][idx % 3],
            "filters.index_anchor_warning.overheat_exposure": [0.15, 0.30, 0.50][idx % 3],
            "filters.index_anchor_warning.overheat_cooldown_days": [2, 4, 6][idx % 3],
            "filters.index_anchor_warning.cooldown_days": max(3, cooldown // 2),
            "filters.index_anchor_warning.severe_cooldown_days": max(6, cooldown),
            "filters.market_regime.risk_state.enabled": True,
            "filters.market_regime.risk_state.weak_exposure": weak_exposure,
            "filters.market_regime.risk_state.post_crash_repair_exposure": min(0.35, weak_exposure + 0.10),
            "filters.market_regime.weak_exposure": weak_exposure,
            "filters.crash_gate.mode": "cash" if idx % 3 == 0 else "recovery_confirm",
            "filters.crash_gate.hold_previous": False,
            "filters.crash_gate.cash_exposure": 0.0,
            "filters.crash_gate.cooldown_days": cooldown,
            "filters.crash_exit.cooldown_days": cooldown,
            "filters.crash_exit.exit_exposure": 0.0,
            "filters.crash_exit.max_exit_days": max(8, cooldown + 8),
        }))

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = sanitize_patch(candidate)
        key = param_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return deduped


def deepseek_review(
    *,
    token: str,
    model: str,
    context: dict[str, Any],
    timeout: int = 90,
    opener: Any = None,
) -> dict[str, Any]:
    return llm_review(provider="deepseek", token=token, model=model, context=context, timeout=timeout, opener=opener)


def llm_review(
    *,
    provider: str,
    token: str,
    model: str,
    context: dict[str, Any],
    timeout: int = 90,
    opener: Any = None,
) -> dict[str, Any]:
    provider = normalize_llm_provider(provider)
    token = str(token or "").strip()
    if not token:
        return {"ok": False, "error": f"{provider.upper()} token is empty", "fallback": True, "provider": provider}
    endpoint = "https://api.deepseek.com/chat/completions" if provider == "deepseek" else "https://api.openai.com/v1/chat/completions"
    body: dict[str, Any] = {
        "model": model or default_llm_model(provider),
        "messages": [
            {"role": "system", "content": "你是中国A股量化策略研究员。只输出JSON，不要Markdown。你的建议只作为调参方向，不能绕过风控准入。"},
            {"role": "user", "content": deepseek_prompt(context)},
        ],
        "stream": False,
    }
    if provider == "deepseek":
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = "high"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        open_fn = opener.open if opener is not None else request.urlopen
        with open_fn(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}", "fallback": True, "provider": provider}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "fallback": True, "provider": provider}
    raw = extract_chat_content(raw_body)
    obj = parse_deepseek_json(raw)
    if not isinstance(obj, dict):
        label = "DeepSeek" if provider == "deepseek" else "OpenAI"
        return {"ok": False, "error": f"{label} returned non-JSON content", "raw": raw, "fallback": True, "provider": provider}
    sanitized = sanitize_deepseek_output(obj)
    sanitized["ok"] = True
    sanitized["raw"] = raw
    sanitized["provider"] = provider
    return sanitized


def normalize_llm_provider(provider: str) -> str:
    value = str(provider or "").strip().lower().replace("-", "_")
    if value in {"deepseek"}:
        return "deepseek"
    if value in {"openai", "chatgpt", "chat_gpt", "gpt"}:
        return "openai"
    return "openai"


def default_llm_model(provider: str) -> str:
    return "deepseek-v4-pro" if normalize_llm_provider(provider) == "deepseek" else "gpt-5.5"


def extract_chat_content(raw_body: str) -> str:
    try:
        parsed = json.loads(raw_body)
        return str(parsed.get("choices", [{}])[0].get("message", {}).get("content") or "")
    except Exception:
        return raw_body


def deepseek_prompt(context: dict[str, Any]) -> str:
    schema = {
        "analysis_md": "800字以内中文复盘，引用输入指标",
        "diagnosis": ["失败或改善原因"],
        "next_direction": ["下一轮方向"],
        "parameter_intents": [{"path": "selection.min_pred_rank", "action": "increase|decrease|set", "value": 0.97, "reason": "为什么"}],
        "risks": ["风险提示"],
        "validation_plan": ["下一轮必须验证什么"],
    }
    return (
        "下面是通用策略AutoTune上下文。请只输出一个JSON对象，不要Markdown代码块。\n"
        f"输出格式: {json.dumps(schema, ensure_ascii=False)}\n"
        "要求：不要编造指标；参数只能来自 parameter_bounds、boolean_params、categorical_params；建议必须说明原因。\n"
        f"上下文: {json.dumps(context, ensure_ascii=False, default=str)}"
    )


def parse_deepseek_json(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def sanitize_deepseek_output(payload: dict[str, Any]) -> dict[str, Any]:
    intents = payload.get("parameter_intents") or []
    accepted: list[dict[str, Any]] = []
    if isinstance(intents, list):
        for item in intents:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if path not in PARAM_BOUNDS and path not in BOOLEAN_PARAMS and path not in CATEGORICAL_PARAMS:
                continue
            value = item.get("value")
            accepted.append({
                "path": path,
                "action": str(item.get("action") or "set"),
                "value": clamp_param(path, value),
                "reason": str(item.get("reason") or ""),
            })
    return {
        "analysis_md": str(payload.get("analysis_md") or ""),
        "diagnosis": list(payload.get("diagnosis") or [])[:8] if isinstance(payload.get("diagnosis"), list) else [],
        "next_direction": list(payload.get("next_direction") or [])[:8] if isinstance(payload.get("next_direction"), list) else [],
        "parameter_intents": accepted,
        "risks": list(payload.get("risks") or [])[:8] if isinstance(payload.get("risks"), list) else [],
        "validation_plan": list(payload.get("validation_plan") or [])[:8] if isinstance(payload.get("validation_plan"), list) else [],
    }


def candidates_from_deepseek(review: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    intents = review.get("parameter_intents") or []
    if not isinstance(intents, list) or not intents:
        return []
    base: dict[str, Any] = {}
    for item in intents:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if path in PARAM_BOUNDS or path in BOOLEAN_PARAMS or path in CATEGORICAL_PARAMS:
            set_path(base, path, clamp_param(path, item.get("value")))
    if not base:
        return []
    candidates = [sanitize_patch(base)]
    if get_path(base, "selection.min_pred_rank") is not None:
        conservative = deepcopy(base)
        rank = float(get_path(conservative, "selection.min_pred_rank"))
        set_path(conservative, "selection.min_pred_rank", min(0.99, rank + 0.005))
        candidates.append(sanitize_patch(conservative))
        exploratory = deepcopy(base)
        set_path(exploratory, "selection.min_pred_rank", max(0.94, rank - 0.005))
        candidates.append(sanitize_patch(exploratory))
    if get_path(base, "position.n_holdings") is not None:
        n = int(get_path(base, "position.n_holdings"))
        for delta in (-4, 4):
            variant = deepcopy(base)
            set_path(variant, "position.n_holdings", n + delta)
            candidates.append(sanitize_patch(variant))
    if get_path(base, "position.max_single_weight") is not None:
        weight = float(get_path(base, "position.max_single_weight"))
        for delta in (-0.005, 0.005):
            variant = deepcopy(base)
            set_path(variant, "position.max_single_weight", weight + delta)
            candidates.append(sanitize_patch(variant))
    if get_path(base, "filters.market_regime.risk_state.weak_exposure") is not None:
        exposure = float(get_path(base, "filters.market_regime.risk_state.weak_exposure"))
        for delta in (-0.04, 0.04):
            variant = deepcopy(base)
            set_path(variant, "filters.market_regime.risk_state.weak_exposure", exposure + delta)
            set_path(variant, "filters.market_regime.weak_exposure", exposure + delta)
            candidates.append(sanitize_patch(variant))
    if get_path(base, "filters.index_anchor_warning.warning_exposure") is not None:
        exposure = float(get_path(base, "filters.index_anchor_warning.warning_exposure"))
        for delta in (-0.10, 0.10):
            variant = deepcopy(base)
            set_path(variant, "filters.index_anchor_warning.enabled", True)
            set_path(variant, "filters.index_anchor_warning.warning_exposure", exposure + delta)
            candidates.append(sanitize_patch(variant))
    if get_path(base, "filters.index_anchor_warning.ret5_overheat") is not None:
        threshold = float(get_path(base, "filters.index_anchor_warning.ret5_overheat"))
        for delta in (-0.03, 0.03):
            variant = deepcopy(base)
            set_path(variant, "filters.index_anchor_warning.enabled", True)
            set_path(variant, "filters.index_anchor_warning.ret5_overheat", threshold + delta)
            candidates.append(sanitize_patch(variant))
    if get_path(base, "filters.index_anchor_warning.overheat_exposure") is not None:
        exposure = float(get_path(base, "filters.index_anchor_warning.overheat_exposure"))
        for delta in (-0.10, 0.10):
            variant = deepcopy(base)
            set_path(variant, "filters.index_anchor_warning.enabled", True)
            set_path(variant, "filters.index_anchor_warning.overheat_exposure", exposure + delta)
            candidates.append(sanitize_patch(variant))
    if get_path(base, "filters.index_anchor_warning.overheat_cooldown_days") is not None:
        cooldown = int(get_path(base, "filters.index_anchor_warning.overheat_cooldown_days"))
        for delta in (-2, 2, 5):
            variant = deepcopy(base)
            set_path(variant, "filters.index_anchor_warning.enabled", True)
            set_path(variant, "filters.index_anchor_warning.overheat_cooldown_days", cooldown + delta)
            candidates.append(sanitize_patch(variant))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = param_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return deduped


def is_trial_passed(row: dict[str, Any]) -> bool:
    return (
        str(row.get("admission") or "") in ALLOWED_ADMISSIONS
        and float(row.get("annual_return") or 0) > 0
        and float(row.get("max_drawdown") or -1) >= -0.22
        and int(row.get("stress_bad_event_count") or 0) == 0
        and not bool(row.get("stress_crash_state_failed"))
        and not bool(row.get("stress_weak_drawdown_failed"))
    )


def trial_score(row: dict[str, Any]) -> float:
    return (
        float(row.get("admission_score") or 0) * 1.0
        + float(row.get("annual_return") or 0) * 120.0
        + float(row.get("max_drawdown") or 0) * 80.0
        + float(row.get("sharpe") or 0) * 6.0
        - float(row.get("stress_bad_event_count") or 0) * 6.0
        - (8.0 if bool(row.get("stress_crash_state_failed")) else 0.0)
        - (5.0 if bool(row.get("stress_weak_drawdown_failed")) else 0.0)
    )


def row_from_eval_result(result: dict[str, Any], eval_run_id: str, base_model_run_id: str) -> dict[str, Any]:
    row = deepcopy(result)
    row["eval_run_id"] = eval_run_id
    row["model_run_id"] = base_model_run_id
    row["passed"] = is_trial_passed(row)
    row["score"] = trial_score(row)
    return row


def run_trial(
    *,
    run_id: str,
    trial_id: str,
    round_no: int,
    source: str,
    base_model_run_id: str,
    start: str,
    end: str,
    params: dict[str, Any],
    llm_direction: dict[str, Any] | None,
) -> dict[str, Any]:
    eval_run_id = f"autotune_{run_id}_{trial_id}"
    override = {
        STRATEGY: deep_merge(params, {"selection": {"run_id": base_model_run_id}}),
    }
    old_override = os.environ.get("QUANT_STRATEGY_OVERRIDES_JSON")
    old_mode = os.environ.get("QUANT_STRATEGY_VERSION_MODE")
    old_require = os.environ.get("QUANT_REQUIRE_ML_FACTOR_RUN_ID")
    os.environ["QUANT_STRATEGY_OVERRIDES_JSON"] = json.dumps(override, ensure_ascii=False)
    os.environ["QUANT_STRATEGY_VERSION_MODE"] = "latest"
    os.environ["QUANT_REQUIRE_ML_FACTOR_RUN_ID"] = "1"
    try:
        # AutoTune is a parameter-search loop for one trained model run. Running
        # the independent baseline here is expensive and does not change the
        # trial's own admission gates, so reserve baseline comparison for the
        # final full evaluation.
        rows = evaluate_strategies.evaluate(
            [STRATEGY],
            start,
            end,
            benchmark="000905.SH",
            slippage=0.002,
            baseline="",
        )
        rows = [row for row in rows if str(row.get("strategy") or "") == STRATEGY]
        payload = {"start": start, "end": end, "benchmark": "000905.SH", "baseline": "", "rows": rows}
        evaluate_strategies.save_eval_strategy_admission(None, eval_run_id, payload, delete_existing=True)
    finally:
        restore_env("QUANT_STRATEGY_OVERRIDES_JSON", old_override)
        restore_env("QUANT_STRATEGY_VERSION_MODE", old_mode)
        restore_env("QUANT_REQUIRE_ML_FACTOR_RUN_ID", old_require)
    result = row_from_eval_result(rows[0] if rows else {"strategy": STRATEGY, "status": "empty", "admission": "继续观察", "reason": "未生成评估结果"}, eval_run_id, base_model_run_id)
    save_trial(run_id, trial_id, round_no, source, base_model_run_id, eval_run_id, params, llm_direction or {}, result)
    return result


def restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def save_run(
    *,
    run_id: str,
    base_model_run_id: str,
    start: str,
    end: str,
    status: str,
    summary: dict[str, Any],
    best: dict[str, Any] | None = None,
) -> None:
    now = now_text()
    best = best or {}
    columns = [
        "run_id", "base_model_run_id", "start_date", "end_date", "status",
        "best_trial_id", "best_model_run_id", "best_admission", "best_score",
        "summary_json", "created_at", "updated_at",
    ]
    with write_transaction() as conn:
        ensure_tables_in_conn(conn)
        conn.execute(
            upsert_sql(
                "factor_autotune_runs",
                columns,
                ["run_id"],
                ["base_model_run_id", "start_date", "end_date", "status", "best_trial_id", "best_model_run_id", "best_admission", "best_score", "summary_json", "updated_at"],
            ),
            (
                run_id,
                base_model_run_id,
                start,
                end,
                status,
                str(best.get("trial_id") or ""),
                str(best.get("model_run_id") or ""),
                str(best.get("admission") or ""),
                float(best.get("score") or best.get("admission_score") or 0) if best else None,
                json.dumps(summary, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )


def ensure_tables_in_conn(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_autotune_runs (
            run_id VARCHAR(255) PRIMARY KEY,
            base_model_run_id VARCHAR(255) NOT NULL,
            start_date VARCHAR(16) NOT NULL,
            end_date VARCHAR(16) NOT NULL,
            status VARCHAR(32) NOT NULL,
            best_trial_id VARCHAR(255) NOT NULL DEFAULT '',
            best_model_run_id VARCHAR(255) NOT NULL DEFAULT '',
            best_admission VARCHAR(64) NOT NULL DEFAULT '',
            best_score DOUBLE,
            summary_json LONGTEXT NOT NULL,
            created_at VARCHAR(64) NOT NULL,
            updated_at VARCHAR(64) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS factor_autotune_trials (
            run_id VARCHAR(255) NOT NULL,
            trial_id VARCHAR(255) NOT NULL,
            round_no BIGINT NOT NULL DEFAULT 0,
            source VARCHAR(64) NOT NULL DEFAULT '',
            model_run_id VARCHAR(255) NOT NULL DEFAULT '',
            eval_run_id VARCHAR(255) NOT NULL DEFAULT '',
            params_json LONGTEXT NOT NULL,
            llm_direction_json LONGTEXT NOT NULL,
            admission VARCHAR(64) NOT NULL DEFAULT '',
            admission_score DOUBLE,
            reason LONGTEXT NOT NULL,
            annual_return DOUBLE,
            total_return DOUBLE,
            max_drawdown DOUBLE,
            sharpe DOUBLE,
            stress_bad_event_count BIGINT NOT NULL DEFAULT 0,
            stress_crash_state_failed BIGINT NOT NULL DEFAULT 0,
            stress_weak_drawdown_failed BIGINT NOT NULL DEFAULT 0,
            passed BIGINT NOT NULL DEFAULT 0,
            created_at VARCHAR(64) NOT NULL,
            updated_at VARCHAR(64) NOT NULL,
            PRIMARY KEY(run_id, trial_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_autotune_trials_run_round ON factor_autotune_trials(run_id, round_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_autotune_trials_passed ON factor_autotune_trials(passed)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_autotune_trials_score ON factor_autotune_trials(admission_score)")


def save_trial(
    run_id: str,
    trial_id: str,
    round_no: int,
    source: str,
    model_run_id: str,
    eval_run_id: str,
    params: dict[str, Any],
    llm_direction: dict[str, Any],
    result: dict[str, Any],
) -> None:
    now = now_text()
    columns = [
        "run_id", "trial_id", "round_no", "source", "model_run_id", "eval_run_id",
        "params_json", "llm_direction_json", "admission", "admission_score", "reason",
        "annual_return", "total_return", "max_drawdown", "sharpe",
        "stress_bad_event_count", "stress_crash_state_failed", "stress_weak_drawdown_failed",
        "passed", "created_at", "updated_at",
    ]
    with write_transaction() as conn:
        ensure_tables_in_conn(conn)
        conn.execute(
            upsert_sql(
                "factor_autotune_trials",
                columns,
                ["run_id", "trial_id"],
                [col for col in columns if col not in {"run_id", "trial_id", "created_at"}],
            ),
            (
                run_id,
                trial_id,
                int(round_no),
                source,
                model_run_id,
                eval_run_id,
                json.dumps(params, ensure_ascii=False, default=str),
                json.dumps(llm_direction, ensure_ascii=False, default=str),
                str(result.get("admission") or ""),
                float(result.get("admission_score") or 0),
                str(result.get("reason") or ""),
                float(result.get("annual_return") or 0),
                float(result.get("total_return") or 0),
                float(result.get("max_drawdown") or 0),
                float(result.get("sharpe") or 0),
                int(result.get("stress_bad_event_count") or 0),
                1 if bool(result.get("stress_crash_state_failed")) else 0,
                1 if bool(result.get("stress_weak_drawdown_failed")) else 0,
                1 if bool(result.get("passed")) else 0,
                now,
                now,
            ),
        )


def activate_best_trial(base_cfg: dict[str, Any], base_model_run_id: str, params: dict[str, Any]) -> None:
    tuned = deep_merge(base_cfg, params)
    tuned["enabled"] = True
    set_path(tuned, "selection.run_id", base_model_run_id)
    now = now_text()
    with write_transaction() as conn:
        ensure_strategy_activation_tables(conn)
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM strategy_config_versions WHERE strategy = ?", (STRATEGY,)).fetchone()
        version = int(row[0] or 0) + 1
        conn.execute("UPDATE strategy_config_versions SET is_active = 0 WHERE strategy = ?", (STRATEGY,))
        conn.execute(
            upsert_sql(
                "strategy_config_versions",
                ["strategy", "version", "label", "config_json", "is_active", "promotion_status", "validation_json", "source", "note", "created_at", "activated_at"],
                ["strategy", "version"],
                ["label", "config_json", "is_active", "promotion_status", "validation_json", "source", "note", "activated_at"],
            ),
            (
                STRATEGY,
                version,
                str(tuned.get("label") or "机器学习因子"),
                json.dumps(tuned, ensure_ascii=False, default=str),
                1,
                "active",
                json.dumps({"source": "factor_autotune", "model_run_id": base_model_run_id}, ensure_ascii=False),
                "factor_autotune",
                "AutoTune 自动准入版本",
                now,
                now,
            ),
        )
        conn.execute(
            upsert_sql("strategy_model_active", ["strategy", "run_id", "updated_at"], ["strategy"], ["run_id", "updated_at"]),
            (STRATEGY, base_model_run_id, now),
        )


def ensure_strategy_activation_tables(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_config_versions (
            strategy VARCHAR(255) NOT NULL,
            version BIGINT NOT NULL,
            label VARCHAR(255) NOT NULL DEFAULT '',
            config_json LONGTEXT NOT NULL,
            is_active BIGINT NOT NULL DEFAULT 0,
            promotion_status VARCHAR(32) NOT NULL DEFAULT 'research',
            validation_json LONGTEXT NOT NULL,
            source VARCHAR(255) NOT NULL DEFAULT '',
            note VARCHAR(255) NOT NULL DEFAULT '',
            created_at VARCHAR(64) NOT NULL,
            activated_at VARCHAR(64) NOT NULL DEFAULT '',
            PRIMARY KEY(strategy, version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_model_active (
            strategy VARCHAR(191) PRIMARY KEY,
            run_id VARCHAR(191) NOT NULL,
            updated_at VARCHAR(191) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def run_autotune(args: argparse.Namespace) -> dict[str, Any]:
    ensure_tables()
    base_model_run_id = args.base_model_run_id.strip() or latest_model_run_id()
    if not base_model_run_id:
        raise RuntimeError("no successful factor model run found")
    base_cfg = load_strategy(STRATEGY)
    set_path(base_cfg, "selection.run_id", base_model_run_id)
    if str(getattr(args, "risk_model_run_id", "") or "").strip():
        set_path(base_cfg, "filters.crash_warning_model.enabled", True)
        set_path(base_cfg, "filters.crash_warning_model.run_id", str(args.risk_model_run_id).strip())
    if str(getattr(args, "risk_prob_column", "") or "").strip():
        set_path(base_cfg, "filters.crash_warning_model.enabled", True)
        set_path(base_cfg, "filters.crash_warning_model.prob_column", str(args.risk_prob_column).strip())
    admission = latest_admission(base_model_run_id)
    stresses = stress_rows(base_model_run_id)
    explored_keys = load_explored_param_keys(base_model_run_id, args.run_id)
    historical_trials = load_historical_trials(base_model_run_id, args.run_id)
    skipped_existing = 0
    planned_trials = max(1, args.max_rounds) * max(1, args.trials_per_round)
    save_run(
        run_id=args.run_id,
        base_model_run_id=base_model_run_id,
        start=args.start,
        end=args.end,
        status="running",
        summary={
            "stage": "prepare",
            "base_model_run_id": base_model_run_id,
            "planned_trials": planned_trials,
            "historical_explored_count": len(explored_keys),
        },
    )

    best: dict[str, Any] | None = None
    all_results: list[dict[str, Any]] = []
    pool = historical_seed_candidates(historical_trials, max(args.trials_per_round * 3, 12))
    pool.extend(generate_rule_candidates(base_cfg, admission, max(args.trials_per_round * 8, 24), 1))
    before = len(pool)
    candidates = filter_unexplored(pool, explored_keys, args.trials_per_round)
    skipped_existing += max(0, before - len(candidates))
    llm_direction: dict[str, Any] = {}

    total_trials = planned_trials
    done_trials = 0
    for round_no in range(1, args.max_rounds + 1):
        if not candidates:
            pool = historical_seed_candidates(historical_trials + all_results, max(args.trials_per_round * 3, 12))
            pool.extend(generate_rule_candidates(base_cfg, best or admission, max(args.trials_per_round * 8, 24), round_no))
            before = len(pool)
            candidates = filter_unexplored(pool, explored_keys, args.trials_per_round)
            skipped_existing += max(0, before - len(candidates))
        if not candidates:
            summary = {
                "stage": "done",
                "reason": "search_space_exhausted",
                "best": compact_trial(best or {}),
                "trial_count": len(all_results),
                "planned_trials": planned_trials,
                "skipped_existing_count": skipped_existing,
                "historical_explored_count": len(explored_keys),
            }
            save_run(run_id=args.run_id, base_model_run_id=base_model_run_id, start=args.start, end=args.end, status="failed", summary=summary, best=best)
            return summary
        for idx, params in enumerate(candidates[:args.trials_per_round], start=1):
            done_trials += 1
            trial_id = f"r{round_no:02d}_t{idx:02d}"
            run_status.progress(TASK_NAME, done_trials, total_trials, "trial", f"AutoTune {trial_id}")
            result = run_trial(
                run_id=args.run_id,
                trial_id=trial_id,
                round_no=round_no,
                source=str(llm_direction.get("provider") or "llm") if llm_direction.get("ok") and round_no > 1 else "rules",
                base_model_run_id=base_model_run_id,
                start=args.start,
                end=args.end,
                params=params,
                llm_direction=llm_direction,
            )
            result["trial_id"] = trial_id
            result["params"] = params
            all_results.append(result)
            explored_keys.add(param_key(params))
            if best is None or trial_score(result) > trial_score(best):
                best = result
            if result.get("passed") and not bool(getattr(args, "continue_after_pass", False)):
                if args.activate_best:
                    activate_best_trial(base_cfg, base_model_run_id, params)
                summary = {
                    "stage": "done",
                    "reason": "found_passed_trial",
                    "best": compact_trial(best),
                    "trial_count": len(all_results),
                    "planned_trials": planned_trials,
                    "skipped_existing_count": skipped_existing,
                    "historical_explored_count": len(explored_keys),
                }
                save_run(run_id=args.run_id, base_model_run_id=base_model_run_id, start=args.start, end=args.end, status="success", summary=summary, best=best)
                return summary

        if round_no >= args.max_rounds:
            break
        run_status.progress(TASK_NAME, done_trials, total_trials, "llm_review", f"复盘第 {round_no} 轮")
        context = {
            "base_model_run_id": base_model_run_id,
            "latest_admission": admission,
            "stress_rows": stresses,
            "current_config": base_cfg,
            "round_results": [compact_trial(row) for row in all_results[-args.trials_per_round:]],
            "all_current_run_results": [compact_trial(row) for row in all_results],
            "historical_autotune_results": historical_trial_context(historical_trials + all_results),
            "explored_param_count": len(explored_keys),
            "skipped_existing_count": skipped_existing,
            "parameter_bounds": PARAM_BOUNDS,
            "boolean_params": sorted(BOOLEAN_PARAMS),
            "categorical_params": {key: sorted(value) for key, value in CATEGORICAL_PARAMS.items()},
        }
        if args.use_deepseek:
            raw_provider = args.llm_provider or os.getenv("LLM_PROVIDER", "")
            if not str(raw_provider or "").strip() and (args.deepseek_token or args.deepseek_model or os.getenv("DEEPSEEK_TOKEN", "")):
                raw_provider = "deepseek"
            provider = normalize_llm_provider(raw_provider)
            token = args.llm_token or os.getenv(f"{provider.upper()}_TOKEN", "")
            model = args.llm_model or os.getenv(f"{provider.upper()}_MODEL", "")
            if provider == "deepseek":
                token = token or args.deepseek_token or os.getenv("DEEPSEEK_TOKEN", "")
                model = model or args.deepseek_model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
            elif provider == "openai":
                token = token or os.getenv("OPENAI_API_KEY", "") or os.getenv("OPENAI_TOKEN", "")
                model = model or os.getenv("OPENAI_MODEL", "gpt-5.5")
            llm_direction = llm_review(provider=provider, token=token, model=model or default_llm_model(provider), context=context)
            pool = candidates_from_deepseek(llm_direction, args.trials_per_round * 3)
        else:
            llm_direction = {"ok": False, "fallback": True, "error": "use_llm=false"}
            pool = []
        candidates = filter_unexplored(pool, explored_keys, args.trials_per_round)
        if not candidates:
            pool = historical_seed_candidates(historical_trials + all_results, max(args.trials_per_round * 3, 12))
            pool.extend(generate_rule_candidates(base_cfg, best or admission, max(args.trials_per_round * 8, 24), round_no + 1))
            before = len(pool)
            candidates = filter_unexplored(pool, explored_keys, args.trials_per_round)
            skipped_existing += max(0, before - len(candidates))

    status = "success" if best and best.get("passed") else "failed"
    if status == "success" and args.activate_best and best and isinstance(best.get("params"), dict):
        activate_best_trial(base_cfg, base_model_run_id, best["params"])
    summary = {
        "stage": "done",
        "reason": "completed_search_budget" if status == "success" else "no_passed_trial",
        "best": compact_trial(best or {}),
        "trial_count": len(all_results),
        "planned_trials": planned_trials,
        "skipped_existing_count": skipped_existing,
        "historical_explored_count": len(explored_keys),
    }
    save_run(run_id=args.run_id, base_model_run_id=base_model_run_id, start=args.start, end=args.end, status=status, summary=summary, best=best)
    return summary


def compact_trial(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trial_id": row.get("trial_id", ""),
        "eval_run_id": row.get("eval_run_id", ""),
        "admission": row.get("admission", ""),
        "admission_score": row.get("admission_score", 0),
        "reason": row.get("reason", ""),
        "annual_return": row.get("annual_return", 0),
        "total_return": row.get("total_return", 0),
        "max_drawdown": row.get("max_drawdown", 0),
        "sharpe": row.get("sharpe", 0),
        "passed": bool(row.get("passed")),
        "params": row.get("params", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-model-run-id", default="")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument("--trials-per-round", type=int, default=DEFAULT_TRIALS_PER_ROUND)
    parser.add_argument("--use-deepseek", action="store_true")
    parser.add_argument("--deepseek-model", default="")
    parser.add_argument("--deepseek-token", default="")
    parser.add_argument("--llm-provider", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--llm-token", default="")
    parser.add_argument("--risk-model-run-id", default="", help="固定使用指定市场/小盘生态风险模型 run")
    parser.add_argument("--risk-prob-column", default="", help="固定使用指定风险概率列，如 final_smallcap_risk")
    parser.add_argument("--activate-best", action="store_true")
    parser.add_argument("--continue-after-pass", action="store_true", help="找到通过准入的 trial 后继续跑完整个搜索预算，并最终激活最佳 trial")
    args = parser.parse_args()
    args.max_rounds = max(1, min(MAX_ROUNDS_CAP, int(args.max_rounds or DEFAULT_MAX_ROUNDS)))
    args.trials_per_round = max(1, min(TRIALS_PER_ROUND_CAP, int(args.trials_per_round or DEFAULT_TRIALS_PER_ROUND)))
    run_status.begin(TASK_NAME)
    try:
        summary = run_autotune(args)
        success = bool(summary.get("best", {}).get("passed"))
        if success:
            run_status.done(TASK_NAME, "AutoTune 找到可启用版本")
        else:
            run_status.done(TASK_NAME, "AutoTune 未找到可启用版本")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if success else 2
    except Exception as exc:
        run_status.error(TASK_NAME, str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
