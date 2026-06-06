"""Factor research worker.

This script is launched by the Wails desktop task scheduler.  Go owns task
state and process supervision; this worker owns factor-research artifacts.
"""
from __future__ import annotations

import argparse
import math
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra.db import replace_sql, write_transaction
from research.data.storage import duckdb_query as dq


FACTOR_FAMILY_KEYS = {
    "估值": "value",
    "质量": "quality",
    "成长": "growth",
    "动量": "momentum",
    "反转过热": "reversal_heat",
    "风险": "risk",
    "流动性拥挤": "liquidity_crowding",
    "市值结构": "size_structure",
    "事件预期": "event_expectation",
}

SEED_FACTORS = [
    ("bp", "估值", 0.094, 0.739, "ready"),
    ("sp", "估值", 0.076, 0.689, "ready"),
    ("dv_ttm", "估值", 0.072, 0.655, "ready"),
    ("ep", "估值", 0.061, 0.605, "ready"),
    ("momentum_r", "动量", 0.045, 0.613, "ready"),
    ("ocfps", "质量", 0.032, 0.597, "design"),
    ("q_ocf_to_sales", "质量", 0.023, 0.664, "design"),
    ("q_sales_yoy", "成长", 0.017, 0.580, "design"),
    ("q_op_qoq", "成长", 0.016, 0.639, "design"),
]

FACTOR_DEFS: dict[str, tuple[str, bool]] = {
    "ep": ("估值", True),
    "bp": ("估值", True),
    "sp": ("估值", True),
    "dv_ttm": ("估值", True),
    "dv_ratio": ("估值", True),
    "pe_ttm": ("估值", False),
    "pe": ("估值", False),
    "pb": ("估值", False),
    "ps": ("估值", False),
    "ps_ttm": ("估值", False),
    "ep_ttm_z_ind": ("估值", True),
    "bp_z_ind": ("估值", True),
    "sp_ttm_z_ind": ("估值", True),
    "roe": ("质量", True),
    "roe_dt": ("质量", True),
    "roe_waa": ("质量", True),
    "roe_yearly": ("质量", True),
    "roa": ("质量", True),
    "roa_yearly": ("质量", True),
    "roic": ("质量", True),
    "grossprofit_margin": ("质量", True),
    "gross_margin": ("质量", True),
    "netprofit_margin": ("质量", True),
    "profit_to_gr": ("质量", True),
    "profit_to_op": ("质量", True),
    "ocf_to_debt": ("质量", True),
    "ocf_to_shortdebt": ("质量", True),
    "current_ratio": ("质量", True),
    "quick_ratio": ("质量", True),
    "debt_to_assets": ("质量", False),
    "debt_to_eqt": ("质量", False),
    "assets_to_eqt": ("质量", False),
    "q_ocf_to_sales": ("质量", True),
    "ocfps": ("质量", True),
    "cfps": ("质量", True),
    "fcff_ps": ("质量", True),
    "fcfe_ps": ("质量", True),
    "assets_turn": ("质量", True),
    "ar_turn": ("质量", True),
    "ca_turn": ("质量", True),
    "q_sales_yoy": ("成长", True),
    "q_op_qoq": ("成长", True),
    "netprofit_yoy": ("成长", True),
    "dt_netprofit_yoy": ("成长", True),
    "tr_yoy": ("成长", True),
    "or_yoy": ("成长", True),
    "op_yoy": ("成长", True),
    "ebt_yoy": ("成长", True),
    "ocf_yoy": ("成长", True),
    "assets_yoy": ("成长", True),
    "equity_yoy": ("成长", True),
    "bps_yoy": ("成长", True),
    "cfps_yoy": ("成长", True),
    "eps_yoy": ("成长", True),
    "ret20": ("动量", True),
    "ret5": ("反转过热", False),
    "ret10": ("反转过热", False),
    "ret60": ("动量", True),
    "ret120": ("动量", True),
    "ret240": ("动量", True),
    "ret20_60": ("动量", True),
    "ret60_120": ("动量", True),
    "ma20_over_ma60": ("动量", True),
    "trend_strength60": ("动量", True),
    "ret20_over_vol20": ("动量", True),
    "dist_ma20": ("反转过热", False),
    "dist_ma60": ("动量", True),
    "dist_high20": ("反转过热", False),
    "dist_high60": ("反转过热", False),
    "amount_spike20": ("反转过热", False),
    "up_days20": ("反转过热", False),
    "drawdown20": ("风险", True),
    "drawdown60": ("风险", True),
    "vol20": ("风险", False),
    "vol60": ("风险", False),
    "downvol20": ("风险", False),
    "gap_abs20": ("风险", False),
    "gap_down20": ("风险", True),
    "ret_min20": ("风险", True),
    "ret_min60": ("风险", True),
    "amihud20": ("流动性拥挤", False),
    "turnover_rate": ("流动性拥挤", False),
    "turnover_rate_f": ("流动性拥挤", False),
    "volume_ratio": ("流动性拥挤", False),
    "turnover_chg20": ("流动性拥挤", False),
    "amount_chg20": ("流动性拥挤", False),
    "amount": ("流动性拥挤", True),
    "log_amount": ("流动性拥挤", True),
    "float_share": ("市值结构", False),
    "free_share": ("市值结构", False),
    "log_total_mv": ("市值结构", False),
    "log_circ_mv": ("市值结构", False),
    "circ_mv_to_total_mv": ("市值结构", True),
    "listed_days": ("市值结构", True),
    "forecast_growth": ("事件预期", True),
    "forecast_profit": ("事件预期", True),
    "forecast_positive": ("事件预期", True),
    "lhb_count_180": ("事件预期", True),
    "lhb_net_amount_180": ("事件预期", True),
    "lhb_net_rate_180": ("事件预期", True),
    "lhb_amount_rate_180": ("事件预期", False),
    "inst_net_buy_180": ("事件预期", True),
    "holder_buy_value_180": ("事件预期", True),
    "holder_buy_count_180": ("事件预期", True),
    "holder_sell_value_180": ("事件预期", False),
}

MODEL_FACTOR_ORDER = [
    "turnover_rate", "turnover_rate_f", "volume_ratio", "turnover_chg20", "amount_chg20",
    "vol20", "vol60", "downvol20", "gap_abs20", "gap_down20", "ret_min20", "ret_min60", "amihud20",
    "bp", "ep", "sp", "dv_ttm", "dv_ratio", "bp_z_ind", "ep_ttm_z_ind", "sp_ttm_z_ind",
    "ocfps", "cfps", "fcff_ps", "fcfe_ps", "q_ocf_to_sales", "ocf_to_debt",
    "q_sales_yoy", "q_op_qoq", "netprofit_yoy", "dt_netprofit_yoy", "tr_yoy", "or_yoy", "op_yoy", "ocf_yoy",
    "roe", "roe_dt", "roe_waa", "roa", "roic", "grossprofit_margin", "netprofit_margin", "profit_to_gr", "assets_turn",
    "debt_to_assets", "debt_to_eqt", "assets_to_eqt", "current_ratio", "quick_ratio",
    "ret5", "ret10", "ret20", "ret60", "ret120", "ret240", "ret20_60", "ret60_120", "ma20_over_ma60", "trend_strength60", "ret20_over_vol20",
    "dist_ma20", "dist_ma60", "dist_high20", "dist_high60", "amount_spike20", "up_days20", "drawdown20", "drawdown60",
    "amount", "log_amount", "log_total_mv", "log_circ_mv", "circ_mv_to_total_mv", "listed_days",
    "forecast_growth", "forecast_profit", "forecast_positive", "lhb_count_180", "lhb_net_amount_180", "lhb_net_rate_180",
    "lhb_amount_rate_180", "inst_net_buy_180", "holder_buy_value_180", "holder_buy_count_180", "holder_sell_value_180",
]

MODEL_FAMILY_MIN_QUOTAS = {
    "事件预期": 3,
    "成长": 5,
    "质量": 5,
    "估值": 6,
    "风险": 5,
    "流动性拥挤": 5,
    "反转过热": 3,
    "动量": 2,
    "市值结构": 2,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=[
            "build_factor_panel",
            "evaluate_factors",
            "train_lgbm",
            "factor_correlation_report",
            "latest_inference",
            "stress_report",
        ],
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--freq", default="monthly")
    parser.add_argument("--label", default="fwd20_excess_industry")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--min-train-years", type=int, default=4)
    parser.add_argument("--min-test-year", type=int, default=0)
    args = parser.parse_args()

    ensure_tables(args.db_path)
    mark_stage(args.db_path, args.run_id, args.stage, "running", summary={"stage": args.stage})
    try:
        if args.stage == "build_factor_panel":
            summary = build_factor_panel(args)
        elif args.stage == "evaluate_factors":
            summary = evaluate_factors(args)
        elif args.stage == "train_lgbm":
            summary = train_lgbm(args)
        elif args.stage == "factor_correlation_report":
            summary = factor_correlation_report(args)
        elif args.stage == "latest_inference":
            summary = latest_inference(args)
        else:
            summary = stress_report(args)
        mark_stage(args.db_path, args.run_id, args.stage, "success", summary=summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        mark_stage(args.db_path, args.run_id, args.stage, "failed", summary={"stage": args.stage}, error=str(exc))
        raise


def ensure_tables(db_path: str | None) -> None:
    with write_transaction(db_path) as conn:
        if conn.backend == "mysql":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_research_runs (
                    run_id VARCHAR(255) PRIMARY KEY,
                    start_date VARCHAR(16) NOT NULL,
                    end_date VARCHAR(16) NOT NULL,
                    freq VARCHAR(32) NOT NULL,
                    label VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_research_stage_results (
                    run_id VARCHAR(255) NOT NULL,
                    stage VARCHAR(128) NOT NULL,
                    sequence BIGINT NOT NULL DEFAULT 0,
                    status VARCHAR(32) NOT NULL,
                    summary_json LONGTEXT,
                    error LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, stage)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_panel_meta (
                    run_id VARCHAR(255) PRIMARY KEY,
                    start_date VARCHAR(16) NOT NULL,
                    end_date VARCHAR(16) NOT NULL,
                    freq VARCHAR(32) NOT NULL,
                    factor_count BIGINT NOT NULL DEFAULT 0,
                    sample_dates BIGINT NOT NULL DEFAULT 0,
                    sample_rows BIGINT NOT NULL DEFAULT 0,
                    label VARCHAR(128) NOT NULL,
                    panel_path VARCHAR(1024),
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_ic_results (
                    run_id VARCHAR(255) NOT NULL,
                    factor VARCHAR(255) NOT NULL,
                    family VARCHAR(128) NOT NULL,
                    variant VARCHAR(64) NOT NULL,
                    horizon VARCHAR(32) NOT NULL,
                    ic_mean DOUBLE,
                    rank_ic_mean DOUBLE,
                    ic_win_rate DOUBLE,
                    icir DOUBLE,
                    status VARCHAR(32) NOT NULL,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, factor, variant, horizon)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_quantile_results (
                    run_id VARCHAR(255) NOT NULL,
                    factor VARCHAR(255) NOT NULL,
                    variant VARCHAR(64) NOT NULL,
                    horizon VARCHAR(32) NOT NULL,
                    q1_return DOUBLE,
                    q5_return DOUBLE,
                    long_short_return DOUBLE,
                    monotonic_score DOUBLE,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, factor, variant, horizon)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_model_runs (
                    run_id VARCHAR(255) PRIMARY KEY,
                    model_type VARCHAR(64) NOT NULL,
                    label VARCHAR(128) NOT NULL,
                    feature_count BIGINT NOT NULL DEFAULT 0,
                    status VARCHAR(32) NOT NULL,
                    summary_json LONGTEXT,
                    model_path VARCHAR(1024),
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_model_features (
                    run_id VARCHAR(255) NOT NULL,
                    feature VARCHAR(255) NOT NULL,
                    importance DOUBLE,
                    rank_no BIGINT NOT NULL DEFAULT 0,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, feature)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_model_predictions (
                    run_id VARCHAR(255) NOT NULL,
                    trade_date VARCHAR(16) NOT NULL,
                    ts_code VARCHAR(32) NOT NULL,
                    pred_score DOUBLE,
                    realized_return DOUBLE,
                    pred_rank DOUBLE,
                    test_year BIGINT,
                    is_top20 TINYINT NOT NULL DEFAULT 0,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, trade_date, ts_code),
                    KEY idx_factor_model_predictions_run_date (run_id, trade_date),
                    KEY idx_factor_model_predictions_top (run_id, is_top20, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_correlation_results (
                    run_id VARCHAR(255) NOT NULL,
                    feature_a VARCHAR(255) NOT NULL,
                    feature_b VARCHAR(255) NOT NULL,
                    correlation DOUBLE,
                    abs_correlation DOUBLE,
                    family_a VARCHAR(128),
                    family_b VARCHAR(128),
                    keep_feature VARCHAR(255),
                    drop_feature VARCHAR(255),
                    reason VARCHAR(255),
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, feature_a, feature_b),
                    KEY idx_factor_correlation_run_abs (run_id, abs_correlation)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_latest_predictions (
                    run_id VARCHAR(255) NOT NULL,
                    trade_date VARCHAR(16) NOT NULL,
                    ts_code VARCHAR(32) NOT NULL,
                    pred_score DOUBLE,
                    pred_rank DOUBLE,
                    is_top20 TINYINT NOT NULL DEFAULT 0,
                    model_path VARCHAR(1024),
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, trade_date, ts_code),
                    KEY idx_factor_latest_run_date (run_id, trade_date),
                    KEY idx_factor_latest_top (run_id, is_top20, trade_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_model_stress_results (
                    run_id VARCHAR(255) NOT NULL,
                    bucket_type VARCHAR(64) NOT NULL,
                    bucket_key VARCHAR(128) NOT NULL,
                    bucket_label VARCHAR(255) NOT NULL,
                    start_date VARCHAR(16) NOT NULL,
                    end_date VARCHAR(16) NOT NULL,
                    n_days BIGINT NOT NULL DEFAULT 0,
                    total_return DOUBLE,
                    annual_return DOUBLE,
                    max_drawdown DOUBLE,
                    sharpe DOUBLE,
                    win_rate DOUBLE,
                    avg_daily_return DOUBLE,
                    volatility DOUBLE,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, bucket_type, bucket_key),
                    KEY idx_factor_stress_run_type (run_id, bucket_type),
                    KEY idx_factor_stress_drawdown (run_id, max_drawdown)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        else:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS factor_research_runs (
                    run_id TEXT PRIMARY KEY,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    freq TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS factor_research_stage_results (
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, stage)
                );
                CREATE TABLE IF NOT EXISTS factor_panel_meta (
                    run_id TEXT PRIMARY KEY,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    freq TEXT NOT NULL,
                    factor_count INTEGER NOT NULL DEFAULT 0,
                    sample_dates INTEGER NOT NULL DEFAULT 0,
                    sample_rows INTEGER NOT NULL DEFAULT 0,
                    label TEXT NOT NULL,
                    panel_path TEXT,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS factor_ic_results (
                    run_id TEXT NOT NULL,
                    factor TEXT NOT NULL,
                    family TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    ic_mean REAL,
                    rank_ic_mean REAL,
                    ic_win_rate REAL,
                    icir REAL,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, factor, variant, horizon)
                );
                CREATE TABLE IF NOT EXISTS factor_quantile_results (
                    run_id TEXT NOT NULL,
                    factor TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    q1_return REAL,
                    q5_return REAL,
                    long_short_return REAL,
                    monotonic_score REAL,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, factor, variant, horizon)
                );
                CREATE TABLE IF NOT EXISTS factor_model_runs (
                    run_id TEXT PRIMARY KEY,
                    model_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    feature_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    model_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS factor_model_features (
                    run_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    importance REAL,
                    rank_no INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, feature)
                );
                CREATE TABLE IF NOT EXISTS factor_model_predictions (
                    run_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    ts_code TEXT NOT NULL,
                    pred_score REAL,
                    realized_return REAL,
                    pred_rank REAL,
                    test_year INTEGER,
                    is_top20 INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, trade_date, ts_code)
                );
                CREATE TABLE IF NOT EXISTS factor_correlation_results (
                    run_id TEXT NOT NULL,
                    feature_a TEXT NOT NULL,
                    feature_b TEXT NOT NULL,
                    correlation REAL,
                    abs_correlation REAL,
                    family_a TEXT,
                    family_b TEXT,
                    keep_feature TEXT,
                    drop_feature TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, feature_a, feature_b)
                );
                CREATE TABLE IF NOT EXISTS factor_latest_predictions (
                    run_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    ts_code TEXT NOT NULL,
                    pred_score REAL,
                    pred_rank REAL,
                    is_top20 INTEGER NOT NULL DEFAULT 0,
                    model_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, trade_date, ts_code)
                );
                CREATE TABLE IF NOT EXISTS factor_model_stress_results (
                    run_id TEXT NOT NULL,
                    bucket_type TEXT NOT NULL,
                    bucket_key TEXT NOT NULL,
                    bucket_label TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    n_days INTEGER NOT NULL DEFAULT 0,
                    total_return REAL,
                    annual_return REAL,
                    max_drawdown REAL,
                    sharpe REAL,
                    win_rate REAL,
                    avg_daily_return REAL,
                    volatility REAL,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, bucket_type, bucket_key)
                );
                """
            )


def build_factor_panel(args: argparse.Namespace) -> dict[str, Any]:
    panel = build_monthly_factor_panel(args.start, args.end)
    panel_dir = data_root() / "factor_research" / args.run_id
    panel_dir.mkdir(parents=True, exist_ok=True)
    panel_path_abs = panel_dir / "monthly_factor_panel.parquet"
    panel.to_parquet(panel_path_abs, index=False, compression="zstd")

    coverage = data_coverage(args.start, args.end)
    factor_count = len(FACTOR_DEFS)
    families = factor_family_summary()
    sample_dates = int(panel["trade_date"].nunique()) if not panel.empty else 0
    sample_rows = int(len(panel))
    panel_path = str(panel_path_abs)
    summary = {
        "stage": args.stage,
        "start": args.start,
        "end": args.end,
        "freq": args.freq,
        "label": args.label,
        "factor_count": factor_count,
        "family_count": len(families),
        "sample_dates": sample_dates,
        "sample_rows": sample_rows,
        "label_rows": int(panel[args.label].notna().sum()) if args.label in panel.columns else 0,
        "panel_path": panel_path,
        "coverage": coverage,
        "families": families,
    }
    now = now_text()
    with write_transaction(args.db_path) as conn:
        conn.execute(
            replace_sql("factor_research_runs", ["run_id", "start_date", "end_date", "freq", "label", "status", "summary_json", "created_at", "updated_at"], ["run_id"]),
            (args.run_id, args.start, args.end, args.freq, args.label, "running", json.dumps(summary, ensure_ascii=False), now, now),
        )
        conn.execute(
            replace_sql("factor_panel_meta", ["run_id", "start_date", "end_date", "freq", "factor_count", "sample_dates", "sample_rows", "label", "panel_path", "summary_json", "created_at", "updated_at"], ["run_id"]),
            (args.run_id, args.start, args.end, args.freq, factor_count, sample_dates, sample_rows, args.label, panel_path, json.dumps(summary, ensure_ascii=False), now, now),
        )
    return summary


def factor_family_summary() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for family, _ in FACTOR_DEFS.values():
        counts[family] = counts.get(family, 0) + 1
    return [
        {"key": FACTOR_FAMILY_KEYS.get(label, label), "label": label, "count": counts[label]}
        for label in FACTOR_FAMILY_KEYS
        if label in counts
    ]


def evaluate_factors(args: argparse.Namespace) -> dict[str, Any]:
    panel_path = panel_path_for(args.run_id)
    if not panel_path.exists():
        raise FileNotFoundError(f"factor panel not found: {panel_path}")
    panel = pd.read_parquet(panel_path)
    if args.label not in panel.columns:
        raise ValueError(f"label column not found: {args.label}")
    now = now_text()
    jobs = []
    for factor, (family, high_good) in FACTOR_DEFS.items():
        for variant, value_col in [("rank", f"{factor}_rank"), ("neutral", f"{factor}_neutral")]:
            if value_col in panel.columns:
                jobs.append((factor, family, high_good, variant, value_col))
    rows = []
    qrows = []
    max_workers = min(8, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_evaluate_factor_variant, panel, args.label, factor, family, high_good, variant, value_col): (factor, variant)
            for factor, family, high_good, variant, value_col in jobs
        }
        for future in as_completed(future_map):
            result = future.result()
            if result is None:
                continue
            row, qrow = result
            rows.append(row)
            qrows.append(qrow)
    rows = sorted(rows, key=lambda row: float(row.get("rank_ic_mean") or -999), reverse=True)
    with write_transaction(args.db_path) as conn:
        ic_sql = replace_sql("factor_ic_results", ["run_id", "factor", "family", "variant", "horizon", "ic_mean", "rank_ic_mean", "ic_win_rate", "icir", "status", "summary_json", "created_at", "updated_at"], ["run_id", "factor", "variant", "horizon"])
        quantile_sql = replace_sql("factor_quantile_results", ["run_id", "factor", "variant", "horizon", "q1_return", "q5_return", "long_short_return", "monotonic_score", "summary_json", "created_at", "updated_at"], ["run_id", "factor", "variant", "horizon"])
        ic_params = []
        quantile_params = []
        for row in rows:
            stats = row.pop("_stats")
            summary = row.pop("_summary")
            factor = row["factor"]
            family = row["family"]
            variant = row["variant"]
            status = row["status"]
            ic_params.append((args.run_id, factor, family, variant, args.label, stats["ic_mean"], stats["rank_ic_mean"], stats["ic_win_rate"], stats["icir"], status, json.dumps(summary, ensure_ascii=False), now, now))
            quantile_params.append((args.run_id, factor, variant, args.label, stats["q1_return"], stats["q5_return"], stats["long_short_return"], stats["monotonic_score"], json.dumps(summary, ensure_ascii=False), now, now))
        if ic_params:
            conn.executemany(ic_sql, ic_params)
        if quantile_params:
            conn.executemany(quantile_sql, quantile_params)
    return {
        "stage": args.stage,
        "factor_count": len(FACTOR_DEFS),
        "variant_count": len(rows),
        "ready_count": sum(1 for row in rows if row["status"] == "ready"),
        "label": args.label,
        "panel_path": str(panel_path),
        "rows": rows,
        "quantiles": qrows,
    }


def _evaluate_factor_variant(
    panel: pd.DataFrame,
    label: str,
    factor: str,
    family: str,
    high_good: bool,
    variant: str,
    value_col: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    stats = factor_stats(panel, value_col, label)
    if not stats:
        return None
    summary = {
        "source": "factor_panel",
        "n_periods": stats["n_periods"],
        "n_obs": stats["n_obs"],
        "high_good": high_good,
        "value_col": value_col,
        "quantiles": stats["quantiles"],
    }
    status = factor_status(stats)
    row = {
        "factor": factor,
        "family": family,
        "variant": variant,
        "rank_ic_mean": stats["rank_ic_mean"],
        "ic_win_rate": stats["ic_win_rate"],
        "icir": stats["icir"],
        "status": status,
        "_stats": stats,
        "_summary": summary,
    }
    qrow = {
        "factor": factor,
        "variant": variant,
        "q1_return": stats["q1_return"],
        "q5_return": stats["q5_return"],
        "long_short_return": stats["long_short_return"],
        "monotonic_score": stats["monotonic_score"],
    }
    return row, qrow


def train_lgbm(args: argparse.Namespace) -> dict[str, Any]:
    now = now_text()
    panel_path = panel_path_for(args.run_id)
    if not panel_path.exists():
        raise FileNotFoundError(f"factor panel not found: {panel_path}")
    lgb, import_error = import_lightgbm()
    if lgb is None:
        feature_count = len(FACTOR_DEFS) * 2
        summary = {
            "stage": args.stage,
            "model_type": "lightgbm_ranker",
            "label": args.label,
            "feature_count": feature_count,
            "status": "planned",
            "lightgbm_available": False,
            "note": import_error or "LightGBM package is not installed yet.",
        }
        model_path = str((data_root() / "factor_research" / args.run_id / "models" / "lightgbm_ranker.txt"))
        with write_transaction(args.db_path) as conn:
            conn.execute(
                replace_sql("factor_model_runs", ["run_id", "model_type", "label", "feature_count", "status", "summary_json", "model_path", "created_at", "updated_at"], ["run_id"]),
                (args.run_id, "lightgbm_ranker", args.label, feature_count, "planned", json.dumps(summary, ensure_ascii=False), model_path, now, now),
            )
            conn.execute(
                replace_sql("factor_research_runs", ["run_id", "start_date", "end_date", "freq", "label", "status", "summary_json", "created_at", "updated_at"], ["run_id"]),
                (args.run_id, args.start, args.end, args.freq, args.label, "partial", json.dumps(summary, ensure_ascii=False), now, now),
            )
        return summary

    panel = pd.read_parquet(panel_path)
    feature_cols = selected_model_features(panel, args.db_path, args.run_id, args.label)
    if args.label not in panel.columns:
        raise ValueError(f"label column not found: {args.label}")
    data = panel[["trade_date", "ts_code", args.label, *feature_cols]].replace([np.inf, -np.inf], np.nan).dropna(subset=[args.label]).copy()
    for col in feature_cols:
        data[col] = data.groupby("trade_date")[col].transform(lambda s: s.fillna(s.median()))
    data = data.dropna(subset=feature_cols)
    data["year"] = data["trade_date"].astype(str).str.slice(0, 4).astype(int)
    years = sorted(data["year"].unique().tolist())
    min_train_years = max(1, int(getattr(args, "min_train_years", 4) or 4))
    first_oos_year = min(years) + min_train_years
    min_test_year = int(getattr(args, "min_test_year", 0) or 0)
    if min_test_year > 0:
        first_oos_year = max(first_oos_year, min_test_year)
    test_years = [year for year in years if year >= first_oos_year]
    predictions = []
    importances = pd.Series(0.0, index=feature_cols)
    model_dir = data_root() / "factor_research" / args.run_id / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    last_model_path = model_dir / "lightgbm_regressor.txt"
    for test_year in test_years:
        train = data[data["year"] < test_year]
        test = data[data["year"] == test_year]
        if len(train) < 5000 or len(test) < 500:
            continue
        model = lgb.LGBMRegressor(
            objective="regression",
            n_estimators=220,
            learning_rate=0.035,
            num_leaves=31,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_samples=80,
            reg_alpha=0.05,
            reg_lambda=0.20,
            random_state=20260606,
            n_jobs=4,
            verbose=-1,
        )
        model.fit(train[feature_cols], train[args.label])
        pred = test[["trade_date", "ts_code", args.label]].copy()
        pred["pred_score"] = model.predict(test[feature_cols])
        pred["test_year"] = test_year
        predictions.append(pred)
        importances = importances.add(pd.Series(model.feature_importances_, index=feature_cols), fill_value=0.0)
        if test_year == test_years[-1]:
            model.booster_.save_model(str(last_model_path))
    if not predictions:
        raise RuntimeError("no walk-forward folds generated")
    pred_df = pd.concat(predictions, ignore_index=True)
    pred_df["pred_rank"] = pred_df.groupby("trade_date")["pred_score"].rank(pct=True)
    pred_df["is_top20"] = (pred_df["pred_rank"] >= 0.8).astype(int)
    prediction_path = data_root() / "factor_research" / args.run_id / "predictions.parquet"
    pred_df.to_parquet(prediction_path, index=False, compression="zstd")
    metrics = model_oos_metrics(pred_df, args.label)
    importance_df = (
        importances.sort_values(ascending=False)
        .reset_index()
        .rename(columns={"index": "feature", 0: "importance"})
    )
    feature_count = len(feature_cols)
    summary = {
        "stage": args.stage,
        "model_type": "lightgbm_regressor",
        "label": args.label,
        "feature_count": feature_count,
        "status": "success",
        "lightgbm_available": True,
        "fold_count": int(len(predictions)),
        "min_train_years": min_train_years,
        "first_oos_year": int(first_oos_year),
        "oos_rank_ic_mean": metrics["oos_rank_ic_mean"],
        "oos_ic_win_rate": metrics["oos_ic_win_rate"],
        "top20_mean_return": metrics["top20_mean_return"],
        "bottom20_mean_return": metrics["bottom20_mean_return"],
        "top_bottom_spread": metrics["top_bottom_spread"],
        "test_years": sorted(pred_df["test_year"].unique().astype(int).tolist()),
        "prediction_rows": int(len(pred_df)),
        "top20_rows": int(pred_df["is_top20"].sum()),
        "prediction_path": str(prediction_path),
        "top_features": importance_df.head(12).to_dict(orient="records"),
    }
    model_path = str(last_model_path)
    with write_transaction(args.db_path) as conn:
        conn.execute(
            replace_sql("factor_model_runs", ["run_id", "model_type", "label", "feature_count", "status", "summary_json", "model_path", "created_at", "updated_at"], ["run_id"]),
            (args.run_id, "lightgbm_regressor", args.label, feature_count, "success", json.dumps(summary, ensure_ascii=False), model_path, now, now),
        )
        feature_sql = replace_sql("factor_model_features", ["run_id", "feature", "importance", "rank_no", "summary_json", "created_at", "updated_at"], ["run_id", "feature"])
        feature_params = []
        for idx, row in importance_df.iterrows():
            feature = str(row["feature"])
            row_summary = {"feature_family": feature_family_from_rank_col(feature)}
            feature_params.append((args.run_id, feature, float(row["importance"]), int(idx + 1), json.dumps(row_summary, ensure_ascii=False), now, now))
        if feature_params:
            conn.executemany(feature_sql, feature_params)
        prediction_rows = pred_df[pred_df["is_top20"] == 1].copy()
        prediction_sql = replace_sql("factor_model_predictions", ["run_id", "trade_date", "ts_code", "pred_score", "realized_return", "pred_rank", "test_year", "is_top20", "created_at", "updated_at"], ["run_id", "trade_date", "ts_code"])
        prediction_params = [
            (args.run_id, str(row.trade_date), str(row.ts_code), float(row.pred_score), float(getattr(row, args.label)), float(row.pred_rank), int(row.test_year), int(row.is_top20), now, now)
            for row in prediction_rows.itertuples(index=False)
        ]
        if prediction_params:
            conn.executemany(prediction_sql, prediction_params)
        conn.execute(
            replace_sql("factor_research_runs", ["run_id", "start_date", "end_date", "freq", "label", "status", "summary_json", "created_at", "updated_at"], ["run_id"]),
            (args.run_id, args.start, args.end, args.freq, args.label, "success", json.dumps(summary, ensure_ascii=False), now, now),
        )
    return summary


def factor_correlation_report(args: argparse.Namespace) -> dict[str, Any]:
    panel_path = panel_path_for(args.run_id)
    if not panel_path.exists():
        raise FileNotFoundError(f"factor panel not found: {panel_path}")
    available_cols = _parquet_columns(panel_path)
    candidate_cols = [
        col
        for factor in FACTOR_DEFS
        for col in (f"{factor}_rank", f"{factor}_neutral")
        if col in available_cols
    ]
    panel = pd.read_parquet(panel_path, columns=["trade_date", *candidate_cols])
    ordered = selected_features_from_ic(args.db_path, args.run_id, args.label)
    ordered = [col for col in ordered if col in candidate_cols]
    if not ordered:
        ordered = [
            col
            for factor in MODEL_FACTOR_ORDER
            for col in (f"{factor}_rank", f"{factor}_neutral")
            if col in candidate_cols
        ]
    selected = prune_correlated_features(panel, ordered, max_features=45, corr_limit=0.92, max_rows=20_000, stratified=False)
    sample = correlation_sample(panel, candidate_cols, max_rows=20_000, stratified=False).replace([np.inf, -np.inf], np.nan)
    corr = sample.corr(method="spearman", min_periods=200)
    rows: list[dict[str, Any]] = []
    selected_rank = {feature: idx for idx, feature in enumerate(selected)}
    ordered_rank = {feature: idx for idx, feature in enumerate(ordered)}
    for i, feature_a in enumerate(candidate_cols):
        for feature_b in candidate_cols[i + 1:]:
            value = corr.at[feature_a, feature_b] if feature_a in corr.index and feature_b in corr.columns else np.nan
            if not np.isfinite(value) or abs(float(value)) < 0.88:
                continue
            keep, drop = _correlation_keep_drop(feature_a, feature_b, selected_rank, ordered_rank)
            rows.append(
                {
                    "feature_a": feature_a,
                    "feature_b": feature_b,
                    "correlation": float(value),
                    "abs_correlation": abs(float(value)),
                    "family_a": feature_family_from_rank_col(feature_a),
                    "family_b": feature_family_from_rank_col(feature_b),
                    "keep_feature": keep,
                    "drop_feature": drop,
                    "reason": _correlation_reason(feature_a, feature_b, keep, drop),
                }
            )
    rows.sort(key=lambda row: row["abs_correlation"], reverse=True)
    now = now_text()
    report_path = data_root() / "factor_research" / args.run_id / "factor_correlation_report.parquet"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(report_path, index=False, compression="zstd")
    with write_transaction(args.db_path) as conn:
        conn.execute("DELETE FROM factor_correlation_results WHERE run_id = ?", (args.run_id,))
        sql = replace_sql(
            "factor_correlation_results",
            [
                "run_id", "feature_a", "feature_b", "correlation", "abs_correlation",
                "family_a", "family_b", "keep_feature", "drop_feature", "reason",
                "created_at", "updated_at",
            ],
            ["run_id", "feature_a", "feature_b"],
        )
        params = [
            (
                args.run_id,
                str(row["feature_a"]),
                str(row["feature_b"]),
                float(row["correlation"]),
                float(row["abs_correlation"]),
                str(row["family_a"]),
                str(row["family_b"]),
                str(row["keep_feature"]),
                str(row["drop_feature"]),
                str(row["reason"]),
                now,
                now,
            )
            for row in rows
        ]
        if params:
            conn.executemany(sql, params)
    return {
        "stage": args.stage,
        "feature_count": len(candidate_cols),
        "selected_feature_count": len(selected),
        "high_corr_pair_count": len(rows),
        "corr_limit": 0.88,
        "report_path": str(report_path),
        "top_pairs": rows[:20],
    }


def latest_inference(args: argparse.Namespace) -> dict[str, Any]:
    lgb, import_error = import_lightgbm()
    if lgb is None:
        raise RuntimeError(import_error or "LightGBM package is not installed")
    panel_path = panel_path_for(args.run_id)
    if not panel_path.exists():
        raise FileNotFoundError(f"factor panel not found: {panel_path}")
    model_path = _model_path_from_db(args.db_path, args.run_id)
    if not model_path:
        raise FileNotFoundError(f"model path not found for run_id={args.run_id}")
    model_file = Path(model_path)
    if not model_file.exists():
        raise FileNotFoundError(f"model file not found: {model_file}")
    booster = lgb.Booster(model_file=str(model_file))
    booster_features = [str(feature) for feature in booster.feature_name() if str(feature)]
    feature_cols = booster_features or _model_features_from_db(args.db_path, args.run_id)
    available_cols = _parquet_columns(panel_path)
    if feature_cols:
        read_cols = ["trade_date", "ts_code", *[feature for feature in feature_cols if feature in available_cols]]
        panel = pd.read_parquet(panel_path, columns=read_cols)
        feature_cols = [feature for feature in feature_cols if feature in panel.columns]
    else:
        candidate_cols = [
            col
            for factor in FACTOR_DEFS
            for col in (f"{factor}_rank", f"{factor}_neutral")
            if col in available_cols
        ]
        panel = pd.read_parquet(panel_path, columns=["trade_date", "ts_code", *candidate_cols])
        feature_cols = selected_model_features(panel, args.db_path, args.run_id, args.label)
    if not feature_cols:
        raise RuntimeError("no model features available for latest inference")
    if panel.empty:
        raise RuntimeError("factor panel is empty")
    latest_date = str(panel["trade_date"].max())
    latest = panel[panel["trade_date"].astype(str) == latest_date][["trade_date", "ts_code", *feature_cols]].copy()
    latest = latest.replace([np.inf, -np.inf], np.nan)
    for col in feature_cols:
        latest[col] = pd.to_numeric(latest[col], errors="coerce")
        latest[col] = latest[col].fillna(latest[col].median())
    latest = latest.dropna(subset=feature_cols)
    if latest.empty:
        raise RuntimeError(f"no valid latest inference rows for {latest_date}")
    latest["pred_score"] = booster.predict(latest[feature_cols])
    latest["pred_rank"] = latest["pred_score"].rank(pct=True)
    latest["is_top20"] = (latest["pred_rank"] >= 0.8).astype(int)
    out = latest[["trade_date", "ts_code", "pred_score", "pred_rank", "is_top20"]].sort_values("pred_score", ascending=False)
    prediction_path = data_root() / "factor_research" / args.run_id / "latest_predictions.parquet"
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(prediction_path, index=False, compression="zstd")
    now = now_text()
    with write_transaction(args.db_path) as conn:
        conn.execute("DELETE FROM factor_latest_predictions WHERE run_id = ? AND trade_date = ?", (args.run_id, latest_date))
        sql = replace_sql(
            "factor_latest_predictions",
            ["run_id", "trade_date", "ts_code", "pred_score", "pred_rank", "is_top20", "model_path", "created_at", "updated_at"],
            ["run_id", "trade_date", "ts_code"],
        )
        params = [
            (
                args.run_id,
                str(row.trade_date),
                str(row.ts_code),
                float(row.pred_score),
                float(row.pred_rank),
                int(row.is_top20),
                str(model_file),
                now,
                now,
            )
            for row in out.itertuples(index=False)
        ]
        if params:
            conn.executemany(sql, params)
    return {
        "stage": args.stage,
        "trade_date": latest_date,
        "feature_count": len(feature_cols),
        "prediction_rows": int(len(out)),
        "top20_rows": int(out["is_top20"].sum()),
        "prediction_path": str(prediction_path),
        "model_path": str(model_file),
        "top_candidates": out.head(20).to_dict(orient="records"),
    }


def stress_report(args: argparse.Namespace) -> dict[str, Any]:
    from common.config.desktop_settings import load_strategy_settings
    from trading.backtest import BacktestConfig, CostModel, run as bt_run
    from trading.backtest.metrics import summary as metric_summary
    from trading.strategy import registry

    settings = load_strategy_settings()
    cfg = settings.get("ml_factor_ranker", {}).copy()
    cfg["selection"] = dict(cfg.get("selection") or {})
    cfg["selection"]["run_id"] = args.run_id
    regime = dict((cfg.get("filters") or {}).get("market_regime") or {})
    for key in ["daily_risk_overlay", "risk_state_only", "risk_state", "crisis_guard"]:
        regime.pop(key, None)
    cfg["filters"] = dict(cfg.get("filters") or {})
    cfg["filters"]["market_regime"] = regime

    old_override = os.environ.get("QUANT_STRATEGY_OVERRIDES_JSON")
    old_mode = os.environ.get("QUANT_STRATEGY_VERSION_MODE")
    os.environ["QUANT_STRATEGY_OVERRIDES_JSON"] = json.dumps({"ml_factor_ranker": cfg}, ensure_ascii=False)
    os.environ["QUANT_STRATEGY_VERSION_MODE"] = "latest"
    try:
        strategy = registry.build("ml_factor_ranker")
        weights = strategy.generate_target_weights(args.start, args.end)
        if weights.empty:
            raise RuntimeError("ml_factor_ranker produced empty weights")
        result = bt_run(
            weights,
            BacktestConfig(
                start=args.start,
                end=args.end,
                cost=CostModel(slippage=0.002),
                benchmark="000905.SH",
                progress=False,
            ),
        )
    finally:
        if old_override is None:
            os.environ.pop("QUANT_STRATEGY_OVERRIDES_JSON", None)
        else:
            os.environ["QUANT_STRATEGY_OVERRIDES_JSON"] = old_override
        if old_mode is None:
            os.environ.pop("QUANT_STRATEGY_VERSION_MODE", None)
        else:
            os.environ["QUANT_STRATEGY_VERSION_MODE"] = old_mode

    active_mask = result.weights.where(result.weights > 1e-8, 0.0).sum(axis=1) > 1e-8
    if not active_mask.any():
        raise RuntimeError("ml_factor_ranker has no active holding period")
    active_start = str(active_mask[active_mask].index[0])
    active_end = str(active_mask[active_mask].index[-1])
    returns = result.returns.loc[active_start:active_end].astype(float)
    weights = result.weights.loc[active_start:active_end]

    rows: list[dict[str, Any]] = []
    rows.append(_stress_metric_row("full", "active", "有效持仓全周期", returns, weights, metric_summary))
    for year, group in returns.groupby(returns.index.astype(str).str.slice(0, 4), sort=True):
        rows.append(_stress_metric_row("year", str(year), f"{year}年", group, weights.loc[group.index], metric_summary))
    for key, label, start, end in _event_periods():
        segment = returns.loc[max(start, active_start):min(end, active_end)]
        if not segment.empty:
            rows.append(_stress_metric_row("event", key, label, segment, weights.loc[segment.index], metric_summary))
    rows.extend(_market_state_stress_rows(args.db_path, args.run_id, returns, weights, metric_summary))

    now = now_text()
    report_path = data_root() / "factor_research" / args.run_id / "stress_report.parquet"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(report_path, index=False, compression="zstd")
    with write_transaction(args.db_path) as conn:
        conn.execute("DELETE FROM factor_model_stress_results WHERE run_id = ?", (args.run_id,))
        sql = replace_sql(
            "factor_model_stress_results",
            [
                "run_id", "bucket_type", "bucket_key", "bucket_label", "start_date", "end_date",
                "n_days", "total_return", "annual_return", "max_drawdown", "sharpe", "win_rate",
                "avg_daily_return", "volatility", "summary_json", "created_at", "updated_at",
            ],
            ["run_id", "bucket_type", "bucket_key"],
        )
        params = [
            (
                args.run_id,
                row["bucket_type"],
                row["bucket_key"],
                row["bucket_label"],
                row["start_date"],
                row["end_date"],
                row["n_days"],
                row["total_return"],
                row["annual_return"],
                row["max_drawdown"],
                row["sharpe"],
                row["win_rate"],
                row["avg_daily_return"],
                row["volatility"],
                json.dumps(row.get("summary") or {}, ensure_ascii=False),
                now,
                now,
            )
            for row in rows
        ]
        if params:
            conn.executemany(sql, params)
    return {
        "stage": args.stage,
        "effective_start": active_start,
        "effective_end": active_end,
        "row_count": len(rows),
        "worst_drawdown": sorted(rows, key=lambda row: float(row.get("max_drawdown") or 0.0))[:8],
        "market_state": [row for row in rows if row["bucket_type"] == "market_state"],
        "report_path": str(report_path),
    }


def _stress_metric_row(
    bucket_type: str,
    bucket_key: str,
    bucket_label: str,
    returns: pd.Series,
    weights: pd.DataFrame,
    metric_summary,
) -> dict[str, Any]:
    returns = returns.dropna().astype(float)
    if returns.empty:
        start = ""
        end = ""
        metrics: dict[str, Any] = {}
    else:
        start = str(returns.index.min())
        end = str(returns.index.max())
        metrics = metric_summary(returns, weights=weights.loc[returns.index.intersection(weights.index)])
    return {
        "bucket_type": bucket_type,
        "bucket_key": bucket_key,
        "bucket_label": bucket_label,
        "start_date": start,
        "end_date": end,
        "n_days": int(len(returns)),
        "total_return": _finite_or_none(metrics.get("total_return")),
        "annual_return": _finite_or_none(metrics.get("annual_return")),
        "max_drawdown": _finite_or_none(metrics.get("max_drawdown")),
        "sharpe": _finite_or_none(metrics.get("sharpe")),
        "win_rate": float((returns > 0).mean()) if not returns.empty else None,
        "avg_daily_return": float(returns.mean()) if not returns.empty else None,
        "volatility": float(returns.std(ddof=1) * np.sqrt(244.0)) if len(returns) > 1 else None,
        "summary": {"source": "ml_factor_ranker_backtest", "conditional": bucket_type == "market_state"},
    }


def _market_state_stress_rows(db_path: str | None, run_id: str, returns: pd.Series, weights: pd.DataFrame, metric_summary) -> list[dict[str, Any]]:
    try:
        with write_transaction(db_path) as conn:
            state_rows = conn.execute(
                """
                SELECT trade_date, state, risk_score
                FROM market_risk_state_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (str(returns.index.min()), str(returns.index.max())),
            ).fetchall()
    except Exception:
        return []
    if not state_rows:
        return []
    state = pd.DataFrame(state_rows, columns=["trade_date", "state", "risk_score"])
    state["trade_date"] = state["trade_date"].astype(str)
    state = state.set_index("trade_date").reindex(returns.index.astype(str))
    out: list[dict[str, Any]] = []
    labels = {
        "normal": "常态",
        "weak": "弱势",
        "crash": "急跌",
        "liquidity_squeeze": "流动性挤压",
        "post_crash_repair": "急跌后修复",
    }
    for state_key, idx in state.groupby("state", dropna=True).groups.items():
        dates = [str(date) for date in idx if str(date) in returns.index]
        if not dates:
            continue
        segment = returns.loc[dates]
        row = _stress_metric_row("market_state", str(state_key), labels.get(str(state_key), str(state_key)), segment, weights.loc[dates], metric_summary)
        risk_scores = pd.to_numeric(state.loc[dates, "risk_score"], errors="coerce")
        row["summary"] = {
            "source": "market_risk_state_daily",
            "conditional": True,
            "avg_risk_score": float(risk_scores.mean()) if risk_scores.notna().any() else None,
        }
        out.append(row)
    out.sort(key=lambda row: str(row["bucket_key"]))
    return out


def _event_periods() -> list[tuple[str, str, str, str]]:
    return [
        ("bull_2014_2015", "股灾前/牛市末段", "20140207", "20150612"),
        ("crash_2015", "2015股灾", "20150615", "20151231"),
        ("circuit_repair_2016_2017", "熔断与修复", "20160101", "20171231"),
        ("deleveraging_2018_2019", "2018-2019去杠杆/贸易冲击", "20180101", "20191231"),
        ("covid_2020", "2020疫情冲击", "20200101", "20201231"),
        ("slowdown_2022", "2022经济下行/疫情反复", "20220101", "20221231"),
        ("liquidity_2024_q1", "2024年初流动性冲击", "20240101", "20240208"),
        ("repair_2024", "2024修复后", "20240219", "20241231"),
        ("year_2025", "2025年度", "20250101", "20251231"),
    ]


def _finite_or_none(value: Any) -> float | None:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return val if math.isfinite(val) else None


def selected_model_features(panel: pd.DataFrame, db_path: str | None = None, run_id: str = "", horizon: str = "") -> list[str]:
    candidate_cols = [
        col
        for factor in FACTOR_DEFS
        for col in (f"{factor}_rank", f"{factor}_neutral")
        if col in panel.columns
    ]
    ic_order = selected_features_from_ic(db_path, run_id, horizon)
    ordered = [col for col in ic_order if col in candidate_cols]
    if not ordered:
        ordered = [
            col
            for factor in MODEL_FACTOR_ORDER
            for col in (f"{factor}_rank", f"{factor}_neutral")
            if col in candidate_cols
        ]
    ordered = [col for col in ordered if panel[col].notna().mean() >= 0.30]
    return prune_correlated_features(panel, ordered, max_features=45, corr_limit=0.92)


def selected_features_from_ic(db_path: str | None, run_id: str, horizon: str) -> list[str]:
    if not run_id:
        return []
    try:
        with write_transaction(db_path) as conn:
            rows = conn.execute(
                """
                SELECT factor, family, variant, COALESCE(rank_ic_mean, 0), COALESCE(ic_win_rate, 0), status
                FROM factor_ic_results
                WHERE run_id = ? AND horizon = ?
                ORDER BY rank_ic_mean DESC
                """,
                (run_id, horizon),
            ).fetchall()
    except Exception:
        return []
    by_family: dict[str, list[str]] = {}
    global_order: list[str] = []
    for factor, family, variant, rank_ic, win_rate, status in rows:
        if float(rank_ic or 0) < 0.012:
            continue
        if float(win_rate or 0) < 0.52:
            continue
        if str(status) == "reject":
            continue
        feature = f"{factor}_{variant}"
        global_order.append(feature)
        by_family.setdefault(str(family), []).append(feature)

    out: list[str] = []
    seen: set[str] = set()
    for family, quota in MODEL_FAMILY_MIN_QUOTAS.items():
        for feature in by_family.get(family, [])[:quota]:
            if feature not in seen:
                out.append(feature)
                seen.add(feature)
    for feature in global_order:
        if feature not in seen:
            out.append(feature)
            seen.add(feature)
    return out


def _model_features_from_db(db_path: str | None, run_id: str) -> list[str]:
    if not run_id:
        return []
    try:
        with write_transaction(db_path) as conn:
            rows = conn.execute(
                """
                SELECT feature
                FROM factor_model_features
                WHERE run_id = ?
                ORDER BY rank_no ASC, importance DESC
                """,
                (run_id,),
            ).fetchall()
    except Exception:
        return []
    return [str(row[0]) for row in rows if row and row[0]]


def _model_path_from_db(db_path: str | None, run_id: str) -> str:
    if not run_id:
        return ""
    try:
        with write_transaction(db_path) as conn:
            row = conn.execute(
                """
                SELECT COALESCE(model_path, '')
                FROM factor_model_runs
                WHERE run_id = ? AND status = 'success'
                """,
                (run_id,),
            ).fetchone()
    except Exception:
        return ""
    return str(row[0]) if row and row[0] else ""


def _parquet_columns(path: Path) -> set[str]:
    try:
        import pyarrow.parquet as pq
        return set(pq.ParquetFile(path).schema.names)
    except Exception:
        return set(pd.read_parquet(path, engine="pyarrow").columns)


def _correlation_keep_drop(
    feature_a: str,
    feature_b: str,
    selected_rank: dict[str, int],
    ordered_rank: dict[str, int],
) -> tuple[str, str]:
    a_selected = feature_a in selected_rank
    b_selected = feature_b in selected_rank
    if a_selected and not b_selected:
        return feature_a, feature_b
    if b_selected and not a_selected:
        return feature_b, feature_a
    a_rank = selected_rank.get(feature_a, ordered_rank.get(feature_a, 1_000_000))
    b_rank = selected_rank.get(feature_b, ordered_rank.get(feature_b, 1_000_000))
    if a_rank <= b_rank:
        return feature_a, feature_b
    return feature_b, feature_a


def _correlation_reason(feature_a: str, feature_b: str, keep: str, drop: str) -> str:
    base_a = feature_a.removesuffix("_rank").removesuffix("_neutral")
    base_b = feature_b.removesuffix("_rank").removesuffix("_neutral")
    if base_a == base_b:
        return "同一基础因子的 rank/neutral 版本高度重合"
    mirror_pairs = {
        frozenset(("pe", "ep")),
        frozenset(("pe_ttm", "ep")),
        frozenset(("pb", "bp")),
        frozenset(("ps", "sp")),
        frozenset(("ps_ttm", "sp")),
    }
    if frozenset((base_a, base_b)) in mirror_pairs:
        return "估值镜像因子高度重复，优先保留 IC/配额排序更靠前者"
    if feature_family_from_rank_col(feature_a) == feature_family_from_rank_col(feature_b):
        return "同家族因子高度相关，训练时保留代表因子降低冗余"
    return f"{drop} 与 {keep} 高度相关，训练时保留排序更靠前者"


def prune_correlated_features(
    panel: pd.DataFrame,
    ordered: list[str],
    *,
    max_features: int,
    corr_limit: float,
    max_rows: int = 80_000,
    stratified: bool = True,
) -> list[str]:
    selected: list[str] = []
    sample = correlation_sample(panel, ordered, max_rows=max_rows, stratified=stratified).replace([np.inf, -np.inf], np.nan)
    for col in ordered:
        if col not in sample.columns or sample[col].nunique(dropna=True) < 5:
            continue
        if not selected:
            selected.append(col)
        else:
            corr = sample[selected].corrwith(sample[col], method="spearman").abs()
            if corr.dropna().max() < corr_limit:
                selected.append(col)
        if len(selected) >= max_features:
            break
    return selected


def correlation_sample(panel: pd.DataFrame, cols: list[str], *, max_rows: int = 80_000, stratified: bool = True) -> pd.DataFrame:
    if len(panel) <= max_rows or "trade_date" not in panel.columns:
        return panel[cols]
    if not stratified:
        return panel[cols].sample(n=max_rows, random_state=20260606)
    dates = sorted(panel["trade_date"].dropna().unique().tolist())
    if not dates:
        return panel[cols].sample(n=min(len(panel), max_rows), random_state=20260606)
    per_date = max(80, max_rows // len(dates))
    sampled = (
        panel[["trade_date", *cols]]
        .groupby("trade_date", group_keys=False, sort=False)
        .apply(lambda group: group.sample(n=min(len(group), per_date), random_state=20260606))
    )
    if len(sampled) > max_rows:
        sampled = sampled.sample(n=max_rows, random_state=20260606)
    return sampled[cols]


def mark_stage(db_path: str | None, run_id: str, stage: str, status: str, *, summary: dict[str, Any], error: str = "") -> None:
    sequence = {
        "build_factor_panel": 1,
        "evaluate_factors": 2,
        "factor_correlation_report": 3,
        "train_lgbm": 4,
        "latest_inference": 5,
    }.get(stage, 0)
    now = now_text()
    with write_transaction(db_path) as conn:
        conn.execute(
            replace_sql("factor_research_stage_results", ["run_id", "stage", "sequence", "status", "summary_json", "error", "created_at", "updated_at"], ["run_id", "stage"]),
            (run_id, stage, sequence, status, json.dumps(summary, ensure_ascii=False), error, now, now),
        )


def build_monthly_factor_panel(start: str, end: str) -> pd.DataFrame:
    raw = dq.RAW_DIR
    sql = f"""
    WITH rebal AS (
      SELECT max(trade_date) AS trade_date
      FROM read_parquet('{raw / "daily" / "*.parquet"}')
      WHERE trade_date BETWEEN '{start}' AND '{end}'
      GROUP BY substr(trade_date, 1, 6)
    ), price AS (
      SELECT d.trade_date, d.ts_code,
             d.close * COALESCE(a.adj_factor, 1.0) AS adj_close,
             d.amount,
             d.pct_chg / 100.0 AS daily_ret,
             (d.open - d.pre_close) / NULLIF(d.pre_close, 0) AS gap_ret,
             avg(d.close * COALESCE(a.adj_factor, 1.0)) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
             avg(d.close * COALESCE(a.adj_factor, 1.0)) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
             max(d.close * COALESCE(a.adj_factor, 1.0)) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS high20,
             max(d.close * COALESCE(a.adj_factor, 1.0)) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS high60,
             avg(d.amount) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS amount_ma20,
             avg(dbp.turnover_rate) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS turnover_ma20,
             avg(CASE WHEN d.pct_chg > 0 THEN 1.0 ELSE 0.0 END) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS up_days20,
             max(abs((d.open - d.pre_close) / NULLIF(d.pre_close, 0))) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS gap_abs20,
             min((d.open - d.pre_close) / NULLIF(d.pre_close, 0)) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS gap_down20,
             min(d.pct_chg / 100.0) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ret_min20,
             min(d.pct_chg / 100.0) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ret_min60,
             d.close * COALESCE(a.adj_factor, 1.0) / NULLIF(lag(d.close * COALESCE(a.adj_factor, 1.0), 5) OVER w, 0) - 1 AS ret5,
             d.close * COALESCE(a.adj_factor, 1.0) / NULLIF(lag(d.close * COALESCE(a.adj_factor, 1.0), 10) OVER w, 0) - 1 AS ret10,
             d.close * COALESCE(a.adj_factor, 1.0) / NULLIF(lag(d.close * COALESCE(a.adj_factor, 1.0), 20) OVER w, 0) - 1 AS ret20,
             d.close * COALESCE(a.adj_factor, 1.0) / NULLIF(lag(d.close * COALESCE(a.adj_factor, 1.0), 60) OVER w, 0) - 1 AS ret60,
             d.close * COALESCE(a.adj_factor, 1.0) / NULLIF(lag(d.close * COALESCE(a.adj_factor, 1.0), 120) OVER w, 0) - 1 AS ret120,
             d.close * COALESCE(a.adj_factor, 1.0) / NULLIF(lag(d.close * COALESCE(a.adj_factor, 1.0), 240) OVER w, 0) - 1 AS ret240,
             stddev_pop(d.pct_chg / 100.0) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * sqrt(244.0) AS vol20,
             stddev_pop(d.pct_chg / 100.0) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) * sqrt(244.0) AS vol60,
             stddev_pop(CASE WHEN d.pct_chg < 0 THEN d.pct_chg / 100.0 ELSE NULL END) OVER (PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * sqrt(244.0) AS downvol20,
             lead(d.close * COALESCE(a.adj_factor, 1.0), 20) OVER w / NULLIF(d.close * COALESCE(a.adj_factor, 1.0), 0) - 1 AS fwd20
      FROM read_parquet('{raw / "daily" / "*.parquet"}') d
      LEFT JOIN read_parquet('{raw / "daily_basic" / "*.parquet"}') dbp
        ON d.ts_code = dbp.ts_code AND d.trade_date = dbp.trade_date
      LEFT JOIN read_parquet('{raw / "adj_factor" / "*.parquet"}') a
        ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
      WHERE d.trade_date BETWEEN '20100101' AND '{end}'
      WINDOW w AS (PARTITION BY d.ts_code ORDER BY d.trade_date)
    ), base AS (
      SELECT r.trade_date, db.ts_code,
             sb.name, sb.industry,
             sb.list_date,
             db.pe, db.pe_ttm, db.pb, db.ps, db.ps_ttm, db.dv_ratio, db.dv_ttm,
             db.total_mv, db.circ_mv, db.float_share, db.free_share, db.turnover_rate, db.turnover_rate_f, db.volume_ratio,
             p.adj_close, p.amount, p.daily_ret, p.gap_ret, p.ma20, p.ma60, p.high20, p.high60, p.amount_ma20, p.turnover_ma20,
             p.up_days20, p.gap_abs20, p.gap_down20, p.ret_min20, p.ret_min60,
             p.ret5, p.ret10, p.ret20, p.ret60, p.ret120, p.ret240, p.vol20, p.vol60, p.downvol20, p.fwd20
      FROM rebal r
      JOIN read_parquet('{raw / "daily_basic" / "*.parquet"}') db ON db.trade_date = r.trade_date
      JOIN price p ON p.trade_date = r.trade_date AND p.ts_code = db.ts_code
      LEFT JOIN read_parquet('{raw / "stock_basic" / "data.parquet"}') sb ON sb.ts_code = db.ts_code
      WHERE db.circ_mv IS NOT NULL AND db.circ_mv > 100000
        AND p.amount IS NOT NULL AND p.amount > 1000
        AND p.fwd20 IS NOT NULL
        AND COALESCE(sb.name, '') NOT LIKE '%ST%'
    ), fin AS (
      SELECT ts_code, ann_date, end_date, roe, roe_dt, roe_waa, roe_yearly, roa, roa_yearly,
             roic, grossprofit_margin, gross_margin, netprofit_margin, profit_to_gr, profit_to_op,
             debt_to_assets, debt_to_eqt, assets_to_eqt, ocf_to_debt, ocf_to_shortdebt,
             current_ratio, quick_ratio, q_ocf_to_sales, ocfps, cfps, fcff_ps, fcfe_ps,
             assets_turn, ar_turn, ca_turn, q_sales_yoy, q_op_qoq, netprofit_yoy,
             dt_netprofit_yoy, tr_yoy, or_yoy, op_yoy, ebt_yoy, ocf_yoy, assets_yoy,
             equity_yoy, bps_yoy, cfps_yoy, basic_eps_yoy AS eps_yoy
      FROM read_parquet('{raw / "fina_indicator" / "*.parquet"}')
      WHERE ann_date <= '{end}' AND ann_date >= '20090101'
    ), forecast AS (
      SELECT ts_code, ann_date,
             COALESCE(p_change_min, p_change_max) AS forecast_growth,
             COALESCE(net_profit_min, net_profit_max) AS forecast_profit,
             CASE WHEN type IN ('预增', '略增', '续盈', '扭亏') OR COALESCE(p_change_min, p_change_max, 0) > 0 THEN 1.0 ELSE 0.0 END AS forecast_positive
      FROM read_parquet('{raw / "forecast" / "*.parquet"}')
      WHERE ann_date <= '{end}' AND ann_date >= '20090101'
    ), lhb_evt AS (
      SELECT r.trade_date, tl.ts_code,
             COUNT(*) AS lhb_count_180,
             SUM(COALESCE(tl.net_amount, 0)) AS lhb_net_amount_180,
             AVG(COALESCE(tl.net_rate, 0)) AS lhb_net_rate_180,
             AVG(COALESCE(tl.amount_rate, 0)) AS lhb_amount_rate_180
      FROM rebal r
      JOIN read_parquet('{raw / "top_list" / "*.parquet"}') tl
        ON tl.trade_date <= r.trade_date
       AND strptime(tl.trade_date, '%Y%m%d') >= strptime(r.trade_date, '%Y%m%d') - INTERVAL 180 DAY
      GROUP BY r.trade_date, tl.ts_code
    ), inst_evt AS (
      SELECT r.trade_date, ti.ts_code,
             SUM(COALESCE(ti.net_buy, 0)) AS inst_net_buy_180
      FROM rebal r
      JOIN read_parquet('{raw / "top_inst" / "*.parquet"}') ti
        ON ti.trade_date <= r.trade_date
       AND strptime(ti.trade_date, '%Y%m%d') >= strptime(r.trade_date, '%Y%m%d') - INTERVAL 180 DAY
      GROUP BY r.trade_date, ti.ts_code
    ), holder_evt AS (
      SELECT r.trade_date, h.ts_code,
             SUM(CASE WHEN h.in_de = 'IN' THEN ABS(COALESCE(h.change_vol, 0)) * COALESCE(h.avg_price, 0) ELSE 0 END) AS holder_buy_value_180,
             SUM(CASE WHEN h.in_de = 'IN' THEN 1 ELSE 0 END) AS holder_buy_count_180,
             SUM(CASE WHEN h.in_de = 'DE' THEN ABS(COALESCE(h.change_vol, 0)) * COALESCE(h.avg_price, 0) ELSE 0 END) AS holder_sell_value_180
      FROM rebal r
      JOIN read_parquet('{raw / "stk_holdertrade" / "*.parquet"}') h
        ON h.ann_date <= r.trade_date
       AND strptime(h.ann_date, '%Y%m%d') >= strptime(r.trade_date, '%Y%m%d') - INTERVAL 180 DAY
      GROUP BY r.trade_date, h.ts_code
    )
    SELECT b.*, f.roe, f.roe_dt, f.roe_waa, f.roe_yearly, f.roa, f.roa_yearly,
           f.roic, f.grossprofit_margin, f.gross_margin, f.netprofit_margin, f.profit_to_gr,
           f.profit_to_op, f.debt_to_assets, f.debt_to_eqt, f.assets_to_eqt, f.ocf_to_debt,
           f.ocf_to_shortdebt, f.current_ratio, f.quick_ratio, f.q_ocf_to_sales, f.ocfps,
           f.cfps, f.fcff_ps, f.fcfe_ps, f.assets_turn, f.ar_turn, f.ca_turn, f.q_sales_yoy,
           f.q_op_qoq, f.netprofit_yoy, f.dt_netprofit_yoy, f.tr_yoy, f.or_yoy, f.op_yoy,
           f.ebt_yoy, f.ocf_yoy, f.assets_yoy, f.equity_yoy, f.bps_yoy, f.cfps_yoy, f.eps_yoy,
           fc.forecast_growth, fc.forecast_profit, fc.forecast_positive,
           le.lhb_count_180, le.lhb_net_amount_180, le.lhb_net_rate_180, le.lhb_amount_rate_180,
           ie.inst_net_buy_180,
           he.holder_buy_value_180, he.holder_buy_count_180, he.holder_sell_value_180
    FROM base b ASOF LEFT JOIN fin f
      ON b.ts_code = f.ts_code AND b.trade_date >= f.ann_date
    ASOF LEFT JOIN forecast fc
      ON b.ts_code = fc.ts_code AND b.trade_date >= fc.ann_date
    LEFT JOIN lhb_evt le
      ON b.trade_date = le.trade_date AND b.ts_code = le.ts_code
    LEFT JOIN inst_evt ie
      ON b.trade_date = ie.trade_date AND b.ts_code = ie.ts_code
    LEFT JOIN holder_evt he
      ON b.trade_date = he.trade_date AND b.ts_code = he.ts_code
    """
    panel = dq.sql(sql)
    if panel.empty:
        return panel
    for col in panel.columns:
        if col not in {"trade_date", "ts_code", "name", "industry"}:
            panel[col] = pd.to_numeric(panel[col], errors="coerce")
    dist_ma20 = panel["adj_close"] / panel["ma20"].replace(0, np.nan) - 1
    dist_ma60 = panel["adj_close"] / panel["ma60"].replace(0, np.nan) - 1
    dist_high20 = panel["adj_close"] / panel["high20"].replace(0, np.nan) - 1
    dist_high60 = panel["adj_close"] / panel["high60"].replace(0, np.nan) - 1
    amount_chg20 = panel["amount"] / panel["amount_ma20"].replace(0, np.nan) - 1
    derived_cols = {
        "ep": np.where(panel["pe_ttm"] > 0, 1.0 / panel["pe_ttm"], np.nan),
        "bp": np.where(panel["pb"] > 0, 1.0 / panel["pb"], np.nan),
        "sp": np.where(panel["ps_ttm"] > 0, 1.0 / panel["ps_ttm"], np.nan),
        "log_circ_mv": np.log(panel["circ_mv"].where(panel["circ_mv"] > 0)),
        "log_total_mv": np.log(panel["total_mv"].where(panel["total_mv"] > 0)),
        "log_amount": np.log(panel["amount"].where(panel["amount"] > 0)),
        "circ_mv_to_total_mv": panel["circ_mv"] / panel["total_mv"].replace(0, np.nan),
        "dist_ma20": dist_ma20,
        "dist_ma60": dist_ma60,
        "dist_high20": dist_high20,
        "dist_high60": dist_high60,
        "drawdown20": dist_high20,
        "drawdown60": dist_high60,
        "amihud20": panel["daily_ret"].abs() / panel["amount_ma20"].replace(0, np.nan),
        "turnover_chg20": panel["turnover_rate"] / panel["turnover_ma20"].replace(0, np.nan) - 1,
        "amount_chg20": amount_chg20,
        "amount_spike20": amount_chg20,
        "ret20_60": panel["ret20"] - panel["ret60"],
        "ret60_120": panel["ret60"] - panel["ret120"],
        "ma20_over_ma60": panel["ma20"] / panel["ma60"].replace(0, np.nan) - 1,
        "trend_strength60": panel["ret60"] / panel["vol60"].replace(0, np.nan),
        "ret20_over_vol20": panel["ret20"] / panel["vol20"].replace(0, np.nan),
        "listed_days": (
            pd.to_datetime(panel["trade_date"], errors="coerce")
            - pd.to_datetime(panel["list_date"], errors="coerce")
        ).dt.days,
    }
    panel = pd.concat([panel, pd.DataFrame(derived_cols, index=panel.index)], axis=1)
    z_cols = {}
    for source, out_col in [("ep", "ep_ttm_z_ind"), ("bp", "bp_z_ind"), ("sp", "sp_ttm_z_ind")]:
        grouped = panel.groupby(["trade_date", "industry"])[source]
        mean = grouped.transform("mean")
        std = grouped.transform("std").replace(0, np.nan)
        z_cols[out_col] = (panel[source] - mean) / std
    fwd20_market = panel.groupby("trade_date")["fwd20"].transform("mean")
    fwd20_industry = panel.groupby(["trade_date", "industry"])["fwd20"].transform("mean")
    label_cols = {
        **z_cols,
        "fwd20_market": fwd20_market,
        "fwd20_industry": fwd20_industry,
        "fwd20_excess_market": panel["fwd20"] - fwd20_market,
        "fwd20_excess_industry": panel["fwd20"] - fwd20_industry.fillna(fwd20_market),
    }
    panel = pd.concat([panel, pd.DataFrame(label_cols, index=panel.index)], axis=1)
    rank_cols = {}
    for factor, (_, high_good) in FACTOR_DEFS.items():
        if factor not in panel.columns:
            continue
        rank_cols[f"{factor}_rank"] = panel.groupby("trade_date")[factor].rank(pct=True, ascending=high_good)
    if rank_cols:
        panel = pd.concat([panel, pd.DataFrame(rank_cols, index=panel.index)], axis=1)
    panel = add_neutralized_factors(panel)
    keep = [
        "trade_date", "ts_code", "name", "industry", "fwd20", "fwd20_excess_market", "fwd20_excess_industry",
        *FACTOR_DEFS.keys(),
        *[f"{factor}_rank" for factor in FACTOR_DEFS],
        *[f"{factor}_neutral" for factor in FACTOR_DEFS],
    ]
    return panel[[col for col in keep if col in panel.columns]].sort_values(["trade_date", "ts_code"]).reset_index(drop=True)


def add_neutralized_factors(panel: pd.DataFrame) -> pd.DataFrame:
    factor_rank_cols = [f"{factor}_rank" for factor in FACTOR_DEFS if f"{factor}_rank" in panel.columns]
    if not factor_rank_cols:
        return panel

    neutral_cols = {rank_col.removesuffix("_rank") + "_neutral": panel[rank_col] for rank_col in factor_rank_cols}
    if neutral_cols:
        panel = pd.concat([panel, pd.DataFrame(neutral_cols, index=panel.index)], axis=1)

    for _, group in panel.groupby("trade_date", sort=False):
        idx = group.index
        if len(group) < 100:
            continue
        industries = group["industry"].fillna("unknown").astype(str) if "industry" in group.columns else pd.Series("unknown", index=idx)
        dummies = pd.get_dummies(industries, prefix="ind", dtype=float)

        grouped_rank_cols: dict[tuple[str, ...], list[str]] = {}
        for rank_col in factor_rank_cols:
            control_cols = tuple(col for col in ["log_circ_mv_rank", "amount_rank"] if col in panel.columns and col != rank_col)
            grouped_rank_cols.setdefault(control_cols, []).append(rank_col)

        for control_cols, rank_cols in grouped_rank_cols.items():
            controls = group[list(control_cols)].astype(float) if control_cols else pd.DataFrame(index=idx)
            x = pd.concat([pd.DataFrame({"const": 1.0}, index=idx), controls, dummies], axis=1)
            x = x.replace([np.inf, -np.inf], np.nan)
            x = x.fillna(x.median(numeric_only=True)).fillna(0.0)
            x = x.loc[:, (x.columns == "const") | (x.nunique(dropna=True) > 1)]
            if len(x.columns) <= 1:
                continue
            valid_rank_cols = [
                col
                for col in rank_cols
                if col in group.columns and group[col].replace([np.inf, -np.inf], np.nan).notna().sum() >= 100
            ]
            if not valid_rank_cols:
                continue
            y = group[valid_rank_cols].replace([np.inf, -np.inf], np.nan).astype(float)
            y_mask = y.notna()
            y_filled = y.apply(lambda col: col.fillna(col.median()), axis=0).fillna(0.5)
            try:
                x_values = x.to_numpy(dtype=float)
                beta, *_ = np.linalg.lstsq(x_values, y_filled.to_numpy(dtype=float), rcond=None)
                residual = y.to_numpy(dtype=float) - x_values @ beta
                residual[~y_mask.to_numpy()] = np.nan
                neutral_df = pd.DataFrame(residual, index=idx, columns=[col.removesuffix("_rank") + "_neutral" for col in valid_rank_cols])
                neutral_rank_df = neutral_df.rank(pct=True)
                panel.loc[idx, neutral_rank_df.columns] = neutral_rank_df
            except np.linalg.LinAlgError:
                continue
    return panel


def factor_stats(panel: pd.DataFrame, value_col: str, label: str) -> dict[str, Any]:
    ics = []
    rank_ics = []
    qret_rows = []
    obs = 0
    for _, group in panel.groupby("trade_date", sort=True):
        data = group[[value_col, label]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < 80:
            continue
        if data[value_col].nunique(dropna=True) < 5 or data[label].nunique(dropna=True) < 5:
            continue
        obs += len(data)
        ic = data[value_col].corr(data[label], method="pearson")
        rank_ic = data[value_col].corr(data[label], method="spearman")
        if math.isfinite(ic):
            ics.append(float(ic))
        if math.isfinite(rank_ic):
            rank_ics.append(float(rank_ic))
        try:
            q = pd.qcut(data[value_col].rank(method="first"), 5, labels=False) + 1
            qret = data.groupby(q)[label].mean()
            if len(qret) == 5:
                qret_rows.append(qret)
        except ValueError:
            continue
    if not rank_ics:
        return {}
    ic_series = pd.Series(ics, dtype="float64")
    rank_ic_series = pd.Series(rank_ics, dtype="float64")
    qavg = pd.concat(qret_rows, axis=1).mean(axis=1) if qret_rows else pd.Series(dtype="float64")
    q1 = float(qavg.get(1, np.nan))
    q5 = float(qavg.get(5, np.nan))
    long_short = q5 - q1
    monotonic = monotonic_score(qavg)
    rank_mean = float(rank_ic_series.mean())
    rank_std = float(rank_ic_series.std(ddof=1))
    return {
        "ic_mean": float(ic_series.mean()) if not ic_series.empty else np.nan,
        "rank_ic_mean": rank_mean,
        "ic_win_rate": float((rank_ic_series > 0).mean()),
        "icir": rank_mean / rank_std if rank_std and math.isfinite(rank_std) else 0.0,
        "n_periods": int(len(rank_ic_series)),
        "n_obs": int(obs),
        "q1_return": q1,
        "q5_return": q5,
        "long_short_return": float(long_short),
        "monotonic_score": float(monotonic),
        "quantiles": {str(int(idx)): float(val) for idx, val in qavg.items()},
    }


def monotonic_score(qavg: pd.Series) -> float:
    if qavg.empty or len(qavg) < 5:
        return 0.0
    values = qavg.sort_index().to_numpy(dtype=float)
    diffs = np.diff(values)
    return float((diffs >= 0).mean())


def factor_status(stats: dict[str, Any]) -> str:
    rank_ic = float(stats.get("rank_ic_mean") or 0)
    win_rate = float(stats.get("ic_win_rate") or 0)
    monotonic = float(stats.get("monotonic_score") or 0)
    if rank_ic > 0.02 and win_rate >= 0.55 and monotonic >= 0.5:
        return "ready"
    if rank_ic > 0 and win_rate >= 0.50:
        return "watch"
    return "reject"


def model_oos_metrics(pred_df: pd.DataFrame, label: str) -> dict[str, float]:
    rank_ics = []
    top_returns = []
    bottom_returns = []
    for _, group in pred_df.groupby("trade_date", sort=True):
        data = group[["pred_score", label]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(data) < 80:
            continue
        rank_ic = data["pred_score"].corr(data[label], method="spearman")
        if math.isfinite(rank_ic):
            rank_ics.append(float(rank_ic))
        ranks = data["pred_score"].rank(pct=True)
        top_returns.append(float(data.loc[ranks >= 0.8, label].mean()))
        bottom_returns.append(float(data.loc[ranks <= 0.2, label].mean()))
    rank_series = pd.Series(rank_ics, dtype="float64")
    top = pd.Series(top_returns, dtype="float64")
    bottom = pd.Series(bottom_returns, dtype="float64")
    return {
        "oos_rank_ic_mean": float(rank_series.mean()) if not rank_series.empty else 0.0,
        "oos_ic_win_rate": float((rank_series > 0).mean()) if not rank_series.empty else 0.0,
        "top20_mean_return": float(top.mean()) if not top.empty else 0.0,
        "bottom20_mean_return": float(bottom.mean()) if not bottom.empty else 0.0,
        "top_bottom_spread": float((top - bottom).mean()) if not top.empty and not bottom.empty else 0.0,
    }


def feature_family_from_rank_col(feature: str) -> str:
    factor = feature
    if factor.endswith("_rank"):
        factor = factor[:-5]
    elif factor.endswith("_neutral"):
        factor = factor[:-8]
    return FACTOR_DEFS.get(factor, ("", True))[0]


def data_coverage(start: str, end: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        raw = dq.RAW_DIR
        daily = dq.sql(
            f"""
            WITH rebal AS (
                SELECT max(trade_date) AS trade_date
                FROM read_parquet('{raw / "daily" / "*.parquet"}')
                WHERE trade_date BETWEEN '{start}' AND '{end}'
                GROUP BY substr(trade_date, 1, 6)
            )
            SELECT COUNT(*) AS sample_rows, COUNT(DISTINCT trade_date) AS sample_dates
            FROM read_parquet('{raw / "daily_basic" / "*.parquet"}')
            WHERE trade_date IN (SELECT trade_date FROM rebal)
            """
        )
        if not daily.empty:
            out["sample_rows"] = int(daily.iloc[0]["sample_rows"])
            out["sample_dates"] = int(daily.iloc[0]["sample_dates"])
        for name, date_col in [("daily", "trade_date"), ("daily_basic", "trade_date"), ("fina_indicator", "ann_date")]:
            df = dq.sql(
                f"""
                SELECT min({date_col}) AS min_date, max({date_col}) AS max_date, COUNT(*) AS rows
                FROM read_parquet('{raw / name / "*.parquet"}')
                WHERE {date_col} BETWEEN '{start}' AND '{end}'
                """
            )
            if not df.empty:
                out[name] = {
                    "min_date": str(df.iloc[0]["min_date"]),
                    "max_date": str(df.iloc[0]["max_date"]),
                    "rows": int(df.iloc[0]["rows"]),
                }
    except Exception as exc:
        out["coverage_error"] = str(exc)
    return out


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def data_root() -> Path:
    import os
    return Path(os.getenv("DATA_ROOT", str(ROOT.parent / "data_store"))).expanduser().resolve()


def panel_path_for(run_id: str) -> Path:
    return data_root() / "factor_research" / run_id / "monthly_factor_panel.parquet"


def import_lightgbm() -> tuple[Any | None, str]:
    try:
        import lightgbm as lgb
        return lgb, ""
    except Exception as exc:
        return None, str(exc)


if __name__ == "__main__":
    main()
