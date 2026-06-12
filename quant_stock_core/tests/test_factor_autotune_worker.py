from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from common.infra import db
from scripts import factor_autotune_worker as worker


def _mysql_available() -> bool:
    try:
        with db.open_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def test_autotune_sanitizes_deepseek_and_bounds() -> None:
    payload = {
        "analysis_md": "弱市和压力段失效，需要更防守。",
        "diagnosis": ["弱市回撤过大"],
        "parameter_intents": [
            {"path": "selection.min_pred_rank", "value": 1.2, "reason": "提高置信度"},
            {"path": "position.n_holdings", "value": 3, "reason": "降低分散度"},
            {"path": "filters.crash_gate.enabled", "value": True, "reason": "避开股灾"},
            {"path": "dangerous.sql", "value": "DROP TABLE", "reason": "不应接受"},
        ],
    }

    sanitized = worker.sanitize_deepseek_output(payload)
    candidates = worker.candidates_from_deepseek(sanitized, 3)

    assert sanitized["parameter_intents"][0]["value"] == 0.99
    assert sanitized["parameter_intents"][1]["value"] == 8
    assert {item["path"] for item in sanitized["parameter_intents"]} == {
        "selection.min_pred_rank",
        "position.n_holdings",
        "filters.crash_gate.enabled",
    }
    assert candidates[0]["selection"]["min_pred_rank"] == 0.99
    assert candidates[0]["position"]["n_holdings"] == 8
    assert candidates[0]["filters"]["crash_gate"]["enabled"] is True


def test_autotune_deepseek_fallback_without_token() -> None:
    result = worker.deepseek_review(token="", model="deepseek-v4-pro", context={})

    assert result["ok"] is False
    assert result["fallback"] is True


def test_autotune_deepseek_non_json_is_rejected() -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"choices":[{"message":{"content":"not json"}}]}'

    class Opener:
        def open(self, req, timeout=90):
            return Response()

    result = worker.deepseek_review(token="token", model="deepseek-v4-pro", context={}, opener=Opener())

    assert result["ok"] is False
    assert result["fallback"] is True


def test_autotune_rule_candidates_react_to_stress_failure() -> None:
    base_cfg = {
        "selection": {"min_pred_rank": 0.96},
        "position": {"n_holdings": 24, "max_single_weight": 0.04, "max_industry_weight": 0.15},
    }
    admission = {
        "admission": "暂不启用",
        "reason": "压力段失效：股灾状态 / 弱市回撤",
        "annual_return": 0.03,
        "max_drawdown": -0.25,
        "stress_bad_event_count": 1,
        "stress_crash_state_failed": True,
        "stress_weak_drawdown_failed": True,
    }

    candidates = worker.generate_rule_candidates(base_cfg, admission, limit=5)

    assert candidates
    flat_candidates = [worker.flatten_patch(candidate) for candidate in candidates]
    assert any(item.get("filters.crash_gate.enabled") is True for item in flat_candidates)
    assert any(item.get("filters.crash_exit.enabled") is True for item in flat_candidates)
    assert any(float(item.get("selection.min_pred_rank", 0)) >= 0.975 for item in flat_candidates)
    assert all("dangerous.sql" not in item for item in flat_candidates)


def test_autotune_filters_explored_param_sets() -> None:
    repeated = {"selection": {"min_pred_rank": 0.97}, "position": {"n_holdings": 20}}
    fresh = {"selection": {"min_pred_rank": 0.975}, "position": {"n_holdings": 16}}
    explored = {worker.param_key(repeated)}

    selected = worker.filter_unexplored([repeated, fresh, repeated], explored, limit=3)

    assert selected == [worker.sanitize_patch(fresh)]
    assert worker.param_key(fresh) in explored


def test_autotune_historical_context_summarizes_trials() -> None:
    trials = [
        {
            "trial_id": "r01_t01",
            "admission": "暂不启用",
            "admission_score": 20,
            "reason": "弱市失败",
            "annual_return": 0.01,
            "total_return": 0.02,
            "max_drawdown": -0.30,
            "sharpe": 0.1,
            "stress_bad_event_count": 1,
            "passed": False,
            "params": {"selection": {"min_pred_rank": 0.97}},
        },
        {
            "trial_id": "r01_t02",
            "admission": "可启用",
            "admission_score": 85,
            "reason": "通过",
            "annual_return": 0.08,
            "total_return": 0.22,
            "max_drawdown": -0.12,
            "sharpe": 1.2,
            "stress_bad_event_count": 0,
            "passed": True,
            "params": {"selection": {"min_pred_rank": 0.98}},
        },
    ]

    context = worker.historical_trial_context(trials)

    assert context["explored_count"] == 2
    assert context["passed_count"] == 1
    assert context["best_trials"][0]["trial_id"] == "r01_t02"
    assert context["top_failed_reasons"][0]["reason"] in {"通过", "弱市失败"}


def test_autotune_trial_pass_gate() -> None:
    passed = {
        "admission": "可启用",
        "annual_return": 0.06,
        "max_drawdown": -0.16,
        "stress_bad_event_count": 0,
        "stress_crash_state_failed": False,
        "stress_weak_drawdown_failed": False,
    }
    failed = {
        **passed,
        "admission": "可启用",
        "stress_bad_event_count": 1,
    }

    assert worker.is_trial_passed(passed) is True
    assert worker.is_trial_passed(failed) is False


pytestmark_mysql = pytest.mark.skipif(not _mysql_available(), reason="local MySQL quant_stock database is not available")


@pytestmark_mysql
def test_autotune_tables_and_trial_roundtrip() -> None:
    run_id = f"pytest_autotune_{uuid4().hex[:12]}"
    trial_id = "r01_t01"
    rec_count_before = 0
    latest_count_before = 0
    try:
        worker.ensure_tables()
        with db.open_db() as conn:
            if db.table_exists(conn, "rec_daily_recommendations"):
                rec_count_before = int(conn.execute("SELECT COUNT(*) FROM rec_daily_recommendations").fetchone()[0] or 0)
            if db.table_exists(conn, "factor_latest_predictions"):
                latest_count_before = int(conn.execute("SELECT COUNT(*) FROM factor_latest_predictions").fetchone()[0] or 0)
        result = {
            "admission": "继续观察",
            "admission_score": 42.5,
            "reason": "pytest",
            "annual_return": 0.03,
            "total_return": 0.08,
            "max_drawdown": -0.18,
            "sharpe": 0.6,
            "stress_bad_event_count": 0,
            "stress_crash_state_failed": False,
            "stress_weak_drawdown_failed": False,
            "passed": False,
        }
        worker.save_trial(
            run_id,
            trial_id,
            1,
            "rules",
            "model_pytest",
            "eval_pytest",
            {"selection": {"min_pred_rank": 0.97}},
            {"analysis_md": "pytest"},
            result,
        )
        worker.save_trial(
            run_id,
            trial_id,
            2,
            "rules",
            "model_pytest",
            "eval_pytest_2",
            {"selection": {"min_pred_rank": 0.98}},
            {"analysis_md": "pytest-upsert"},
            {**result, "admission_score": 43.5, "reason": "pytest-upsert"},
        )
        with db.open_db() as conn:
            cols = db.table_columns(conn, "factor_autotune_trials")
            row = conn.execute(
                """
                SELECT run_id, trial_id, round_no, source, admission, admission_score, reason, passed
                FROM factor_autotune_trials
                WHERE run_id = ? AND trial_id = ?
                """,
                (run_id, trial_id),
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) FROM factor_autotune_trials WHERE run_id = ? AND trial_id = ?",
                (run_id, trial_id),
            ).fetchone()
            rec_count_after = int(conn.execute("SELECT COUNT(*) FROM rec_daily_recommendations").fetchone()[0] or 0) if db.table_exists(conn, "rec_daily_recommendations") else 0
            latest_count_after = int(conn.execute("SELECT COUNT(*) FROM factor_latest_predictions").fetchone()[0] or 0) if db.table_exists(conn, "factor_latest_predictions") else 0

        assert "params_json" in cols
        assert "llm_direction_json" in cols
        assert row == (run_id, trial_id, 2, "rules", "继续观察", 43.5, "pytest-upsert", 0)
        assert int(count[0]) == 1
        assert rec_count_after == rec_count_before
        assert latest_count_after == latest_count_before
    finally:
        with db.write_transaction() as conn:
            if db.table_exists(conn, "factor_autotune_trials"):
                conn.execute("DELETE FROM factor_autotune_trials WHERE run_id = ?", (run_id,))
            if db.table_exists(conn, "factor_autotune_runs"):
                conn.execute("DELETE FROM factor_autotune_runs WHERE run_id = ?", (run_id,))


@pytestmark_mysql
def test_autotune_run_only_activates_passed_trial(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = f"pytest_autotune_active_{uuid4().hex[:12]}"
    strategy = f"pytest_strategy_{uuid4().hex[:8]}"
    base_model_run_id = f"model_{uuid4().hex[:8]}"
    args = SimpleNamespace(
        run_id=run_id,
        base_model_run_id=base_model_run_id,
        start="20200101",
        end="20240101",
        max_rounds=1,
        trials_per_round=1,
        use_deepseek=False,
        deepseek_token="",
        deepseek_model="",
        activate_best=True,
    )
    monkeypatch.setattr(worker, "STRATEGY", strategy)
    monkeypatch.setattr(worker, "load_strategy", lambda name: {"label": "pytest", "selection": {}, "position": {}})
    monkeypatch.setattr(worker, "latest_admission", lambda model_run_id: {"admission": "暂不启用", "reason": "pytest"})
    monkeypatch.setattr(worker, "stress_rows", lambda model_run_id: [])
    monkeypatch.setattr(worker, "generate_rule_candidates", lambda base_cfg, admission, limit, round_no=1: [{"selection": {"min_pred_rank": 0.97}}])

    def passed_trial(**kwargs):
        result = {
            "trial_id": kwargs["trial_id"],
            "eval_run_id": "eval_pytest_passed",
            "model_run_id": base_model_run_id,
            "admission": "可启用",
            "admission_score": 80.0,
            "reason": "pytest passed",
            "annual_return": 0.08,
            "total_return": 0.2,
            "max_drawdown": -0.1,
            "sharpe": 1.2,
            "stress_bad_event_count": 0,
            "stress_crash_state_failed": False,
            "stress_weak_drawdown_failed": False,
        }
        result["passed"] = worker.is_trial_passed(result)
        result["score"] = worker.trial_score(result)
        worker.save_trial(
            kwargs["run_id"],
            kwargs["trial_id"],
            kwargs["round_no"],
            kwargs["source"],
            kwargs["base_model_run_id"],
            result["eval_run_id"],
            kwargs["params"],
            kwargs["llm_direction"] or {},
            result,
        )
        return result

    monkeypatch.setattr(worker, "run_trial", passed_trial)
    try:
        summary = worker.run_autotune(args)
        with db.open_db() as conn:
            row = conn.execute(
                "SELECT run_id FROM strategy_model_active WHERE strategy = ?",
                (strategy,),
            ).fetchone()
            version = conn.execute(
                "SELECT COUNT(*) FROM strategy_config_versions WHERE strategy = ? AND source = 'factor_autotune'",
                (strategy,),
            ).fetchone()
        assert summary["reason"] == "found_passed_trial"
        assert row == (base_model_run_id,)
        assert int(version[0] or 0) == 1
    finally:
        with db.write_transaction() as conn:
            for table in ("factor_autotune_trials", "factor_autotune_runs"):
                if db.table_exists(conn, table):
                    conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
            if db.table_exists(conn, "strategy_model_active"):
                conn.execute("DELETE FROM strategy_model_active WHERE strategy = ?", (strategy,))
            if db.table_exists(conn, "strategy_config_versions"):
                conn.execute("DELETE FROM strategy_config_versions WHERE strategy = ?", (strategy,))


@pytestmark_mysql
def test_autotune_run_does_not_activate_failed_trial(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = f"pytest_autotune_inactive_{uuid4().hex[:12]}"
    strategy = f"pytest_strategy_{uuid4().hex[:8]}"
    base_model_run_id = f"model_{uuid4().hex[:8]}"
    args = SimpleNamespace(
        run_id=run_id,
        base_model_run_id=base_model_run_id,
        start="20200101",
        end="20240101",
        max_rounds=1,
        trials_per_round=1,
        use_deepseek=False,
        deepseek_token="",
        deepseek_model="",
        activate_best=True,
    )
    monkeypatch.setattr(worker, "STRATEGY", strategy)
    monkeypatch.setattr(worker, "load_strategy", lambda name: {"label": "pytest", "selection": {}, "position": {}})
    monkeypatch.setattr(worker, "latest_admission", lambda model_run_id: {"admission": "暂不启用", "reason": "pytest"})
    monkeypatch.setattr(worker, "stress_rows", lambda model_run_id: [])
    monkeypatch.setattr(worker, "generate_rule_candidates", lambda base_cfg, admission, limit, round_no=1: [{"selection": {"min_pred_rank": 0.97}}])

    def failed_trial(**kwargs):
        result = {
            "trial_id": kwargs["trial_id"],
            "eval_run_id": "eval_pytest_failed",
            "model_run_id": base_model_run_id,
            "admission": "暂不启用",
            "admission_score": 20.0,
            "reason": "pytest failed",
            "annual_return": -0.02,
            "total_return": -0.05,
            "max_drawdown": -0.3,
            "sharpe": -0.5,
            "stress_bad_event_count": 1,
            "stress_crash_state_failed": True,
            "stress_weak_drawdown_failed": False,
            "passed": False,
        }
        result["score"] = worker.trial_score(result)
        worker.save_trial(
            kwargs["run_id"],
            kwargs["trial_id"],
            kwargs["round_no"],
            kwargs["source"],
            kwargs["base_model_run_id"],
            result["eval_run_id"],
            kwargs["params"],
            kwargs["llm_direction"] or {},
            result,
        )
        return result

    monkeypatch.setattr(worker, "run_trial", failed_trial)
    try:
        summary = worker.run_autotune(args)
        with db.open_db() as conn:
            row = conn.execute(
                "SELECT run_id FROM strategy_model_active WHERE strategy = ?",
                (strategy,),
            ).fetchone() if db.table_exists(conn, "strategy_model_active") else None
        assert summary["reason"] == "no_passed_trial"
        assert row is None
    finally:
        with db.write_transaction() as conn:
            for table in ("factor_autotune_trials", "factor_autotune_runs"):
                if db.table_exists(conn, table):
                    conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
            if db.table_exists(conn, "strategy_model_active"):
                conn.execute("DELETE FROM strategy_model_active WHERE strategy = ?", (strategy,))
            if db.table_exists(conn, "strategy_config_versions"):
                conn.execute("DELETE FROM strategy_config_versions WHERE strategy = ?", (strategy,))
