"""Run one portfolio candidate and write its result to desktop SQLite.

The desktop app owns orchestration. This script intentionally handles exactly
one candidate so Go can monitor progress, retry failures, and resume a parent
portfolio evaluation from unfinished child tasks.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config.desktop_settings import load_portfolio_risk
from trading.strategy import registry
from scripts.optimize_portfolio import (
    _combine_candidate,
    _float_or_none,
    _json_default,
    _reason,
    _resolve_db_path,
    _run_panel,
    _score,
)
from scripts.evaluate_strategies import _weight_exposure


def emit(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False, default=_json_default), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--candidate-name", required=True)
    parser.add_argument("--weights-json", required=True)
    parser.add_argument("--scheme-json", default="{}")
    parser.add_argument("--exit-json", default="{}")
    parser.add_argument("--strategy-overrides-json", default="{}")
    parser.add_argument("--strategy-version-mode", choices=["active", "latest"], default="latest")
    parser.add_argument("--strategy-version-json", default="{}")
    parser.add_argument("--rebalance-freq", type=int, default=5)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--benchmark", default="000905.SH")
    parser.add_argument("--slippage", type=float, default=0.002)
    parser.add_argument("--objective", choices=["稳健", "平衡", "进攻"], default="平衡")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    weights = json.loads(args.weights_json)
    if not isinstance(weights, dict) or not weights:
        raise SystemExit("weights-json must be a non-empty object")
    weights = {str(k): float(v) for k, v in weights.items()}
    scheme = _safe_json_object(args.scheme_json)
    exit_architecture = _safe_json_object(args.exit_json)
    if not exit_architecture:
        exit_architecture = _safe_json_object(scheme.get("exit_architecture"))
    strategy_overrides = _safe_json_object(args.strategy_overrides_json) or _safe_json_object(scheme.get("strategy_overrides"))
    os.environ["QUANT_STRATEGY_OVERRIDES_JSON"] = json.dumps(strategy_overrides, ensure_ascii=False)
    os.environ["QUANT_STRATEGY_VERSION_MODE"] = args.strategy_version_mode
    os.environ["QUANT_STRATEGY_VERSION_JSON"] = args.strategy_version_json

    emit({"type": "progress", "stage": "load", "progress": 0.03, "message": "加载策略与风控配置"})
    risk = _candidate_risk(scheme, load_portfolio_risk())
    panels: dict[str, pd.DataFrame] = {}

    for idx, name in enumerate(weights.keys(), start=1):
        emit({
            "type": "progress",
            "stage": "generate_weights",
            "progress": 0.05 + 0.35 * (idx - 1) / max(len(weights), 1),
            "name": name,
            "message": f"生成策略权重: {registry.get_label(name)}",
        })
        strategy = registry.build(name)
        panel = strategy.generate_target_weights(args.start, args.end)
        if not panel.empty:
            panels[name] = panel

    emit({"type": "progress", "stage": "combine", "progress": 0.45, "message": "合成交易方案权重"})
    combined = _combine_candidate(weights, panels, risk)
    combined = _apply_rebalance_freq(combined, args.rebalance_freq)
    if combined.empty:
        row = {
            "candidate_id": args.candidate_id,
            "name": args.candidate_name,
            "objective": args.objective,
            "strategies": ",".join(weights.keys()),
            "weights": weights,
            "scheme_type": "trading_scheme",
            "scheme": scheme,
            "strategy_overrides": strategy_overrides,
            "strategy_version_mode": args.strategy_version_mode,
            "exit_architecture": exit_architecture,
            "exit_architecture_type": str(exit_architecture.get("type") or "rebalance_only"),
            "exit_architecture_label": str(exit_architecture.get("label") or "跌出目标池卖出"),
            "rebalance_freq": args.rebalance_freq,
            "status": "empty",
            "score": -999.0,
            "reason": "交易方案未生成持仓",
        }
    else:
        emit({"type": "progress", "stage": "backtest", "progress": 0.62, "message": "运行交易方案回测"})
        result = _run_panel(combined, args.start, args.end, args.benchmark, args.slippage)
        exit_stats = _exit_architecture_stats(result.weights, exit_architecture, args.rebalance_freq)
        row = {
            "candidate_id": args.candidate_id,
            "name": args.candidate_name,
            "objective": args.objective,
            "strategies": ",".join(weights.keys()),
            "weights": weights,
            "scheme_type": "trading_scheme",
            "scheme": scheme,
            "strategy_overrides": strategy_overrides,
            "strategy_version_mode": args.strategy_version_mode,
            "entry": scheme.get("entry") or {"type": "strategy_weight_mix", "weights": weights},
            "exit_architecture": exit_architecture,
            "exit_architecture_type": str(exit_architecture.get("type") or "rebalance_only"),
            "exit_architecture_label": str(exit_architecture.get("label") or "跌出目标池卖出"),
            "position_rule": scheme.get("position_rule") or {},
            "rebalance_freq": args.rebalance_freq,
            "risk_rule": scheme.get("risk_rule") or {},
            "status": "ok",
            **result.summary,
            **_weight_exposure(result.weights),
            **exit_stats,
        }
        row["score"] = _scheme_score(row, args.objective, exit_architecture)
        row["reason"] = _reason(row)

    emit({"type": "progress", "stage": "save", "progress": 0.92, "message": "保存候选方案结果"})
    save_candidate(_resolve_db_path(args.db_path), args.run_id, row)
    emit({"type": "result", "stage": "done", "progress": 1.0, "row": row})

    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2, default=_json_default))


def save_candidate(db_path: Path, run_id: str, row: dict[str, Any]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path), timeout=30.0) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_optimization_candidates(
                run_id, candidate_id, rank, name, objective, status, score,
                strategies, weights_json, total_return, excess_annual_return,
                win_rate, annual_volatility, annual_return, max_drawdown, sharpe,
                calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount,
                exit_architecture_type, exit_architecture_label, exit_architecture_json,
                rebalance_freq, market_regime_filter, position_max_weight,
                validation_status, validation_json,
                reason, payload_json, created_at, updated_at
            ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(run_id, candidate_id) DO UPDATE SET
                rank = excluded.rank,
                name = excluded.name,
                objective = excluded.objective,
                status = excluded.status,
                score = excluded.score,
                strategies = excluded.strategies,
                weights_json = excluded.weights_json,
                total_return = excluded.total_return,
                excess_annual_return = excluded.excess_annual_return,
                win_rate = excluded.win_rate,
                annual_volatility = excluded.annual_volatility,
                annual_return = excluded.annual_return,
                max_drawdown = excluded.max_drawdown,
                sharpe = excluded.sharpe,
                calmar = excluded.calmar,
                avg_turnover = excluded.avg_turnover,
                avg_holdings = excluded.avg_holdings,
                avg_total_mv = excluded.avg_total_mv,
                avg_amount = excluded.avg_amount,
                exit_architecture_type = excluded.exit_architecture_type,
                exit_architecture_label = excluded.exit_architecture_label,
                exit_architecture_json = excluded.exit_architecture_json,
                rebalance_freq = excluded.rebalance_freq,
                market_regime_filter = excluded.market_regime_filter,
                position_max_weight = excluded.position_max_weight,
                validation_status = excluded.validation_status,
                validation_json = excluded.validation_json,
                reason = excluded.reason,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                run_id,
                row.get("candidate_id", ""),
                row.get("name", ""),
                row.get("objective", ""),
                row.get("status", ""),
                float(row.get("score") or 0),
                row.get("strategies", ""),
                json.dumps(row.get("weights") or {}, ensure_ascii=False),
                _float_or_none(row.get("total_return")),
                _float_or_none(row.get("excess_annual_return")),
                _float_or_none(row.get("win_rate")),
                _float_or_none(row.get("annual_volatility")),
                _float_or_none(row.get("annual_return")),
                _float_or_none(row.get("max_drawdown")),
                _float_or_none(row.get("sharpe")),
                _float_or_none(row.get("calmar")),
                _float_or_none(row.get("avg_turnover")),
                _float_or_none(row.get("avg_holdings")),
                _float_or_none(row.get("avg_total_mv")),
                _float_or_none(row.get("avg_amount")),
                row.get("exit_architecture_type", ""),
                row.get("exit_architecture_label", ""),
                json.dumps(row.get("exit_architecture") or {}, ensure_ascii=False, default=_json_default),
                int(row.get("rebalance_freq") or 0),
                _market_regime_filter(row.get("risk_rule")),
                _float_or_none(_safe_json_object(row.get("position_rule")).get("max_weight")),
                row.get("validation_status", ""),
                json.dumps(row.get("validation") or {}, ensure_ascii=False, default=_json_default),
                row.get("reason", ""),
                json.dumps(row, ensure_ascii=False, default=_json_default),
            ),
        )


def _safe_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _market_regime_filter(value: Any) -> str:
    risk = _safe_json_object(value)
    portfolio_risk = _safe_json_object(risk.get("portfolio_risk"))
    regime = _safe_json_object(portfolio_risk.get("market_regime"))
    if regime.get("enabled"):
        return "enabled"
    label = str(risk.get("label") or "")
    return label or "off"


def _candidate_risk(scheme: dict[str, Any], default_risk: dict[str, Any]) -> dict[str, Any]:
    risk_rule = _safe_json_object(scheme.get("risk_rule"))
    risk = _safe_json_object(risk_rule.get("portfolio_risk")) or dict(default_risk or {})
    position_rule = _safe_json_object(scheme.get("position_rule"))
    if position_rule:
        max_weight = position_rule.get("max_weight")
        if max_weight is not None:
            risk["max_single_weight"] = float(max_weight)
        max_holdings = position_rule.get("max_holdings")
        if max_holdings is not None:
            risk["max_holdings"] = int(max_holdings)
    return risk


def _apply_rebalance_freq(weights: pd.DataFrame, rebalance_freq: int) -> pd.DataFrame:
    if weights.empty or rebalance_freq <= 1:
        return weights
    sampled = weights.iloc[::rebalance_freq].copy()
    if sampled.empty:
        sampled = weights.iloc[[0]].copy()
    if sampled.index[0] != weights.index[0]:
        sampled = pd.concat([weights.iloc[[0]], sampled]).sort_index()
    return sampled.reindex(weights.index).ffill().fillna(0.0)


def _exit_architecture_stats(weights: pd.DataFrame, exit_architecture: dict[str, Any], rebalance_freq: int) -> dict[str, Any]:
    if weights.empty:
        return {
            "avg_holding_days": 0,
            "exit_reason_distribution": {},
            "exit_architecture_note": "无持仓",
        }
    active = weights.gt(1e-8)
    entries = active & ~active.shift(1, fill_value=False)
    exits = ~active & active.shift(1, fill_value=False)
    entry_count = int(entries.sum().sum())
    exit_count = int(exits.sum().sum())
    reason = str(exit_architecture.get("type") or "rebalance_only")
    label = str(exit_architecture.get("label") or "跌出目标池卖出")
    exit_distribution = {"signal_rebalance": exit_count}
    if reason != "rebalance_only":
        # 当前向量化回测尚不能逐笔模拟强制卖出；这里记录方案约束，供后续时光机执行层复用。
        exit_distribution[reason] = 0
    active_days = int(active.sum().sum())
    avg_positions = float(active.sum(axis=1).mean() or 0)
    avg_holding_days = active_days / max(entry_count, 1)
    return {
        "entry_count": entry_count,
        "exit_count": exit_count,
        "avg_holding_days": float(avg_holding_days),
        "avg_positions": avg_positions,
        "exit_reason_distribution": exit_distribution,
        "exit_architecture_note": label,
        "rebalance_freq": rebalance_freq,
    }


def _scheme_score(row: dict[str, Any], objective: str, exit_architecture: dict[str, Any]) -> float:
    score = _score(row, objective)
    turnover = float(row.get("avg_turnover") or 0)
    avg_holding_days = float(row.get("avg_holding_days") or 0)
    exit_type = str(exit_architecture.get("type") or "rebalance_only")
    if exit_type in {"stop_loss", "stop_loss_trailing", "tight_risk"}:
        score += 0.015 if float(row.get("max_drawdown") or 0) > -0.16 else -0.015
    if exit_type in {"trailing_stop", "stop_loss_trailing", "wide_risk"} and float(row.get("annual_return") or 0) > 0:
        score += 0.01
    if turnover > 0.35:
        score -= 0.03
    if avg_holding_days < 3:
        score -= 0.02
    return float(score)


if __name__ == "__main__":
    main()
