from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if np.isfinite(out) else default
    except Exception:
        return default


def _rank_ic_by_date(frame: pd.DataFrame, factor: str, target: str) -> pd.Series:
    rows: list[tuple[str, float]] = []
    for trade_date, group in frame[["trade_date", factor, target]].dropna().groupby("trade_date", sort=True):
        if len(group) < 20 or group[factor].nunique(dropna=True) < 2 or group[target].nunique(dropna=True) < 2:
            continue
        rows.append((str(trade_date), _safe_float(group[factor].rank().corr(group[target].rank()))))
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series([value for _, value in rows], index=[date for date, _ in rows], dtype="float64")


def _quantile_spread(frame: pd.DataFrame, factor: str, target: str, quantiles: int = 5) -> float:
    spreads: list[float] = []
    for _trade_date, group in frame[["trade_date", factor, target]].dropna().groupby("trade_date", sort=True):
        if len(group) < quantiles * 10 or group[factor].nunique(dropna=True) < quantiles:
            continue
        try:
            bucket = pd.qcut(group[factor].rank(method="first"), quantiles, labels=False)
            grouped = group.assign(_bucket=bucket).groupby("_bucket")[target].mean()
            if len(grouped) >= quantiles:
                spreads.append(_safe_float(grouped.iloc[-1] - grouped.iloc[0]))
        except Exception:
            continue
    return _safe_float(np.mean(spreads)) if spreads else 0.0


def _quantile_stats(frame: pd.DataFrame, factor: str, target: str, quantiles: int = 5) -> dict[str, float]:
    bucket_returns: list[list[float]] = [[] for _ in range(quantiles)]
    for _trade_date, group in frame[["trade_date", factor, target]].dropna().groupby("trade_date", sort=True):
        if len(group) < quantiles * 10 or group[factor].nunique(dropna=True) < quantiles:
            continue
        try:
            bucket = pd.qcut(group[factor].rank(method="first"), quantiles, labels=False)
            grouped = group.assign(_bucket=bucket).groupby("_bucket")[target].mean()
            if len(grouped) >= quantiles:
                for index in range(quantiles):
                    bucket_returns[index].append(_safe_float(grouped.iloc[index]))
        except Exception:
            continue
    means = [_safe_float(np.mean(values)) if values else 0.0 for values in bucket_returns]
    diffs = np.diff(means) if len(means) > 1 else np.array([])
    monotonicity = _safe_float((diffs >= 0).mean()) if len(diffs) else 0.0
    spread_values = [top - bottom for top, bottom in zip(bucket_returns[-1], bucket_returns[0])]
    spread_mean = _safe_float(np.mean(spread_values)) if spread_values else 0.0
    spread_std = _safe_float(np.std(spread_values, ddof=1)) if len(spread_values) > 1 else 0.0
    spread_t = _safe_float(spread_mean / (spread_std / np.sqrt(len(spread_values)))) if spread_std > 0 else 0.0
    return {
        "quantile_bottom_mean": means[0] if means else 0.0,
        "quantile_top_mean": means[-1] if means else 0.0,
        "quantile_top_bottom": spread_mean,
        "quantile_spread_t": spread_t,
        "quantile_monotonicity": monotonicity,
    }


def _yearly_ic_summary(ic: pd.Series) -> tuple[str, float, float]:
    if ic.empty:
        return "[]", 0.0, 0.0
    work = pd.DataFrame({"trade_date": ic.index.astype(str), "rank_ic": ic.to_numpy(dtype=float)})
    work["year"] = work["trade_date"].str.slice(0, 4)
    rows: list[dict[str, object]] = []
    means: list[float] = []
    for year, group in work.groupby("year", sort=True):
        mean = _safe_float(group["rank_ic"].mean())
        means.append(mean)
        rows.append(
            {
                "year": str(year),
                "rank_ic_mean": mean,
                "rank_ic_ir": _safe_float(mean / group["rank_ic"].std()) if _safe_float(group["rank_ic"].std()) > 0 else 0.0,
                "win_rate": _safe_float((group["rank_ic"] > 0).mean()),
                "days": int(len(group)),
            }
        )
    positive_year_rate = _safe_float(np.mean([value > 0 for value in means])) if means else 0.0
    stability = _safe_float(np.mean(means) / np.std(means, ddof=1)) if len(means) > 1 and np.std(means, ddof=1) > 0 else 0.0
    return pd.DataFrame(rows).to_json(orient="records", force_ascii=False), positive_year_rate, stability


def single_factor_report(frame: pd.DataFrame, factor_columns: Sequence[str], target: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if frame.empty or target not in frame.columns:
        return pd.DataFrame(rows)
    for factor in factor_columns:
        if factor not in frame.columns:
            rows.append({"factor": factor, "status": "missing"})
            continue
        usable = frame[["trade_date", factor, target]].replace([np.inf, -np.inf], np.nan).dropna()
        coverage = len(usable) / max(len(frame), 1)
        ic = _rank_ic_by_date(usable, factor, target)
        quantile = _quantile_stats(usable, factor, target)
        yearly_json, positive_year_rate, yearly_stability = _yearly_ic_summary(ic)
        rank_ic_mean = _safe_float(ic.mean()) if len(ic) else 0.0
        rank_ic_std = _safe_float(ic.std()) if len(ic) else 0.0
        rank_ic_ir = _safe_float(rank_ic_mean / rank_ic_std) if rank_ic_std > 0 else 0.0
        quality_score = (
            abs(rank_ic_mean) * 100.0
            + max(rank_ic_ir, 0.0) * 2.0
            + max(positive_year_rate - 0.5, 0.0) * 4.0
            + max(quantile["quantile_monotonicity"] - 0.5, 0.0) * 2.0
            + min(max(coverage, 0.0), 1.0)
        )
        rows.append(
            {
                "factor": factor,
                "status": "ok" if len(ic) > 0 else "insufficient",
                "n_rows": int(len(usable)),
                "coverage": _safe_float(coverage),
                "rank_ic_mean": rank_ic_mean,
                "rank_ic_abs_mean": abs(rank_ic_mean),
                "rank_ic_std": rank_ic_std,
                "rank_ic_ir": rank_ic_ir,
                "rank_ic_win_rate": _safe_float((ic > 0).mean()) if len(ic) else 0.0,
                "rank_ic_days": int(len(ic)),
                "positive_year_rate": positive_year_rate,
                "yearly_ic_stability": yearly_stability,
                "yearly_ic_json": yearly_json,
                "quality_score": _safe_float(quality_score),
                **quantile,
            }
        )
    return pd.DataFrame(rows).sort_values(["status", "quality_score"], ascending=[True, False]).reset_index(drop=True)


def factor_correlation_report(frame: pd.DataFrame, factor_columns: Sequence[str], *, max_rows: int = 300000, threshold: float = 0.90) -> pd.DataFrame:
    existing = [column for column in factor_columns if column in frame.columns]
    if frame.empty or len(existing) < 2:
        return pd.DataFrame(columns=["factor_a", "factor_b", "correlation", "abs_correlation"])
    work = frame[existing].replace([np.inf, -np.inf], np.nan)
    if len(work) > max_rows:
        work = work.sample(max_rows, random_state=20260618)
    corr = work.corr(method="spearman", min_periods=500)
    rows: list[dict[str, object]] = []
    for i, factor_a in enumerate(existing):
        for factor_b in existing[i + 1 :]:
            value = _safe_float(corr.loc[factor_a, factor_b], np.nan)
            if not np.isfinite(value):
                continue
            if abs(value) >= threshold:
                rows.append({"factor_a": factor_a, "factor_b": factor_b, "correlation": value, "abs_correlation": abs(value)})
    return pd.DataFrame(rows).sort_values("abs_correlation", ascending=False).reset_index(drop=True) if rows else pd.DataFrame(columns=["factor_a", "factor_b", "correlation", "abs_correlation"])


def factor_selection_report(
    single_factor_frame: pd.DataFrame,
    correlation_frame: pd.DataFrame | None = None,
    *,
    min_coverage: float = 0.70,
    min_ic_abs: float = 0.005,
    max_corr: float = 0.95,
) -> pd.DataFrame:
    if single_factor_frame is None or single_factor_frame.empty:
        return pd.DataFrame(columns=["factor", "decision", "reason", "quality_score"])
    blocked: set[str] = set()
    if correlation_frame is not None and not correlation_frame.empty:
        quality = {
            str(row.factor): _safe_float(row.quality_score)
            for row in single_factor_frame.itertuples(index=False)
            if hasattr(row, "factor") and hasattr(row, "quality_score")
        }
        for row in correlation_frame.itertuples(index=False):
            if _safe_float(getattr(row, "abs_correlation", 0.0)) < max_corr:
                continue
            a = str(getattr(row, "factor_a"))
            b = str(getattr(row, "factor_b"))
            loser = b if quality.get(a, 0.0) >= quality.get(b, 0.0) else a
            blocked.add(loser)
    rows: list[dict[str, object]] = []
    for row in single_factor_frame.itertuples(index=False):
        factor = str(getattr(row, "factor"))
        status = str(getattr(row, "status", ""))
        coverage = _safe_float(getattr(row, "coverage", 0.0))
        ic_abs = _safe_float(getattr(row, "rank_ic_abs_mean", abs(_safe_float(getattr(row, "rank_ic_mean", 0.0)))))
        quality = _safe_float(getattr(row, "quality_score", 0.0))
        reasons: list[str] = []
        if status != "ok":
            reasons.append("insufficient")
        if coverage < min_coverage:
            reasons.append("low_coverage")
        if ic_abs < min_ic_abs:
            reasons.append("weak_ic")
        if factor in blocked:
            reasons.append("highly_correlated_lower_quality")
        decision = "keep" if not reasons else "review"
        rows.append({"factor": factor, "decision": decision, "reason": ",".join(reasons), "quality_score": quality, "coverage": coverage, "rank_ic_abs_mean": ic_abs})
    return pd.DataFrame(rows).sort_values(["decision", "quality_score"], ascending=[True, False]).reset_index(drop=True)
