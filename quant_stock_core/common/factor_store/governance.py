from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .storage import FactorSnapshotSpec, factor_snapshot_digest


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if np.isfinite(out) else default
    except Exception:
        return default


def _json_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _frame_schema_hash(frame: pd.DataFrame) -> str:
    payload = [{"name": str(column), "dtype": str(dtype)} for column, dtype in zip(frame.columns, frame.dtypes)]
    return _json_hash(payload)


def _date_distribution_hash(frame: pd.DataFrame) -> str:
    if frame.empty or "trade_date" not in frame.columns:
        return ""
    counts = frame.groupby("trade_date", sort=True).size().astype(int).to_dict()
    return _json_hash(counts)


def build_factor_manifest(
    *,
    spec: FactorSnapshotSpec,
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    artifact_paths: dict[str, str],
    preprocess: str,
    quality_gate: dict[str, Any] | None = None,
    drift_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_factors = [column for column in factor_columns if column in frame.columns]
    return {
        "manifest_version": "factor_store_manifest_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "factor_store_id": spec.factor_store_id,
        "snapshot_digest": factor_snapshot_digest(spec),
        "version": spec.version,
        "feature_set": spec.feature_set,
        "universe": spec.universe,
        "start": spec.start,
        "end": spec.end,
        "horizons": list(spec.horizons),
        "params_hash": _json_hash(spec.params),
        "preprocess": preprocess,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "factor_count": int(len(existing_factors)),
        "missing_factor_count": int(len([column for column in factor_columns if column not in frame.columns])),
        "trade_date_min": str(frame["trade_date"].min()) if "trade_date" in frame.columns and not frame.empty else "",
        "trade_date_max": str(frame["trade_date"].max()) if "trade_date" in frame.columns and not frame.empty else "",
        "schema_hash": _frame_schema_hash(frame),
        "factor_list_hash": _json_hash(list(factor_columns)),
        "date_distribution_hash": _date_distribution_hash(frame),
        "artifact_paths": artifact_paths,
        "quality_gate": quality_gate or {},
        "drift_summary": drift_summary or {},
    }


def build_quality_gate_report(
    *,
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    preprocess_after_frame: pd.DataFrame | None,
    single_factor_frame: pd.DataFrame | None,
    correlation_frame: pd.DataFrame | None,
    selection_frame: pd.DataFrame | None,
    min_rows: int = 10000,
    min_keep_ratio: float = 0.20,
    min_median_coverage: float = 0.70,
    max_missing_rate: float = 0.05,
    max_high_corr_pairs_per_factor: float = 2.0,
) -> pd.DataFrame:
    factor_count = max(len(factor_columns), 1)
    keep_count = 0
    review_count = 0
    if selection_frame is not None and not selection_frame.empty and "decision" in selection_frame.columns:
        keep_count = int((selection_frame["decision"] == "keep").sum())
        review_count = int((selection_frame["decision"] == "review").sum())
    keep_ratio = keep_count / factor_count
    median_coverage = 0.0
    if single_factor_frame is not None and not single_factor_frame.empty and "coverage" in single_factor_frame.columns:
        median_coverage = _safe_float(single_factor_frame["coverage"].median())
    max_after_missing = 0.0
    if preprocess_after_frame is not None and not preprocess_after_frame.empty and "missing_rate" in preprocess_after_frame.columns:
        max_after_missing = _safe_float(preprocess_after_frame["missing_rate"].max())
    high_corr_pairs = int(len(correlation_frame)) if correlation_frame is not None else 0
    high_corr_per_factor = high_corr_pairs / factor_count
    checks = [
        {
            "check": "row_count",
            "status": "pass" if len(frame) >= min_rows else "fail",
            "value": int(len(frame)),
            "threshold": min_rows,
            "message": "样本行数达到训练前最低要求",
        },
        {
            "check": "factor_keep_ratio",
            "status": "pass" if keep_ratio >= min_keep_ratio else "warn",
            "value": keep_ratio,
            "threshold": min_keep_ratio,
            "message": "通过单因子和冗余检查的因子比例",
        },
        {
            "check": "median_coverage",
            "status": "pass" if median_coverage >= min_median_coverage else "warn",
            "value": median_coverage,
            "threshold": min_median_coverage,
            "message": "单因子中位覆盖率",
        },
        {
            "check": "max_missing_rate_after_preprocess",
            "status": "pass" if max_after_missing <= max_missing_rate else "fail",
            "value": max_after_missing,
            "threshold": max_missing_rate,
            "message": "预处理后最大缺失率",
        },
        {
            "check": "high_corr_pairs_per_factor",
            "status": "pass" if high_corr_per_factor <= max_high_corr_pairs_per_factor else "warn",
            "value": high_corr_per_factor,
            "threshold": max_high_corr_pairs_per_factor,
            "message": "高相关因子对密度",
        },
    ]
    severity = "pass"
    if any(row["status"] == "fail" for row in checks):
        severity = "fail"
    elif any(row["status"] == "warn" for row in checks):
        severity = "warn"
    summary = {
        "check": "summary",
        "status": severity,
        "value": keep_count,
        "threshold": factor_count,
        "message": f"keep={keep_count}, review={review_count}, high_corr_pairs={high_corr_pairs}",
    }
    return pd.DataFrame([summary, *checks])


def quality_gate_summary(gate_frame: pd.DataFrame | None) -> dict[str, Any]:
    if gate_frame is None or gate_frame.empty:
        return {"status": "missing", "failed_checks": [], "warn_checks": []}
    rows = gate_frame.to_dict("records")
    status = str(rows[0].get("status", "missing")) if rows else "missing"
    return {
        "status": status,
        "failed_checks": [str(row.get("check")) for row in rows if row.get("status") == "fail"],
        "warn_checks": [str(row.get("check")) for row in rows if row.get("status") == "warn"],
    }


def build_drift_report(
    current_preprocess_frame: pd.DataFrame | None,
    previous_preprocess_path: str | Path | None,
    *,
    missing_rate_warn_delta: float = 0.05,
    std_warn_ratio: float = 3.0,
) -> pd.DataFrame:
    columns = ["factor", "status", "missing_rate_delta", "std_ratio", "current_missing_rate", "previous_missing_rate", "current_std", "previous_std"]
    if current_preprocess_frame is None or current_preprocess_frame.empty or not previous_preprocess_path:
        return pd.DataFrame(columns=columns)
    path = Path(previous_preprocess_path)
    if not path.exists():
        return pd.DataFrame(columns=columns)
    previous = pd.read_parquet(path)
    if previous.empty or "factor" not in previous.columns:
        return pd.DataFrame(columns=columns)
    prev_by_factor = {str(row.factor): row for row in previous.itertuples(index=False)}
    rows: list[dict[str, Any]] = []
    for row in current_preprocess_frame.itertuples(index=False):
        factor = str(getattr(row, "factor"))
        prev = prev_by_factor.get(factor)
        if prev is None:
            rows.append({"factor": factor, "status": "new_factor", "missing_rate_delta": 0.0, "std_ratio": 0.0, "current_missing_rate": _safe_float(getattr(row, "missing_rate", 0.0)), "previous_missing_rate": 0.0, "current_std": _safe_float(getattr(row, "std", 0.0)), "previous_std": 0.0})
            continue
        current_missing = _safe_float(getattr(row, "missing_rate", 0.0))
        previous_missing = _safe_float(getattr(prev, "missing_rate", 0.0))
        current_std = abs(_safe_float(getattr(row, "std", 0.0)))
        previous_std = abs(_safe_float(getattr(prev, "std", 0.0)))
        std_ratio = current_std / previous_std if previous_std > 1e-12 else 0.0
        status = "pass"
        if abs(current_missing - previous_missing) >= missing_rate_warn_delta:
            status = "warn"
        if std_ratio >= std_warn_ratio or (std_ratio > 0 and std_ratio <= 1.0 / std_warn_ratio):
            status = "warn"
        rows.append(
            {
                "factor": factor,
                "status": status,
                "missing_rate_delta": current_missing - previous_missing,
                "std_ratio": std_ratio,
                "current_missing_rate": current_missing,
                "previous_missing_rate": previous_missing,
                "current_std": current_std,
                "previous_std": previous_std,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def drift_summary(drift_frame: pd.DataFrame | None) -> dict[str, Any]:
    if drift_frame is None or drift_frame.empty:
        return {"status": "missing", "warn_count": 0, "new_factor_count": 0}
    warn_count = int((drift_frame["status"] == "warn").sum()) if "status" in drift_frame.columns else 0
    new_count = int((drift_frame["status"] == "new_factor").sum()) if "status" in drift_frame.columns else 0
    return {"status": "warn" if warn_count else "pass", "warn_count": warn_count, "new_factor_count": new_count}


def build_feature_consistency_report(
    *,
    frame: pd.DataFrame,
    expected_features: Sequence[str],
    manifest: dict[str, Any] | None = None,
    latest_date: str = "",
    max_latest_missing_rate: float = 0.02,
    max_mean_shift_z: float = 6.0,
) -> pd.DataFrame:
    expected = [str(item) for item in expected_features]
    missing = [feature for feature in expected if feature not in frame.columns]
    non_numeric: list[str] = []
    for feature in expected:
        if feature not in frame.columns:
            continue
        values = pd.to_numeric(frame[feature], errors="coerce")
        if values.notna().sum() == 0:
            non_numeric.append(feature)
    manifest_factor_hash = ""
    manifest_schema_hash = ""
    manifest_feature_set = ""
    manifest_factors: list[str] = []
    if manifest:
        manifest_factor_hash = str(manifest.get("factor_list_hash") or "")
        manifest_schema_hash = str(manifest.get("schema_hash") or "")
        manifest_feature_set = str(manifest.get("feature_set") or "")
        artifact_paths = manifest.get("artifact_paths") if isinstance(manifest.get("artifact_paths"), dict) else {}
        feature_set_path = str(artifact_paths.get("feature_set_path") or "")
        if feature_set_path and Path(feature_set_path).exists():
            try:
                feature_set_payload = json.loads(Path(feature_set_path).read_text(encoding="utf-8"))
                raw_factors = feature_set_payload.get("factor_names") or []
                if isinstance(raw_factors, list):
                    manifest_factors = [str(item) for item in raw_factors]
            except Exception:
                manifest_factors = []
    current_factor_hash = _json_hash(expected)
    current_schema_hash = _frame_schema_hash(frame)
    rows: list[dict[str, Any]] = [
        {
            "check": "expected_features_present",
            "status": "pass" if not missing else "fail",
            "value": len(missing),
            "threshold": 0,
            "message": ",".join(missing[:20]),
        },
        {
            "check": "expected_features_numeric",
            "status": "pass" if not non_numeric else "fail",
            "value": len(non_numeric),
            "threshold": 0,
            "message": ",".join(non_numeric[:20]),
        },
    ]
    if manifest_factor_hash:
        subset_missing = sorted(set(expected).difference(set(manifest_factors))) if manifest_factors else []
        factor_match = manifest_factor_hash == current_factor_hash
        subset_match = bool(manifest_factors) and not subset_missing
        rows.append(
            {
                "check": "factor_list_hash_match",
                "status": "pass" if factor_match or subset_match else "fail",
                "value": current_factor_hash,
                "threshold": manifest_factor_hash,
                "message": (
                    f"feature_set={manifest_feature_set}; expected_subset_of_manifest=True; "
                    f"manifest_factor_count={len(manifest_factors)}; expected_factor_count={len(expected)}"
                    if subset_match and not factor_match
                    else f"feature_set={manifest_feature_set}; missing_from_manifest={','.join(subset_missing[:20])}"
                ),
            }
        )
    if manifest_schema_hash:
        rows.append(
            {
                "check": "schema_hash_observed",
                "status": "pass" if manifest_schema_hash == current_schema_hash else "warn",
                "value": current_schema_hash,
                "threshold": manifest_schema_hash,
                "message": "schema hash differs when runtime frame has extra columns or dtypes shifted",
            }
        )
    latest = pd.DataFrame()
    if latest_date and "trade_date" in frame.columns:
        latest = frame[frame["trade_date"].astype(str).eq(str(latest_date))].copy()
    elif "trade_date" in frame.columns and not frame.empty:
        max_date = str(frame["trade_date"].astype(str).max())
        latest = frame[frame["trade_date"].astype(str).eq(max_date)].copy()
    if not latest.empty and expected:
        latest_missing_rates = []
        mean_shift_flags = []
        history = frame.drop(latest.index, errors="ignore")
        for feature in expected:
            if feature not in frame.columns:
                continue
            latest_values = pd.to_numeric(latest[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
            latest_missing_rates.append(float(latest_values.isna().mean()))
            if history.empty or feature not in history.columns:
                continue
            hist_values = pd.to_numeric(history[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
            if hist_values.empty:
                continue
            std = float(hist_values.std())
            if not np.isfinite(std) or std <= 1e-12:
                continue
            shift = abs(float(latest_values.dropna().mean()) - float(hist_values.mean())) / std if latest_values.dropna().size else 0.0
            if np.isfinite(shift) and shift >= max_mean_shift_z:
                mean_shift_flags.append(feature)
        max_missing = max(latest_missing_rates) if latest_missing_rates else 0.0
        rows.append(
            {
                "check": "latest_feature_missing_rate",
                "status": "pass" if max_missing <= max_latest_missing_rate else "fail",
                "value": max_missing,
                "threshold": max_latest_missing_rate,
                "message": "max missing rate across expected features on latest cross-section",
            }
        )
        rows.append(
            {
                "check": "latest_distribution_shift",
                "status": "pass" if not mean_shift_flags else "fail",
                "value": len(mean_shift_flags),
                "threshold": 0,
                "message": ",".join(mean_shift_flags[:20]),
            }
        )
    severity = "pass"
    if any(row["status"] == "fail" for row in rows):
        severity = "fail"
    elif any(row["status"] == "warn" for row in rows):
        severity = "warn"
    return pd.DataFrame([{"check": "summary", "status": severity, "value": len(expected), "threshold": len(expected), "message": f"expected_features={len(expected)}"}] + rows)


def feature_consistency_summary(report: pd.DataFrame | None) -> dict[str, Any]:
    if report is None or report.empty:
        return {"status": "missing", "failed_checks": [], "warn_checks": []}
    rows = report.to_dict("records")
    status = str(rows[0].get("status", "missing")) if rows else "missing"
    return {
        "status": status,
        "failed_checks": [str(row.get("check")) for row in rows if row.get("status") == "fail"],
        "warn_checks": [str(row.get("check")) for row in rows if row.get("status") == "warn"],
    }


def build_capacity_report(
    frame: pd.DataFrame,
    *,
    top_n: int,
    capital_base: float,
    capital_fraction: float = 1.0,
    max_participation_rate: float = 0.05,
    target_participation_rate: float = 0.02,
    amount_unit: float = 1000.0,
    impact_bps_coefficient: float = 50.0,
    score_column: str = "model_score",
    weight_column: str | None = None,
    capital_scale_column: str | None = None,
    amount_column: str = "amount",
    price_column: str = "close",
) -> pd.DataFrame:
    columns = [
        "trade_date", "ts_code", "name", "rank", "weight", "order_notional", "daily_amount",
        "participation_rate", "max_capacity_notional", "estimated_impact_bps", "status", "message",
    ]
    if frame.empty or top_n <= 0 or capital_base <= 0:
        return pd.DataFrame(columns=columns)
    required = {"trade_date", "ts_code", score_column}
    if not required.issubset(frame.columns) or amount_column not in frame.columns:
        missing = sorted((required | {amount_column}) - set(frame.columns))
        return pd.DataFrame([{
            "trade_date": "",
            "ts_code": "",
            "name": "",
            "rank": 0,
            "weight": 0.0,
            "order_notional": 0.0,
            "daily_amount": 0.0,
            "participation_rate": 0.0,
            "max_capacity_notional": 0.0,
            "estimated_impact_bps": 0.0,
            "status": "fail",
            "message": "missing_columns:" + ",".join(missing),
        }], columns=columns)
    rows: list[dict[str, Any]] = []
    work = frame.copy()
    work[score_column] = pd.to_numeric(work[score_column], errors="coerce").fillna(0.0)
    effective_fraction = min(max(float(capital_fraction), 0.0), 1.0)
    for trade_date, group in work.groupby("trade_date", sort=True):
        selected = group.sort_values(score_column, ascending=False).head(int(top_n)).copy()
        if selected.empty:
            continue
        if weight_column and weight_column in selected.columns:
            weights = pd.to_numeric(selected[weight_column], errors="coerce").clip(lower=0.0).fillna(0.0)
            if float(weights.sum()) <= 0:
                weights = pd.Series(1.0 / len(selected), index=selected.index)
        else:
            scores = pd.to_numeric(selected[score_column], errors="coerce").clip(lower=0.0).fillna(0.0)
            if float(scores.sum()) > 0:
                weights = scores / float(scores.sum())
            else:
                weights = pd.Series(1.0 / len(selected), index=selected.index)
        if capital_scale_column and capital_scale_column in selected.columns:
            scales = pd.to_numeric(selected[capital_scale_column], errors="coerce").clip(lower=0.0, upper=1.0).fillna(1.0)
        else:
            scales = pd.Series(1.0, index=selected.index)
        for rank, (idx, row) in enumerate(selected.iterrows(), 1):
            weight = float(weights.loc[idx])
            scale = float(scales.loc[idx])
            order_notional = float(capital_base) * effective_fraction * weight * scale
            daily_amount = _safe_float(row.get(amount_column)) * float(amount_unit)
            participation = order_notional / daily_amount if daily_amount > 0 else float("inf")
            max_capacity = daily_amount * float(max_participation_rate) if daily_amount > 0 else 0.0
            impact = float(impact_bps_coefficient) * np.sqrt(max(participation, 0.0)) if np.isfinite(participation) else float("inf")
            status = "pass"
            message = ""
            if not np.isfinite(participation) or daily_amount <= 0:
                status = "fail"
                message = "missing_daily_amount"
            elif participation > float(max_participation_rate):
                status = "fail"
                message = "exceeds_max_participation"
            elif participation > float(target_participation_rate):
                status = "warn"
                message = "above_target_participation"
            rows.append({
                "trade_date": str(trade_date),
                "ts_code": str(row.get("ts_code", "")),
                "name": str(row.get("name", "")),
                "rank": int(rank),
                "weight": weight,
                "order_notional": order_notional,
                "daily_amount": daily_amount,
                "participation_rate": participation if np.isfinite(participation) else 0.0,
                "max_capacity_notional": max_capacity,
                "estimated_impact_bps": impact if np.isfinite(impact) else 0.0,
                "status": status,
                "message": message,
            })
    return pd.DataFrame(rows, columns=columns)


def capacity_summary(report: pd.DataFrame | None) -> dict[str, Any]:
    if report is None or report.empty:
        return {"status": "missing", "fail_count": 0, "warn_count": 0}
    fail_count = int((report["status"] == "fail").sum()) if "status" in report.columns else 0
    warn_count = int((report["status"] == "warn").sum()) if "status" in report.columns else 0
    status = "fail" if fail_count else "warn" if warn_count else "pass"
    return {
        "status": status,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "max_participation_rate": _safe_float(report["participation_rate"].max()) if "participation_rate" in report.columns else 0.0,
        "median_participation_rate": _safe_float(report["participation_rate"].median()) if "participation_rate" in report.columns else 0.0,
        "max_estimated_impact_bps": _safe_float(report["estimated_impact_bps"].max()) if "estimated_impact_bps" in report.columns else 0.0,
        "total_order_notional": _safe_float(report["order_notional"].sum()) if "order_notional" in report.columns else 0.0,
        "min_capacity_notional": _safe_float(report["max_capacity_notional"].min()) if "max_capacity_notional" in report.columns else 0.0,
    }


def _portfolio_selected_frame(
    frame: pd.DataFrame,
    *,
    top_n: int,
    score_column: str = "model_score",
    capital_fraction: float = 1.0,
    weight_column: str | None = None,
    capital_scale_column: str | None = None,
) -> pd.DataFrame:
    if frame.empty or top_n <= 0 or "trade_date" not in frame.columns or "ts_code" not in frame.columns or score_column not in frame.columns:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    work = frame.copy()
    work[score_column] = pd.to_numeric(work[score_column], errors="coerce").fillna(0.0)
    effective_fraction = min(max(float(capital_fraction), 0.0), 1.0)
    for trade_date, group in work.groupby("trade_date", sort=True):
        selected = group.sort_values(score_column, ascending=False).head(int(top_n)).copy()
        if selected.empty:
            continue
        if weight_column and weight_column in selected.columns:
            weights = pd.to_numeric(selected[weight_column], errors="coerce").clip(lower=0.0).fillna(0.0)
            if float(weights.sum()) <= 0:
                weights = pd.Series(1.0 / len(selected), index=selected.index)
        else:
            scores = pd.to_numeric(selected[score_column], errors="coerce").clip(lower=0.0).fillna(0.0)
            if float(scores.sum()) > 0:
                weights = scores / float(scores.sum())
            else:
                weights = pd.Series(1.0 / len(selected), index=selected.index)
        if capital_scale_column and capital_scale_column in selected.columns:
            scales = pd.to_numeric(selected[capital_scale_column], errors="coerce").clip(lower=0.0, upper=1.0).fillna(1.0)
        else:
            scales = pd.Series(1.0, index=selected.index)
        selected["portfolio_weight"] = (weights.astype(float) * scales.astype(float) * effective_fraction).astype(float)
        selected["portfolio_rank"] = np.arange(1, len(selected) + 1, dtype=int)
        selected["trade_date"] = str(trade_date)
        rows.append(selected)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def build_portfolio_risk_report(
    frame: pd.DataFrame,
    *,
    top_n: int,
    capital_fraction: float = 1.0,
    max_single_weight: float = 0.10,
    max_industry_weight: float = 0.30,
    max_size_bucket_weight: float = 0.60,
    max_avg_crash_prob: float = 0.15,
    score_column: str = "model_score",
    weight_column: str | None = None,
    capital_scale_column: str | None = None,
) -> pd.DataFrame:
    columns = ["trade_date", "check", "status", "value", "threshold", "message"]
    selected = _portfolio_selected_frame(
        frame,
        top_n=top_n,
        score_column=score_column,
        capital_fraction=capital_fraction,
        weight_column=weight_column,
        capital_scale_column=capital_scale_column,
    )
    if selected.empty:
        return pd.DataFrame([{
            "trade_date": "",
            "check": "selection",
            "status": "fail",
            "value": 0.0,
            "threshold": float(top_n),
            "message": "no_selected_rows",
        }], columns=columns)
    rows: list[dict[str, Any]] = []
    for trade_date, group in selected.groupby("trade_date", sort=True):
        max_single = _safe_float(group["portfolio_weight"].max())
        rows.append({
            "trade_date": str(trade_date),
            "check": "max_single_weight",
            "status": "pass" if max_single <= float(max_single_weight) else "fail",
            "value": max_single,
            "threshold": float(max_single_weight),
            "message": "单票最大权重",
        })
        if "industry" in group.columns:
            industry_weight = group.groupby(group["industry"].fillna("").astype(str))["portfolio_weight"].sum()
            max_industry = _safe_float(industry_weight.max())
            top_industry = str(industry_weight.idxmax()) if not industry_weight.empty else ""
            rows.append({
                "trade_date": str(trade_date),
                "check": "max_industry_weight",
                "status": "pass" if max_industry <= float(max_industry_weight) else "fail",
                "value": max_industry,
                "threshold": float(max_industry_weight),
                "message": top_industry,
            })
        else:
            rows.append({
                "trade_date": str(trade_date),
                "check": "max_industry_weight",
                "status": "warn",
                "value": 0.0,
                "threshold": float(max_industry_weight),
                "message": "missing_industry",
            })
        if "size_bucket" in group.columns:
            size_weight = group.groupby(group["size_bucket"].fillna("").astype(str))["portfolio_weight"].sum()
            max_size = _safe_float(size_weight.max())
            top_size = str(size_weight.idxmax()) if not size_weight.empty else ""
            rows.append({
                "trade_date": str(trade_date),
                "check": "max_size_bucket_weight",
                "status": "pass" if max_size <= float(max_size_bucket_weight) else "warn",
                "value": max_size,
                "threshold": float(max_size_bucket_weight),
                "message": top_size,
            })
        else:
            rows.append({
                "trade_date": str(trade_date),
                "check": "max_size_bucket_weight",
                "status": "warn",
                "value": 0.0,
                "threshold": float(max_size_bucket_weight),
                "message": "missing_size_bucket",
            })
        if "crash_prob" in group.columns:
            crash = pd.to_numeric(group["crash_prob"], errors="coerce").fillna(0.0)
            gross_exposure = _safe_float(group["portfolio_weight"].sum())
            avg_crash = _safe_float((crash * group["portfolio_weight"]).sum() / gross_exposure) if gross_exposure > 0 else _safe_float(crash.mean())
            rows.append({
                "trade_date": str(trade_date),
                "check": "avg_crash_prob",
                "status": "pass" if avg_crash <= float(max_avg_crash_prob) else "fail",
                "value": avg_crash,
                "threshold": float(max_avg_crash_prob),
                "message": f"组合投入资金加权闪崩概率 exposure={gross_exposure:.4f}",
            })
        if "capacity_status" in group.columns:
            fail_count = int((group["capacity_status"].astype(str) == "fail").sum())
            warn_count = int((group["capacity_status"].astype(str) == "warn").sum())
            rows.append({
                "trade_date": str(trade_date),
                "check": "capacity_fail_count",
                "status": "pass" if fail_count == 0 else "fail",
                "value": float(fail_count),
                "threshold": 0.0,
                "message": f"warn={warn_count}",
            })
    severity = "pass"
    if any(row["status"] == "fail" for row in rows):
        severity = "fail"
    elif any(row["status"] == "warn" for row in rows):
        severity = "warn"
    return pd.DataFrame([{
        "trade_date": "",
        "check": "summary",
        "status": severity,
        "value": float(len(selected)),
        "threshold": float(top_n),
        "message": f"selected_rows={len(selected)}",
    }, *rows], columns=columns)


def portfolio_risk_summary(report: pd.DataFrame | None) -> dict[str, Any]:
    if report is None or report.empty:
        return {"status": "missing", "fail_count": 0, "warn_count": 0}
    rows = report.to_dict("records")
    status = str(rows[0].get("status", "missing")) if rows else "missing"
    data = report[report["check"] != "summary"].copy() if "check" in report.columns else report.copy()
    fail_count = int((data["status"] == "fail").sum()) if "status" in data.columns else 0
    warn_count = int((data["status"] == "warn").sum()) if "status" in data.columns else 0

    def max_value(check: str) -> float:
        if data.empty or "check" not in data.columns:
            return 0.0
        values = data[data["check"] == check]["value"] if "value" in data.columns else pd.Series(dtype="float64")
        return _safe_float(values.max()) if not values.empty else 0.0

    worst = 0.0
    if not data.empty and {"status", "value"}.issubset(data.columns):
        risky = data[data["status"].isin(["fail", "warn"])]["value"]
        worst = _safe_float(risky.max()) if not risky.empty else 0.0

    return {
        "status": status,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "worst_value": worst,
        "max_single_weight": max_value("max_single_weight"),
        "max_industry_weight": max_value("max_industry_weight"),
        "max_size_bucket_weight": max_value("max_size_bucket_weight"),
        "max_avg_crash_prob": max_value("avg_crash_prob"),
        "capacity_fail_count": int(max_value("capacity_fail_count")),
    }
