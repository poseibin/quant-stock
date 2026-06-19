from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import profit_arena_worker as worker


def _args(**patch):
    base = {
        "selection_min_trades": 100,
        "selection_min_trade_years": 5,
        "min_rank_ic": 0.08,
        "min_rank_ic_days": 50,
        "min_capital_annual_return": 0.0,
        "min_capital_sharpe": 0.0,
        "max_capital_drawdown": -0.30,
        "enforce_capacity_gate": True,
        "allow_capacity_fail": False,
        "enforce_portfolio_risk_gate": True,
        "allow_portfolio_risk_fail": False,
    }
    base.update(patch)
    return SimpleNamespace(**base)


def _candidate(**patch):
    base = {
        "scope": "small",
        "horizon": 20,
        "top_n": 3,
        "trade_count": 240,
        "trade_years": 8,
        "rank_ic": 0.10,
        "rank_ic_days": 120,
        "capital_annual_return": 0.35,
        "capital_max_drawdown": -0.18,
        "capital_sharpe": 1.6,
        "capacity_status": "pass",
        "capacity_fail_count": 0,
        "portfolio_risk_status": "pass",
        "portfolio_risk_fail_count": 0,
    }
    base.update(patch)
    return base


def test_capacity_fail_candidate_is_not_selectable_when_gate_enforced() -> None:
    args = _args()
    high_return_but_untradeable = _candidate(
        capital_annual_return=0.60,
        capital_sharpe=2.0,
        capacity_status="fail",
        capacity_fail_count=12,
    )
    lower_return_but_capacity_safe = _candidate(
        capital_annual_return=0.32,
        capital_sharpe=1.4,
        capacity_status="pass",
    )

    assert not worker.evaluation_gate_ok(high_return_but_untradeable, args)
    assert worker.evaluation_gate_ok(lower_return_but_capacity_safe, args)
    selected = worker.select_best_challenger([high_return_but_untradeable, lower_return_but_capacity_safe], args)

    assert selected is lower_return_but_capacity_safe


def test_score_components_mark_capacity_failure_as_hard_gate_failure() -> None:
    args = _args()
    candidate = _candidate(capacity_status="fail", capacity_fail_count=1)

    components = worker.arena_score_components(candidate, args)
    diagnostics = components["gate_diagnostics"]

    assert components["hard_gate_ok"] is False
    assert "capacity_gate" in components["hard_gate_failures"]
    assert diagnostics["hard_gate_ok"] is False
    assert "容量门禁失败" in diagnostics["labels"]


def test_gate_failure_summary_counts_institutional_rejections() -> None:
    args = _args()
    rows = [
        _candidate(capacity_status="pass"),
        _candidate(capacity_status="fail", capacity_fail_count=2),
        _candidate(portfolio_risk_status="fail", portfolio_risk_fail_count=1),
    ]

    summary = worker.gate_failure_summary(rows, args)

    assert summary["hard_gate_pass_count"] == 1
    assert summary["hard_gate_fail_count"] == 2
    assert summary["top_failures"][0]["count"] == 1
    assert {item["name"] for item in summary["top_failures"]} == {"capacity_gate", "portfolio_risk_gate"}


def test_latest_capacity_selection_summary_marks_incomplete_buy_plan() -> None:
    frame = pd.DataFrame([
        {"capacity_status": "pass"},
        {"capacity_status": "warn"},
        {"capacity_status": "fail"},
        {"capacity_status": ""},
    ])

    summary = worker.latest_capacity_selection_summary(frame, 3)

    assert summary["display_count"] == 4
    assert summary["evaluated_count"] == 3
    assert summary["tradable_count"] == 2
    assert summary["fail_count"] == 1
    assert summary["buy_plan_complete"] is False


def test_latest_buy_plan_status_blocks_portfolio_risk_before_capacity() -> None:
    capacity = {"tradable_count": 2, "evaluated_top_n": 3, "fail_count": 1}
    risk = {"status": "fail", "fail_count": 1}

    status = worker.latest_buy_plan_status(capacity, risk)

    assert status["status"] == "blocked_by_portfolio_risk"
    assert status["reason"] == "portfolio_risk_gate_failed"


def test_latest_buy_plan_status_marks_partial_capacity() -> None:
    capacity = {"tradable_count": 2, "evaluated_top_n": 3, "fail_count": 1}
    risk = {"status": "pass"}

    status = worker.latest_buy_plan_status(capacity, risk)

    assert status["status"] == "partial_capacity"
    assert status["reason"] == "capacity_tradable_candidates_below_top_n"


def test_latest_buy_plan_status_uses_buy_top_n_not_display_pool_size() -> None:
    capacity = {
        "display_count": 20,
        "tradable_count": 3,
        "evaluated_top_n": 3,
        "fail_count": 0,
    }
    risk = {"status": "pass"}

    status = worker.latest_buy_plan_status(capacity, risk)

    assert status["status"] == "ready"
    assert status["target_count"] == 3


def test_no_champion_when_all_candidates_fail_institutional_gates() -> None:
    args = _args()
    capacity_fail = _candidate(capacity_status="fail", capacity_fail_count=3)
    risk_fail = _candidate(portfolio_risk_status="fail", portfolio_risk_fail_count=2)

    selected = worker.select_best_challenger([capacity_fail, risk_fail], args)

    assert selected == {}


def test_capacity_failure_can_be_overridden_explicitly_for_research() -> None:
    args = _args(allow_capacity_fail=True, enforce_portfolio_risk_gate=False)
    capacity_fail = _candidate(capital_annual_return=0.60, capacity_status="fail", capacity_fail_count=3)
    capacity_pass = _candidate(capital_annual_return=0.30, capacity_status="pass")

    assert worker.evaluation_gate_ok(capacity_fail, args)
    selected = worker.select_best_challenger([capacity_fail, capacity_pass], args)

    assert selected is capacity_fail


def test_capacity_report_uses_real_position_weight_scale_and_capital_fraction() -> None:
    trades = pd.DataFrame([
        {
            "trade_date": "2026-06-18",
            "ts_code": "000001.SZ",
            "name": "A",
            "model_score": 100.0,
            "amount": 10_000_000.0,
            "position_weight": 0.75,
            "capital_scale": 0.5,
        },
        {
            "trade_date": "2026-06-18",
            "ts_code": "000002.SZ",
            "name": "B",
            "model_score": 1.0,
            "amount": 10_000_000.0,
            "position_weight": 0.25,
            "capital_scale": 1.0,
        },
    ])

    full = worker.build_capacity_report(
        trades,
        top_n=2,
        capital_base=1_000_000.0,
        capital_fraction=1.0,
        amount_unit=1.0,
        weight_column="position_weight",
        capital_scale_column="capital_scale",
    )
    half = worker.build_capacity_report(
        trades,
        top_n=2,
        capital_base=1_000_000.0,
        capital_fraction=0.5,
        amount_unit=1.0,
        weight_column="position_weight",
        capital_scale_column="capital_scale",
    )

    assert full["order_notional"].sum() == 625_000.0
    assert half["order_notional"].sum() == 312_500.0
    assert full.loc[full["ts_code"] == "000001.SZ", "order_notional"].iloc[0] == 375_000.0


def test_zero_capital_fraction_means_horizon_based_auto_tranche_not_zero_exposure() -> None:
    assert worker.effective_capital_tranche_fraction(0.0, 20) == 0.05
    assert worker.effective_capital_tranche_fraction(-1.0, 10) == 0.10


def test_portfolio_risk_uses_real_effective_portfolio_weight() -> None:
    trades = pd.DataFrame([
        {
            "trade_date": "2026-06-18",
            "ts_code": "000001.SZ",
            "model_score": 100.0,
            "industry": "bank",
            "size_bucket": "large",
            "crash_prob": 0.05,
            "position_weight": 0.75,
            "capital_scale": 0.5,
        },
        {
            "trade_date": "2026-06-18",
            "ts_code": "000002.SZ",
            "model_score": 1.0,
            "industry": "tech",
            "size_bucket": "small",
            "crash_prob": 0.20,
            "position_weight": 0.25,
            "capital_scale": 1.0,
        },
    ])

    report = worker.build_portfolio_risk_report(
        trades,
        top_n=2,
        capital_fraction=0.5,
        max_single_weight=0.20,
        weight_column="position_weight",
        capital_scale_column="capital_scale",
    )

    max_single = report[report["check"] == "max_single_weight"]["value"].iloc[0]
    avg_crash = report[report["check"] == "avg_crash_prob"]["value"].iloc[0]

    assert max_single == 0.1875
    assert round(avg_crash, 4) == 0.1100
