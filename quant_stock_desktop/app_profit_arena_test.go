package main

import (
	"math"
	"testing"
)

func TestProfitArenaPredictionCapacityFailed(t *testing.T) {
	fail := ProfitArenaPrediction{SummaryJSON: `{"capacity_status":"fail","capacity_participation_rate":0.12}`}
	if !profitArenaPredictionCapacityFailed(fail) {
		t.Fatal("expected capacity fail prediction to be rejected")
	}
	if got := profitArenaPredictionCapacityStatus(fail); got != "fail" {
		t.Fatalf("expected fail status, got %s", got)
	}

	warn := ProfitArenaPrediction{SummaryJSON: `{"capacity_status":"warn","capacity_participation_rate":0.03}`}
	if profitArenaPredictionCapacityFailed(warn) {
		t.Fatal("expected capacity warn prediction to remain tradable")
	}
	if got := profitArenaPredictionCapacityStatus(warn); got != "warn" {
		t.Fatalf("expected warn status, got %s", got)
	}

	legacy := ProfitArenaPrediction{SummaryJSON: `{}`}
	if profitArenaPredictionCapacityFailed(legacy) {
		t.Fatal("expected legacy prediction without capacity summary to remain tradable")
	}
}

func TestProfitArenaPredictionPortfolioRiskStatus(t *testing.T) {
	fail := ProfitArenaPrediction{SummaryJSON: `{"portfolio_risk_status":"fail"}`}
	if got := profitArenaPredictionPortfolioRiskStatus(fail); got != "fail" {
		t.Fatalf("expected portfolio risk fail, got %s", got)
	}

	legacy := ProfitArenaPrediction{SummaryJSON: `{}`}
	if got := profitArenaPredictionPortfolioRiskStatus(legacy); got != "" {
		t.Fatalf("expected empty legacy portfolio status, got %s", got)
	}
}

func TestProfitArenaPredictionBuyPlanStatus(t *testing.T) {
	blocked := ProfitArenaPrediction{SummaryJSON: `{"buy_plan_status":"blocked_by_portfolio_risk","buy_plan_reason":"portfolio_risk_gate_failed"}`}
	if got := profitArenaPredictionBuyPlanStatus(blocked); got != "blocked_by_portfolio_risk" {
		t.Fatalf("expected blocked buy plan status, got %s", got)
	}
	status, reason := profitArenaPredictionBuyPlan(blocked)
	if status != "blocked_by_portfolio_risk" || reason != "portfolio_risk_gate_failed" {
		t.Fatalf("expected blocked status/reason, got %s/%s", status, reason)
	}

	legacy := ProfitArenaPrediction{SummaryJSON: `{}`}
	if got := profitArenaPredictionBuyPlanStatus(legacy); got != "" {
		t.Fatalf("expected empty legacy buy plan status, got %s", got)
	}
}

func TestProfitArenaPredictionIsBuyCandidate(t *testing.T) {
	buy := ProfitArenaPrediction{SummaryJSON: `{"is_buy_candidate":1}`}
	if !profitArenaPredictionIsBuyCandidate(buy) {
		t.Fatal("expected explicit buy candidate")
	}

	displayOnly := ProfitArenaPrediction{SummaryJSON: `{"is_buy_candidate":0}`}
	if profitArenaPredictionIsBuyCandidate(displayOnly) {
		t.Fatal("expected display-only candidate to be excluded from buy plan stats")
	}

	legacy := ProfitArenaPrediction{SummaryJSON: `{}`}
	if !profitArenaPredictionIsBuyCandidate(legacy) {
		t.Fatal("expected legacy prediction without marker to remain compatible")
	}
}

func TestProfitArenaPredictionPortfolioRiskFailTakesPrecedenceInScanLogic(t *testing.T) {
	rows := []ProfitArenaPrediction{
		{SummaryJSON: `{"portfolio_risk_status":"pass"}`},
		{SummaryJSON: `{"portfolio_risk_status":"fail"}`},
	}
	status := ""
	for _, row := range rows {
		if next := profitArenaPredictionPortfolioRiskStatus(row); next != "" {
			if next == "fail" {
				status = next
			} else if status == "" {
				status = next
			}
		}
	}
	if status != "fail" {
		t.Fatalf("expected fail to take precedence, got %s", status)
	}
}

func TestProfitArenaEffectiveCapitalFraction(t *testing.T) {
	if got := profitArenaEffectiveCapitalFraction(0, 20); got != 0.05 {
		t.Fatalf("expected 0 to mean 1/horizon, got %v", got)
	}
	if got := profitArenaEffectiveCapitalFraction(-1, 10); got != 0.10 {
		t.Fatalf("expected negative value to mean 1/horizon, got %v", got)
	}
	if got := profitArenaEffectiveCapitalFraction(2, 20); got != 1 {
		t.Fatalf("expected fraction to be capped at 1, got %v", got)
	}
}

func TestProfitArenaEffectiveTargetWeightsPreferStoredWeights(t *testing.T) {
	rows := []ProfitArenaPrediction{
		{ModelScore: 10, SummaryJSON: `{"position_weight":0.7,"capital_scale":0.5}`},
		{ModelScore: 1, SummaryJSON: `{"position_weight":0.3,"capital_scale":1}`},
	}
	weights := profitArenaEffectiveTargetWeights(rows, "score")
	if len(weights) != 2 || math.Abs(weights[0]-0.35) > 1e-9 || math.Abs(weights[1]-0.3) > 1e-9 {
		t.Fatalf("expected stored effective weights [0.35 0.3], got %#v", weights)
	}
}

func TestProfitArenaPredictionStale(t *testing.T) {
	if !profitArenaPredictionStale("2026-06-18", "20260619") {
		t.Fatal("expected older prediction date to be stale")
	}
	if profitArenaPredictionStale("20260619", "20260619") {
		t.Fatal("expected same-day prediction to be fresh")
	}
	if profitArenaPredictionStale("", "20260619") {
		t.Fatal("expected empty prediction date to avoid stale classification")
	}
}

func TestProfitArenaRunHardGateOK(t *testing.T) {
	ok := ProfitArenaRunSummary{SummaryJSON: `{"best_challenger_score_components":{"hard_gate_ok":true},"best":{"capacity_status":"pass","portfolio_risk_status":"pass"}}`}
	if !profitArenaRunHardGateOK(ok) {
		t.Fatal("expected explicit pass run to be eligible")
	}

	capacityFail := ProfitArenaRunSummary{SummaryJSON: `{"best_challenger_score_components":{"hard_gate_ok":true},"best":{"capacity_status":"fail"}}`}
	if profitArenaRunHardGateOK(capacityFail) {
		t.Fatal("expected capacity fail run to be ineligible")
	}

	hardGateFail := ProfitArenaRunSummary{SummaryJSON: `{"best_challenger_score_components":{"hard_gate_ok":false},"best":{"capacity_status":"pass"}}`}
	if profitArenaRunHardGateOK(hardGateFail) {
		t.Fatal("expected hard gate fail run to be ineligible")
	}

	legacy := ProfitArenaRunSummary{SummaryJSON: `{}`}
	if !profitArenaRunHardGateOK(legacy) {
		t.Fatal("expected legacy run without explicit gate fields to remain eligible")
	}
}

func TestRunStatusObservabilitySummaryLatestInference(t *testing.T) {
	obs := runStatusObservabilitySummary("done", "20260619 推荐 8 只 buy_plan=ready capacity_pass=8 capacity_warn=1 capacity_fail=0 portfolio_status=pass portfolio_fail=0 portfolio_warn=0")
	if got := asString(obs["buy_plan_status"]); got != "ready" {
		t.Fatalf("expected buy plan ready, got %s", got)
	}
	capacity := mapParam(obs, "capacity")
	if intFromAny(capacity["pass_count"]) != 8 || intFromAny(capacity["warn_count"]) != 1 || intFromAny(capacity["fail_count"]) != 0 {
		t.Fatalf("unexpected capacity observability: %#v", capacity)
	}
	portfolio := mapParam(obs, "portfolio_risk")
	if asString(portfolio["status"]) != "pass" || intFromAny(portfolio["fail_count"]) != 0 || intFromAny(portfolio["warn_count"]) != 0 {
		t.Fatalf("unexpected portfolio risk observability: %#v", portfolio)
	}
}

func TestRunStatusObservabilitySummaryHardGate(t *testing.T) {
	running := runStatusObservabilitySummary("scope_horizon", "status=success rows=12000 gate_pass=12")
	runningGate := mapParam(running, "hard_gate")
	if intFromAny(runningGate["pass_count"]) != 12 || intFromAny(runningGate["fail_count"]) != 0 || boolFromAnyDefault(runningGate["final"], true) {
		t.Fatalf("unexpected running hard gate observability: %#v", runningGate)
	}

	done := runStatusObservabilitySummary("done", "summary=/tmp/summary.json gate_pass=19 gate_fail=3")
	doneGate := mapParam(done, "hard_gate")
	if intFromAny(doneGate["pass_count"]) != 19 || intFromAny(doneGate["fail_count"]) != 3 || !boolFromAnyDefault(doneGate["final"], false) {
		t.Fatalf("unexpected final hard gate observability: %#v", doneGate)
	}
}

func TestRunStatusObservabilitySummaryPreservesZeroTokens(t *testing.T) {
	obs := runStatusObservabilitySummary("done", "buy_plan=ready capacity_pass=0 capacity_warn=0 capacity_fail=0 portfolio_status=pass portfolio_fail=0 portfolio_warn=0 gate_pass=0 gate_fail=0")
	capacity := mapParam(obs, "capacity")
	if _, ok := capacity["fail_count"]; !ok || intFromAny(capacity["fail_count"]) != 0 {
		t.Fatalf("expected zero capacity fail count to be preserved: %#v", capacity)
	}
	portfolio := mapParam(obs, "portfolio_risk")
	if _, ok := portfolio["fail_count"]; !ok || intFromAny(portfolio["fail_count"]) != 0 {
		t.Fatalf("expected zero portfolio fail count to be preserved: %#v", portfolio)
	}
	hardGate := mapParam(obs, "hard_gate")
	if _, ok := hardGate["fail_count"]; !ok || intFromAny(hardGate["fail_count"]) != 0 {
		t.Fatalf("expected zero hard gate fail count to be preserved: %#v", hardGate)
	}
}

func TestRunStatusSubtaskLabelsAvoidBlankCurrentStep(t *testing.T) {
	key, name := runStatusSubtaskLabels("capacity_gate", "最新推荐容量门禁")
	if key != "capacity_gate" || name != "最新推荐容量门禁" {
		t.Fatalf("unexpected explicit subtask labels: %s/%s", key, name)
	}

	key, name = runStatusSubtaskLabels("", "最新推荐组合风险预算")
	if key != "最新推荐组合风险预算" || name != "最新推荐组合风险预算" {
		t.Fatalf("expected name to backfill key, got %s/%s", key, name)
	}

	key, name = runStatusSubtaskLabels("arena_challenge", "")
	if key != "arena_challenge" || name != "arena_challenge" {
		t.Fatalf("expected stage to backfill name, got %s/%s", key, name)
	}
}
