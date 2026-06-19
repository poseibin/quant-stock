from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FactorPreprocessConfig:
    mode: str = "none"
    lower: float = 0.01
    upper: float = 0.99
    fill_missing: bool = True
    standardize: bool = False
    rank_normalize: bool = False
    neutralize_size: bool = False
    neutralize_industry: bool = False
    add_missing_flags: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def preprocess_config(mode: str = "none") -> FactorPreprocessConfig:
    value = str(mode or "none").strip().lower()
    if value in {"", "none", "raw"}:
        return FactorPreprocessConfig(mode="none", fill_missing=False)
    if value in {"winsorize", "clip"}:
        return FactorPreprocessConfig(mode="winsorize")
    if value in {"zscore", "standardize"}:
        return FactorPreprocessConfig(mode="zscore", standardize=True)
    if value in {"winsorize_zscore", "clip_zscore", "standard"}:
        return FactorPreprocessConfig(mode="winsorize_zscore", standardize=True)
    if value in {"rank", "rank_normalize"}:
        return FactorPreprocessConfig(mode="rank_normalize", rank_normalize=True)
    if value in {"institutional", "production", "clean"}:
        return FactorPreprocessConfig(mode="institutional", standardize=True, neutralize_size=True, neutralize_industry=True, add_missing_flags=True)
    if value in {"size_neutral", "winsorize_zscore_size_neutral"}:
        return FactorPreprocessConfig(mode="size_neutral", standardize=True, neutralize_size=True)
    raise ValueError(f"unsupported factor preprocess mode: {mode}")


def factor_preprocess_report(frame: pd.DataFrame, factor_columns: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if frame.empty or not factor_columns:
        return pd.DataFrame(rows)
    total_rows = max(len(frame), 1)
    for column in factor_columns:
        if column not in frame.columns:
            rows.append({"factor": column, "status": "missing"})
            continue
        values = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        finite = values.dropna()
        rows.append(
            {
                "factor": column,
                "status": "ok" if len(finite) else "empty",
                "row_count": int(total_rows),
                "valid_count": int(len(finite)),
                "missing_count": int(total_rows - len(finite)),
                "missing_rate": float(1.0 - len(finite) / total_rows),
                "zero_rate": float((finite == 0).mean()) if len(finite) else 0.0,
                "mean": float(finite.mean()) if len(finite) else 0.0,
                "std": float(finite.std()) if len(finite) else 0.0,
                "min": float(finite.min()) if len(finite) else 0.0,
                "p01": float(finite.quantile(0.01)) if len(finite) else 0.0,
                "p50": float(finite.quantile(0.50)) if len(finite) else 0.0,
                "p99": float(finite.quantile(0.99)) if len(finite) else 0.0,
                "max": float(finite.max()) if len(finite) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _factor_loop_progress(
    progress_callback: Callable[[str, dict[str, object]], None] | None,
    event: str,
    column: str,
    index: int,
    total: int,
) -> None:
    if progress_callback and (index == 1 or index == total or index % 10 == 0):
        progress_callback(event, {"factor": column, "factor_index": index, "factor_count": total})


def winsorize_by_date(
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    lower: float = 0.01,
    upper: float = 0.99,
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> pd.DataFrame:
    if frame.empty or not factor_columns:
        return frame.copy()
    out = frame.copy()
    existing = [column for column in factor_columns if column in out.columns]
    if not existing:
        return out
    trade_dates = out["trade_date"]
    total = len(existing)
    for index, column in enumerate(existing, start=1):
        _factor_loop_progress(progress_callback, "preprocess_winsorize_progress", column, index, total)
        values = pd.to_numeric(out[column], errors="coerce")
        grouped = values.groupby(trade_dates)
        low_by_date = grouped.quantile(lower)
        high_by_date = grouped.quantile(upper)
        low = trade_dates.map(low_by_date)
        high = trade_dates.map(high_by_date)
        out[column] = values.clip(lower=low, upper=high).replace([np.inf, -np.inf], np.nan)
    return out


def fill_missing_by_date(
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    group_columns: Sequence[str] = (),
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> pd.DataFrame:
    if frame.empty or not factor_columns:
        return frame.copy()
    out = frame.copy()
    existing = [column for column in factor_columns if column in out.columns]
    groups = [column for column in group_columns if column in out.columns]
    total = len(existing)
    for index, column in enumerate(existing, start=1):
        _factor_loop_progress(progress_callback, "preprocess_fill_missing_progress", column, index, total)
        values = pd.to_numeric(out[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if groups:
            grouped_fill = values.groupby([out["trade_date"], *[out[group] for group in groups]], dropna=False).transform("median")
            values = values.fillna(grouped_fill)
        date_fill = values.groupby(out["trade_date"]).transform("median")
        out[column] = values.fillna(date_fill).fillna(0.0)
    return out


def zscore_by_date(
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> pd.DataFrame:
    if frame.empty or not factor_columns:
        return frame.copy()
    out = frame.copy()
    existing = [column for column in factor_columns if column in out.columns]
    if not existing:
        return out
    total = len(existing)
    for index, column in enumerate(existing, start=1):
        _factor_loop_progress(progress_callback, "preprocess_standardize_progress", column, index, total)
        values = pd.to_numeric(out[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        mean = values.groupby(out["trade_date"]).transform("mean")
        std = values.groupby(out["trade_date"]).transform("std").replace(0, np.nan)
        out[column] = ((values - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def rank_normalize_by_date(
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> pd.DataFrame:
    if frame.empty or not factor_columns:
        return frame.copy()
    out = frame.copy()
    existing = [column for column in factor_columns if column in out.columns]
    total = len(existing)
    for index, column in enumerate(existing, start=1):
        _factor_loop_progress(progress_callback, "preprocess_rank_normalize_progress", column, index, total)
        values = pd.to_numeric(out[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        ranks = values.groupby(out["trade_date"]).rank(pct=True, method="average")
        out[column] = ((ranks - 0.5) * 2.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def add_missing_flags(frame: pd.DataFrame, factor_columns: Sequence[str]) -> pd.DataFrame:
    if frame.empty or not factor_columns:
        return frame.copy()
    flags: dict[str, pd.Series] = {}
    for column in factor_columns:
        if column in frame.columns:
            flags[f"{column}__missing"] = pd.to_numeric(frame[column], errors="coerce").replace([np.inf, -np.inf], np.nan).isna().astype("int8")
    if not flags:
        return frame.copy()
    return pd.concat([frame.copy(), pd.DataFrame(flags, index=frame.index)], axis=1)


def neutralize_by_date(
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    *,
    size_columns: Sequence[str] = ("circ_mv_log", "total_mv_log", "size_pct_rank"),
    industry_columns: Sequence[str] = ("industry", "industry_name", "industry_code"),
    use_size: bool = True,
    use_industry: bool = False,
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> pd.DataFrame:
    if frame.empty or not factor_columns or "trade_date" not in frame.columns:
        return frame.copy()
    out = frame.copy()
    existing = [column for column in factor_columns if column in out.columns]
    size_column = next((column for column in size_columns if column in out.columns), "")
    industry_column = next((column for column in industry_columns if column in out.columns), "")
    if use_size and not size_column and not (use_industry and industry_column):
        return out
    date_groups = list(out.groupby("trade_date", sort=False).groups.items())
    total_dates = len(date_groups)
    for date_index, (_trade_date, index) in enumerate(date_groups, start=1):
        if progress_callback and (date_index == 1 or date_index == total_dates or date_index % 100 == 0):
            progress_callback(
                "preprocess_neutralize_progress",
                {
                    "trade_date": str(_trade_date),
                    "date_index": date_index,
                    "total_dates": total_dates,
                    "factor_count": len(existing),
                    "use_size": bool(use_size),
                    "use_industry": bool(use_industry),
                },
            )
        idx = list(index)
        design_parts: list[pd.DataFrame] = []
        if use_size and size_column:
            size = pd.to_numeric(out.loc[idx, size_column], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
            design_parts.append(pd.DataFrame({"_size": size.to_numpy()}, index=idx))
        if use_industry and industry_column:
            industry = out.loc[idx, industry_column].astype(str).fillna("")
            dummies = pd.get_dummies(industry, prefix="_ind", dtype=float)
            if len(dummies.columns) > 1:
                design_parts.append(dummies.iloc[:, 1:].set_index(pd.Index(idx)))
        if not design_parts:
            continue
        design = pd.concat(design_parts, axis=1)
        design.insert(0, "_intercept", 1.0)
        x = design.to_numpy(dtype=float)
        if x.shape[0] <= x.shape[1] + 20:
            continue
        for column in existing:
            y = pd.to_numeric(out.loc[idx, column], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy(dtype=float)
            try:
                beta, *_ = np.linalg.lstsq(x, y, rcond=None)
                out.loc[idx, column] = y - x.dot(beta)
            except Exception:
                continue
    return out


def preprocess_factors(
    frame: pd.DataFrame,
    factor_columns: Sequence[str],
    mode: str = "none",
    progress_callback: Callable[[str, dict[str, object]], None] | None = None,
) -> pd.DataFrame:
    config = preprocess_config(mode)
    if config.mode == "none":
        return frame.copy()
    out = frame.copy()
    if progress_callback:
        progress_callback("preprocess_start", {"mode": config.mode, "rows": len(out), "factor_count": len(factor_columns)})
    if config.add_missing_flags:
        if progress_callback:
            progress_callback("preprocess_missing_flags", {"factor_count": len(factor_columns)})
        out = add_missing_flags(out, factor_columns)
    if progress_callback:
        progress_callback("preprocess_winsorize", {"factor_count": len(factor_columns)})
    out = winsorize_by_date(out, factor_columns, lower=config.lower, upper=config.upper, progress_callback=progress_callback)
    if config.fill_missing:
        if progress_callback:
            progress_callback("preprocess_fill_missing", {"factor_count": len(factor_columns)})
        out = fill_missing_by_date(
            out,
            factor_columns,
            group_columns=("industry", "industry_name", "industry_code"),
            progress_callback=progress_callback,
        )
    if config.neutralize_size or config.neutralize_industry:
        if progress_callback:
            progress_callback(
                "preprocess_neutralize_start",
                {"factor_count": len(factor_columns), "use_size": config.neutralize_size, "use_industry": config.neutralize_industry},
            )
        out = neutralize_by_date(
            out,
            factor_columns,
            use_size=config.neutralize_size,
            use_industry=config.neutralize_industry,
            progress_callback=progress_callback,
        )
    if config.rank_normalize:
        if progress_callback:
            progress_callback("preprocess_rank_normalize", {"factor_count": len(factor_columns)})
        out = rank_normalize_by_date(out, factor_columns, progress_callback=progress_callback)
    if config.standardize:
        if progress_callback:
            progress_callback("preprocess_standardize", {"factor_count": len(factor_columns)})
        out = zscore_by_date(out, factor_columns, progress_callback=progress_callback)
    if progress_callback:
        progress_callback("preprocess_done", {"mode": config.mode, "rows": len(out), "factor_count": len(factor_columns)})
    return out
