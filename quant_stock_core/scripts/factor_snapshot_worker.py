#!/usr/bin/env python3
"""Build reusable factor snapshots from atomic market data.

The production snapshot is a shared stock factor base. Strategies such as
通用策略 and 热门做T consume their own feature sets from this wide base.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.factor_store import (
    FactorDefinition,
    FactorRegistry,
    FactorSnapshotSpec,
    FeatureSetDefinition,
    FeatureSetRegistry,
    build_drift_report,
    build_factor_manifest,
    build_quality_gate_report,
    drift_summary,
    factor_correlation_report,
    factor_preprocess_report,
    factor_selection_report,
    factor_snapshot_dir,
    load_latest_factor_snapshot_meta,
    preprocess_config,
    preprocess_factors,
    quality_gate_summary,
    single_factor_report,
    update_factor_snapshot_metadata,
    write_factor_artifacts,
    write_factor_manifest,
    write_factor_snapshot,
)
from common.infra import status as run_status
from scripts import profit_arena_worker as profit_arena


TASK_NAME = "factor_snapshot"


def progress(event: str, **payload: Any) -> None:
    print(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **payload}, ensure_ascii=False), flush=True)


def status_progress(idx: int, total: int, stage: str, name: str, message: str | None = None) -> None:
    try:
        run_status.progress(TASK_NAME, int(idx), int(total), stage, name, message)
    except Exception:
        pass


def preprocess_progress(event: str, payload: dict[str, object]) -> None:
    progress(event, **payload)
    factor_loop_base = {
        "preprocess_winsorize_progress": (38, 39, "preprocess_winsorize", "执行截面缩尾"),
        "preprocess_fill_missing_progress": (39, 40, "preprocess_fill", "填充因子缺失值"),
        "preprocess_rank_normalize_progress": (42, 43, "preprocess_rank", "执行截面 rank 标准化"),
        "preprocess_standardize_progress": (43, 44, "preprocess_standardize", "执行截面标准化"),
    }
    if event in factor_loop_base:
        start_idx, end_idx, stage, name = factor_loop_base[event]
        factor_count = int(payload.get("factor_count") or 1)
        factor_index = int(payload.get("factor_index") or 0)
        stage_progress = min(max(factor_index / max(factor_count, 1), 0.0), 1.0)
        idx = start_idx + int(stage_progress * max(end_idx - start_idx, 1))
        message = f"factor={payload.get('factor')} {factor_index}/{factor_count}"
        status_progress(idx, 100, stage, name, message)
        return
    if event == "preprocess_neutralize_progress":
        total_dates = int(payload.get("total_dates") or 1)
        date_index = int(payload.get("date_index") or 0)
        stage_progress = min(max(date_index / max(total_dates, 1), 0.0), 1.0)
        idx = 37 + int(stage_progress * 5)
        message = f"trade_date={payload.get('trade_date')} {date_index}/{total_dates} factors={payload.get('factor_count')}"
        status_progress(idx, 100, "preprocess_neutralize", "执行因子中性化", message)
        return
    stage_map = {
        "preprocess_start": (36, "preprocess", "开始因子预处理"),
        "preprocess_missing_flags": (37, "preprocess_missing", "生成缺失标记"),
        "preprocess_winsorize": (38, "preprocess_winsorize", "执行截面缩尾"),
        "preprocess_fill_missing": (39, "preprocess_fill", "填充因子缺失值"),
        "preprocess_neutralize_start": (40, "preprocess_neutralize", "开始因子中性化"),
        "preprocess_rank_normalize": (42, "preprocess_rank", "执行截面 rank 标准化"),
        "preprocess_standardize": (43, "preprocess_standardize", "执行截面标准化"),
        "preprocess_done": (44, "preprocess_done", "因子预处理完成"),
    }
    if event in stage_map:
        idx, stage, name = stage_map[event]
        status_progress(idx, 100, stage, name, json.dumps(payload, ensure_ascii=False, sort_keys=True))


def profit_arena_factor_registry() -> FactorRegistry:
    registry = FactorRegistry()
    for name in profit_arena.FEATURES:
        if name.startswith("market_"):
            category = "market"
        elif name.startswith("industry_") or name.startswith("rs_industry"):
            category = "industry"
        elif name.startswith("small_"):
            category = "small_cap_ecology"
        elif name in {"pb", "pe_ttm", "circ_mv_log", "total_mv_log", "size_pct_rank"}:
            category = "valuation_size"
        elif "volatility" in name or "drawdown" in name:
            category = "risk"
        elif "amount" in name or "turnover" in name or "volume" in name:
            category = "liquidity"
        else:
            category = "price_action"
        registry.register(FactorDefinition(name=name, category=category, description=f"profit arena factor: {name}"))
    return registry


def profit_arena_feature_sets() -> FeatureSetRegistry:
    registry = FeatureSetRegistry()
    for feature_set_id in ("legacy53", "core", "ecology", "all", "v6all", "pre_v7", "champion_v100", "champion_v116", "base_v1", "stock_factor_base_v1", "stock_h20_general_final_v1", "hot_t_daily_v1", "hot_t_v1"):
        registry.register(
            FeatureSetDefinition(
                feature_set_id=feature_set_id,
                strategy_id="stock_factor_base" if feature_set_id in {"base_v1", "stock_factor_base_v1"} else ("hot_t_model" if feature_set_id in {"hot_t_daily_v1", "hot_t_v1"} else "profit_arena_model"),
                factor_names=tuple(profit_arena.feature_columns_for_set(feature_set_id)),
                description=f"通用股票因子基座 {feature_set_id} 特征集",
                preprocess="institutional",
            )
        )
    return registry


FACTOR_TESTCASE_COLUMNS = (
    "ret5",
    "ret20",
    "open_to_close",
    "gap_open",
    "amount_chg5",
    "ma20_bias",
    "volatility20",
    "turnover_chg5",
    "breakout_high20",
    "close_position_day",
    "high_to_close_pullback",
    "low_to_close_rebound",
    "turnover_chg20",
    "failed_breakout20",
)


def _stable_sample_key(trade_date: Any, ts_code: Any) -> str:
    raw = f"{trade_date}|{ts_code}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return default
    if not math.isfinite(result):
        return default
    return result


def _both_missing(left: Any, right: Any) -> bool:
    return bool(pd.isna(left) and pd.isna(right))


def _label_check_value(value: Any) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        return _finite_float(text)
    return _finite_float(value)


def _direct_rolling_mean(values: pd.Series, window: int, min_periods: int) -> float:
    tail = pd.to_numeric(values.tail(window), errors="coerce").dropna()
    if len(tail) < min_periods:
        return 0.0
    return _finite_float(tail.mean())


def _direct_pct_from_lag(values: pd.Series, lag: int) -> float:
    series = pd.to_numeric(values, errors="coerce").dropna()
    if len(series) <= lag:
        return 0.0
    base = _finite_float(series.iloc[-lag - 1])
    current = _finite_float(series.iloc[-1])
    if abs(base) < 1e-12:
        return 0.0
    return current / base - 1.0


def _recompute_factor_value(raw_by_code: dict[str, pd.DataFrame], ts_code: str, trade_date: str, factor: str) -> float:
    rows = raw_by_code.get(ts_code)
    if rows is None or rows.empty:
        return 0.0
    history = rows[rows["trade_date"].astype(str) <= str(trade_date)].sort_values("trade_date")
    if history.empty:
        return 0.0

    close = pd.to_numeric(history["close"], errors="coerce")
    open_ = pd.to_numeric(history["open"], errors="coerce")
    high = pd.to_numeric(history["high"], errors="coerce")
    low = pd.to_numeric(history["low"], errors="coerce")
    amount = pd.to_numeric(history["amount"], errors="coerce")
    turnover = pd.to_numeric(history["turnover_rate"], errors="coerce")

    if factor == "ret5":
        return _direct_pct_from_lag(close, 5)
    if factor == "ret20":
        return _direct_pct_from_lag(close, 20)
    if factor == "open_to_close":
        base = _finite_float(open_.iloc[-1])
        if abs(base) < 1e-12:
            return 0.0
        return _finite_float(close.iloc[-1]) / base - 1.0
    if factor == "gap_open":
        if len(close.dropna()) < 2:
            return 0.0
        previous_close = _finite_float(close.dropna().iloc[-2])
        if abs(previous_close) < 1e-12:
            return 0.0
        return _finite_float(open_.iloc[-1]) / previous_close - 1.0
    if factor == "amount_chg5":
        baseline = _direct_rolling_mean(amount, 5, 2)
        if abs(baseline) < 1e-12:
            return 0.0
        return _finite_float(amount.iloc[-1]) / baseline - 1.0
    if factor == "ma20_bias":
        baseline = _direct_rolling_mean(close, 20, 6)
        if abs(baseline) < 1e-12:
            return 0.0
        return _finite_float(close.iloc[-1]) / baseline - 1.0
    if factor == "volatility20":
        pct = pd.to_numeric(history["pct_chg"], errors="coerce").tail(20).dropna()
        if len(pct) < 6:
            return 0.0
        return _finite_float(pct.std())
    if factor == "turnover_chg5":
        baseline = _direct_rolling_mean(turnover, 5, 2)
        if abs(baseline) < 1e-12:
            return 0.0
        return _finite_float(turnover.iloc[-1]) / baseline - 1.0
    if factor == "turnover_chg20":
        baseline = _direct_rolling_mean(turnover, 20, 5)
        if abs(baseline) < 1e-12:
            return 0.0
        return _finite_float(turnover.iloc[-1]) / baseline - 1.0
    if factor == "breakout_high20":
        previous_high = high.shift(1).tail(20).dropna()
        if len(previous_high) < 8:
            return 0.0
        return 1.0 if _finite_float(close.iloc[-1]) > _finite_float(previous_high.max()) else 0.0
    if factor == "failed_breakout20":
        previous_high = high.shift(1).tail(20).dropna()
        if len(previous_high) < 8:
            return 0.0
        high_bar = _finite_float(high.iloc[-1])
        close_bar = _finite_float(close.iloc[-1])
        threshold = _finite_float(previous_high.max())
        return 1.0 if high_bar > threshold and close_bar <= threshold else 0.0
    if factor == "close_position_day":
        span = _finite_float(high.iloc[-1]) - _finite_float(low.iloc[-1])
        if abs(span) < 1e-12:
            return 0.0
        return (_finite_float(close.iloc[-1]) - _finite_float(low.iloc[-1])) / span
    if factor == "high_to_close_pullback":
        base = _finite_float(close.iloc[-1])
        if abs(base) < 1e-12:
            return 0.0
        return _finite_float(high.iloc[-1]) / base - 1.0
    if factor == "low_to_close_rebound":
        base = _finite_float(low.iloc[-1])
        if abs(base) < 1e-12:
            return 0.0
        return _finite_float(close.iloc[-1]) / base - 1.0
    return 0.0


def _recompute_label_values(
    raw_by_code: dict[str, pd.DataFrame],
    ts_code: str,
    trade_date: str,
    horizon: int,
    buy_slippage: float,
    sell_slippage: float,
    commission: float,
    stamp_tax: float,
) -> dict[str, Any]:
    rows = raw_by_code.get(str(ts_code))
    if rows is None or rows.empty:
        return {"exit_date": "", "future_return": math.nan, "net_return": math.nan, "future_max_return": math.nan, "future_drawdown": math.nan}
    history = rows.sort_values("trade_date").reset_index(drop=True).copy()
    history["trade_date"] = history["trade_date"].astype(str)
    matches = history.index[history["trade_date"] == str(trade_date)].tolist()
    if not matches:
        return {"exit_date": "", "future_return": math.nan, "net_return": math.nan, "future_max_return": math.nan, "future_drawdown": math.nan}
    idx = int(matches[0])
    next_idx = idx + 1
    exit_idx = idx + int(horizon) + 1
    if next_idx >= len(history) or exit_idx >= len(history):
        return {"exit_date": "", "future_return": math.nan, "net_return": math.nan, "future_max_return": math.nan, "future_drawdown": math.nan}
    next_open = _finite_float(history.loc[next_idx, "open"], math.nan)
    exit_close = _finite_float(history.loc[exit_idx, "close"], math.nan)
    future_window = history.loc[next_idx:exit_idx]
    if not math.isfinite(next_open) or abs(next_open) < 1e-12 or not math.isfinite(exit_close):
        gross = math.nan
        net = math.nan
        future_max_return = math.nan
        future_drawdown = math.nan
    else:
        gross = exit_close / next_open - 1.0
        net = (1.0 + gross) * (1.0 - sell_slippage - commission - stamp_tax) / (1.0 + buy_slippage + commission) - 1.0
        future_high = _finite_float(pd.to_numeric(future_window["high"], errors="coerce").max(), math.nan)
        future_low = _finite_float(pd.to_numeric(future_window["low"], errors="coerce").min(), math.nan)
        future_max_return = future_high / next_open - 1.0 if math.isfinite(future_high) else math.nan
        future_drawdown = future_low / next_open - 1.0 if math.isfinite(future_low) else math.nan
        price_limit_pct = profit_arena.price_limit_pct_series(history)
        next_pct = _finite_float(history.loc[next_idx, "pct_chg"], math.nan)
        current_limit = _finite_float(price_limit_pct.iloc[idx], math.nan)
        can_buy_next_open = math.isfinite(next_pct) and math.isfinite(current_limit) and next_pct < current_limit - 0.2
        if not can_buy_next_open:
            net = math.nan
    return {
        "exit_date": str(history.loc[exit_idx, "trade_date"]),
        "future_return": gross,
        "net_return": net,
        "future_max_return": future_max_return,
        "future_drawdown": future_drawdown,
    }


def _append_label_testcase_rows(
    rows: list[dict[str, Any]],
    raw_by_code: dict[str, pd.DataFrame],
    frame: pd.DataFrame,
    horizons: list[int],
    samples: int,
    tolerance: float,
    buy_slippage: float,
    sell_slippage: float,
    commission: float,
    stamp_tax: float,
) -> dict[str, Any]:
    label_checks = 0
    label_failed = 0
    latest_unmatured_checks = 0
    for horizon in horizons:
        columns = {
            "future_return": f"future_return_{horizon}d",
            "net_return": f"net_return_{horizon}d",
            "future_max_return": f"future_max_return_{horizon}d",
            "future_drawdown": f"future_drawdown_{horizon}d",
            "exit_date": f"exit_date_{horizon}d",
        }
        if not all(column in frame.columns for column in columns.values()):
            continue
        mature = frame[frame[columns["future_return"]].notna()][["trade_date", "ts_code", *columns.values()]].copy()
        if not mature.empty:
            mature["_sample_key"] = mature.apply(lambda row: _stable_sample_key(f"label|{horizon}|{row['trade_date']}", row["ts_code"]), axis=1)
            mature = mature.sort_values("_sample_key").head(max(1, int(samples)))
        latest_dates = sorted(str(value) for value in frame["trade_date"].dropna().unique())[-int(horizon + 1):]
        latest = frame[frame["trade_date"].astype(str).isin(latest_dates)][["trade_date", "ts_code", columns["net_return"]]].copy()
        if not latest.empty:
            latest["_sample_key"] = latest.apply(lambda row: _stable_sample_key(f"latest_label|{horizon}|{row['trade_date']}", row["ts_code"]), axis=1)
            latest = latest.sort_values("_sample_key").head(max(1, min(int(samples), 20)))
        for _, sample in mature.iterrows():
            recomputed = _recompute_label_values(
                raw_by_code,
                str(sample["ts_code"]),
                str(sample["trade_date"]),
                int(horizon),
                buy_slippage,
                sell_slippage,
                commission,
                stamp_tax,
            )
            for key, column in columns.items():
                actual = sample[column]
                expected = recomputed[key]
                if key == "exit_date":
                    actual_value = _label_check_value(actual)
                    expected_value = _label_check_value(expected)
                    abs_diff = abs(actual_value - expected_value)
                elif _both_missing(actual, expected):
                    actual_value = math.nan
                    expected_value = math.nan
                    abs_diff = 0.0
                else:
                    actual_value = _finite_float(actual, math.nan)
                    expected_value = _finite_float(expected, math.nan)
                    abs_diff = abs(actual_value - expected_value) if math.isfinite(actual_value) and math.isfinite(expected_value) else math.inf
                status = "pass" if abs_diff <= tolerance else "fail"
                label_checks += 1
                label_failed += 1 if status != "pass" else 0
                rows.append({
                    "trade_date": str(sample["trade_date"]),
                    "ts_code": str(sample["ts_code"]),
                    "factor": f"label:{column}",
                    "snapshot_value": actual_value,
                    "recomputed_value": expected_value,
                    "abs_diff": abs_diff,
                    "status": status,
                })
        for _, sample in latest.iterrows():
            actual = sample[columns["net_return"]]
            status = "pass" if pd.isna(actual) else "fail"
            latest_unmatured_checks += 1
            label_checks += 1
            label_failed += 1 if status != "pass" else 0
            rows.append({
                "trade_date": str(sample["trade_date"]),
                "ts_code": str(sample["ts_code"]),
                "factor": f"label_latest_unmatured:{columns['net_return']}",
                "snapshot_value": _finite_float(actual, math.nan) if not pd.isna(actual) else math.nan,
                "recomputed_value": math.nan,
                "abs_diff": 0.0 if status == "pass" else math.inf,
                "status": status,
            })
    return {
        "label_check_count": label_checks,
        "label_failed_count": label_failed,
        "latest_unmatured_label_checks": latest_unmatured_checks,
    }


def build_factor_testcase_report(
    raw: pd.DataFrame,
    frame: pd.DataFrame,
    factor_columns: list[str],
    samples: int,
    tolerance: float,
    horizons: list[int] | None = None,
    buy_slippage: float = 0.0015,
    sell_slippage: float = 0.0015,
    commission: float = 0.00025,
    stamp_tax: float = 0.0005,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    testcase_columns = [name for name in FACTOR_TESTCASE_COLUMNS if name in factor_columns and name in frame.columns]
    if not testcase_columns:
        report = pd.DataFrame()
        return report, {
            "status": "fail",
            "message": "没有可校验的固化因子 testcase",
            "sample_count": 0,
            "check_count": 0,
            "failed_count": 1,
            "max_abs_diff": None,
            "tolerance": tolerance,
        }

    latest_dates = sorted(str(value) for value in frame["trade_date"].dropna().unique())[-8:]
    candidates = frame[frame["trade_date"].astype(str).isin(latest_dates)][["trade_date", "ts_code"] + testcase_columns].copy()
    candidates["_sample_key"] = candidates.apply(lambda row: _stable_sample_key(row["trade_date"], row["ts_code"]), axis=1)
    candidates = candidates.sort_values("_sample_key").head(max(1, int(samples)))
    raw_by_code = {str(code): rows.copy() for code, rows in raw.groupby("ts_code", sort=False)}

    rows: list[dict[str, Any]] = []
    for _, sample in candidates.iterrows():
        trade_date = str(sample["trade_date"])
        ts_code = str(sample["ts_code"])
        for factor in testcase_columns:
            expected = _recompute_factor_value(raw_by_code, ts_code, trade_date, factor)
            actual = _finite_float(sample[factor])
            abs_diff = abs(actual - expected)
            rows.append(
                {
                    "trade_date": trade_date,
                    "ts_code": ts_code,
                    "factor": factor,
                    "snapshot_value": actual,
                    "recomputed_value": expected,
                    "abs_diff": abs_diff,
                    "status": "pass" if abs_diff <= tolerance else "fail",
                }
            )

    label_summary = _append_label_testcase_rows(
        rows,
        raw_by_code,
        frame,
        [int(value) for value in (horizons or []) if int(value) > 0],
        samples,
        tolerance,
        buy_slippage,
        sell_slippage,
        commission,
        stamp_tax,
    )
    report = pd.DataFrame(rows)
    failed_count = int((report["status"] != "pass").sum()) if not report.empty else 1
    summary = {
        "status": "pass" if failed_count == 0 else "fail",
        "sample_count": int(candidates.shape[0]),
        "check_count": int(report.shape[0]),
        "failed_count": failed_count,
        "max_abs_diff": None if report.empty else _finite_float(report["abs_diff"].max()),
        "tolerance": tolerance,
        "factors": testcase_columns,
        "sample_dates": latest_dates,
        **label_summary,
    }
    if failed_count:
        summary["message"] = "因子基座 testcase 复算不一致"
    return report, summary


def write_factor_testcase_artifacts(data_path: str | Path, spec: FactorSnapshotSpec, report: pd.DataFrame) -> dict[str, str]:
    root = factor_snapshot_dir(data_path, spec)
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    parquet_path = root / "factor_testcase_report.parquet"
    json_path = root / "factor_testcase_report.json"
    report.to_parquet(parquet_path, index=False)
    report.to_json(json_path, orient="records", force_ascii=False, indent=2)
    paths["factor_testcase_report"] = str(parquet_path)
    paths["factor_testcase_report_json"] = str(json_path)
    return paths


def build_profit_arena_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    horizons = profit_arena.parse_int_list(args.horizons)
    execution_stop_losses = profit_arena.parse_float_list(args.execution_stop_loss)
    execution_take_profits = profit_arena.parse_float_list(args.execution_take_profit)
    spec = FactorSnapshotSpec(
        factor_store_id=args.factor_store_id,
        start=args.start,
        end=args.end,
        horizons=tuple(sorted(int(value) for value in horizons)),
        feature_set=args.feature_set,
        universe="main_board_non_st_listed120_amount20000_price250",
        version=profit_arena.PANEL_CACHE_VERSION,
        params={
            "buy_slippage": args.buy_slippage,
            "sell_slippage": args.sell_slippage,
            "commission": args.commission,
            "stamp_tax": args.stamp_tax,
            "stop_loss": args.stop_loss,
            "take_profit": args.take_profit,
            "execution_stop_losses": execution_stop_losses,
            "execution_take_profits": execution_take_profits,
            "warmup_days": args.warmup_days,
            "preprocess": args.preprocess,
        },
    )
    previous_meta = load_latest_factor_snapshot_meta(args.data_path, args.factor_store_id)
    status_progress(8, 100, "raw", "读取原子行情数据", f"{args.start}-{args.end}")
    progress("factor_snapshot_raw_load_start", factor_store_id=args.factor_store_id, start=args.start, end=args.end)
    raw = profit_arena.read_market_panel(Path(args.data_path), args.start, args.end, warmup_days=args.warmup_days)
    if raw.empty:
        raise RuntimeError("原子日线数据为空，无法生成因子快照")
    progress("factor_snapshot_raw_loaded", rows=len(raw), columns=len(raw.columns))
    status_progress(20, 100, "feature_calc", "计算通用策略因子面板", f"raw_rows={len(raw)} horizons={horizons}")
    frame = profit_arena.add_features(
        raw,
        args.start,
        args.end,
        horizons,
        args.buy_slippage,
        args.sell_slippage,
        args.commission,
        args.stamp_tax,
        args.stop_loss,
        args.take_profit,
        execution_stop_losses,
        execution_take_profits,
    )
    factor_registry = profit_arena_factor_registry()
    feature_set = profit_arena_feature_sets().get(args.feature_set)
    factor_columns = list(feature_set.factor_names)
    status_progress(36, 100, "preprocess", "生成因子预处理报告", f"feature_set={args.feature_set} factors={len(factor_columns)}")
    preprocess_before = factor_preprocess_report(frame, factor_columns)
    processed_frame = preprocess_factors(frame, factor_columns, args.preprocess, progress_callback=preprocess_progress)
    preprocess_after = factor_preprocess_report(processed_frame, factor_columns)
    status_progress(44, 100, "factor_testcase", "执行因子 testcase", f"samples={args.factor_testcase_samples}")
    if args.skip_factor_testcase:
        testcase_report = pd.DataFrame()
        testcase_summary = {
            "status": "skipped",
            "sample_count": 0,
            "check_count": 0,
            "failed_count": 0,
            "max_abs_diff": None,
            "tolerance": args.factor_testcase_max_abs_diff,
            "message": "已按参数跳过因子 testcase",
        }
    else:
        testcase_report, testcase_summary = build_factor_testcase_report(
            raw,
            frame,
            factor_columns,
            samples=args.factor_testcase_samples,
            tolerance=args.factor_testcase_max_abs_diff,
            horizons=horizons,
            buy_slippage=args.buy_slippage,
            sell_slippage=args.sell_slippage,
            commission=args.commission,
            stamp_tax=args.stamp_tax,
        )
        if testcase_summary.get("status") != "pass":
            raise RuntimeError(f"因子基座 testcase 未通过: {testcase_summary}")
    target = f"net_return_{int(horizons[0])}d"
    status_progress(50, 100, "single_factor", "执行单因子检验", f"target={target} skip={args.skip_factor_validation}")
    report = single_factor_report(processed_frame, factor_columns, target) if not args.skip_factor_validation else None
    status_progress(62, 100, "correlation", "执行因子相关性和筛选", f"factors={len(factor_columns)}")
    correlation_report = factor_correlation_report(processed_frame, factor_columns) if not args.skip_factor_validation else None
    selection_report = factor_selection_report(report, correlation_report) if report is not None else None
    previous_preprocess_path = ""
    previous_artifacts = previous_meta.get("artifact_paths") if isinstance(previous_meta, dict) else None
    if isinstance(previous_artifacts, dict):
        previous_preprocess_path = str(previous_artifacts.get("preprocess_after_report_path") or "")
    status_progress(72, 100, "drift", "计算因子漂移报告", previous_preprocess_path or "no_previous_snapshot")
    drift_report = build_drift_report(preprocess_after, previous_preprocess_path) if not args.skip_factor_validation else None
    status_progress(80, 100, "quality_gate", "执行因子质量门禁", f"min_rows={args.quality_min_rows}")
    quality_gate_report = build_quality_gate_report(
        frame=processed_frame,
        factor_columns=factor_columns,
        preprocess_after_frame=preprocess_after,
        single_factor_frame=report,
        correlation_frame=correlation_report,
        selection_frame=selection_report,
        min_rows=args.quality_min_rows,
        min_keep_ratio=args.quality_min_keep_ratio,
        min_median_coverage=args.quality_min_median_coverage,
        max_missing_rate=args.quality_max_missing_rate,
    ) if not args.skip_factor_validation else None
    gate_summary = quality_gate_summary(quality_gate_report)
    current_drift_summary = drift_summary(drift_report)
    if args.enforce_quality_gate and gate_summary.get("status") == "fail":
        raise RuntimeError(f"因子质量门禁未通过: {gate_summary}")
    status_progress(86, 100, "persist_snapshot", "写入因子快照主表", f"quality={gate_summary.get('status')}")
    keep_count = int((selection_report["decision"] == "keep").sum()) if selection_report is not None and not selection_report.empty else 0
    review_count = int((selection_report["decision"] == "review").sum()) if selection_report is not None and not selection_report.empty else 0
    config = preprocess_config(args.preprocess)
    path = write_factor_snapshot(
        args.data_path,
        spec,
        processed_frame,
        extra={
            "feature_count": len(factor_columns),
            "all_factor_count": len(profit_arena.FEATURES),
            "preprocess": args.preprocess,
            "factor_preprocess": args.preprocess,
            "execution_stop_losses": execution_stop_losses,
            "execution_take_profits": execution_take_profits,
            "production_contract": {
                "strategy": "stock_factor_base",
                "consumer_strategies": ["profit_arena_model", "hot_t_model"],
                "required_start": "20100101",
                "required_horizon": 20,
                "required_feature_set": "stock_factor_base_v1",
                "required_version": profit_arena.PANEL_CACHE_VERSION,
                "required_preprocess": "institutional",
                "required_execution_take_profits": [0.20, 0.25, 0.30],
            },
            "preprocess_config": config.to_json(),
            "single_factor_target": target if not args.skip_factor_validation else "",
            "factor_keep_count": keep_count,
            "factor_review_count": review_count,
            "quality_gate": gate_summary,
            "drift_summary": current_drift_summary,
            "factor_testcase": testcase_summary,
        },
    )
    status_progress(92, 100, "persist_artifacts", "写入因子治理产物", f"keep={keep_count} review={review_count}")
    artifact_paths = write_factor_artifacts(
        args.data_path,
        spec,
        factor_definitions=[factor_registry.get(name) for name in factor_registry.names()],
        feature_set=feature_set,
        preprocess_before_frame=preprocess_before,
        preprocess_after_frame=preprocess_after,
        single_factor_frame=report,
        correlation_frame=correlation_report,
        selection_frame=selection_report,
        quality_gate_frame=quality_gate_report,
        drift_frame=drift_report,
    )
    if not args.skip_factor_testcase:
        artifact_paths.update(write_factor_testcase_artifacts(args.data_path, spec, testcase_report))
    manifest = build_factor_manifest(
        spec=spec,
        frame=processed_frame,
        factor_columns=factor_columns,
        artifact_paths=artifact_paths,
        preprocess=args.preprocess,
        quality_gate=gate_summary,
        drift_summary=current_drift_summary,
    )
    manifest_path = write_factor_manifest(args.data_path, spec, manifest)
    status_progress(96, 100, "manifest", "写入因子 manifest 和元数据", str(manifest_path))
    update_factor_snapshot_metadata(
        args.data_path,
        spec,
        {
            "artifact_paths": artifact_paths,
            "manifest_path": manifest_path,
            "quality_gate": gate_summary,
            "drift_summary": current_drift_summary,
            "factor_testcase": testcase_summary,
            "factor_preprocess": args.preprocess,
            "execution_stop_losses": execution_stop_losses,
            "execution_take_profits": execution_take_profits,
        },
    )
    progress("factor_snapshot_written", path=str(path), rows=len(processed_frame), columns=len(processed_frame.columns), manifest_path=manifest_path, quality_gate=gate_summary, drift_summary=current_drift_summary, factor_testcase=testcase_summary, **artifact_paths)
    done_message = (
        f"rows={len(processed_frame)} factors={len(factor_columns)} "
        f"testcase={testcase_summary.get('status')} quality={gate_summary.get('status')} drift={current_drift_summary.get('status')} "
        f"keep={keep_count} review={review_count} manifest={manifest_path}"
    )
    status_progress(100, 100, "done", "因子快照完成", done_message)
    return {
        "path": path,
        "manifest_path": manifest_path,
        "rows": len(processed_frame),
        "factors": len(factor_columns),
        "testcase_status": testcase_summary.get("status"),
        "quality_status": gate_summary.get("status"),
        "drift_status": current_drift_summary.get("status"),
        "keep_count": keep_count,
        "review_count": review_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--factor-store-id", default="stock_factor_base_v1")
    parser.add_argument("--start", default="20100101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--horizons", default="20")
    parser.add_argument("--feature-set", choices=["legacy53", "core", "ecology", "all", "v6all", "pre_v7", "champion_v100", "champion_v116", "base_v1", "stock_factor_base_v1", "stock_h20_general_final_v1", "hot_t_daily_v1", "hot_t_v1"], default="stock_factor_base_v1")
    parser.add_argument("--preprocess", choices=["none", "winsorize", "zscore", "winsorize_zscore", "rank_normalize", "size_neutral", "institutional"], default="institutional")
    parser.add_argument("--skip-factor-validation", action="store_true")
    parser.add_argument("--skip-factor-testcase", action="store_true")
    parser.add_argument("--factor-testcase-samples", type=int, default=80)
    parser.add_argument("--factor-testcase-max-abs-diff", type=float, default=1e-8)
    parser.add_argument("--enforce-quality-gate", action="store_true")
    parser.add_argument("--quality-min-rows", type=int, default=10000)
    parser.add_argument("--quality-min-keep-ratio", type=float, default=0.20)
    parser.add_argument("--quality-min-median-coverage", type=float, default=0.70)
    parser.add_argument("--quality-max-missing-rate", type=float, default=0.05)
    parser.add_argument("--buy-slippage", type=float, default=0.0015)
    parser.add_argument("--sell-slippage", type=float, default=0.0015)
    parser.add_argument("--commission", type=float, default=0.00025)
    parser.add_argument("--stamp-tax", type=float, default=0.0005)
    parser.add_argument("--stop-loss", type=float, default=0.0)
    parser.add_argument("--take-profit", type=float, default=0.0)
    parser.add_argument("--execution-stop-loss", default="0")
    parser.add_argument("--execution-take-profit", default="0.20,0.25,0.30")
    parser.add_argument("--warmup-days", type=int, default=260)
    args = parser.parse_args()
    run_status.begin(TASK_NAME)
    try:
        status_progress(2, 100, "prepare", "准备生成因子快照", f"factor_store_id={args.factor_store_id}")
        result = build_profit_arena_snapshot(args)
        run_status.done(
            TASK_NAME,
            (
                f"因子快照已生成: {result['path']} "
                f"rows={result['rows']} factors={result['factors']} "
                f"testcase={result['testcase_status']} quality={result['quality_status']} drift={result['drift_status']} "
                f"manifest={result['manifest_path']}"
            ),
        )
        return 0
    except Exception as exc:
        run_status.error(
            TASK_NAME,
            (
                f"factor_store_id={args.factor_store_id} start={args.start} end={args.end} "
                f"feature_set={args.feature_set} preprocess={args.preprocess} error={exc}"
            ),
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
