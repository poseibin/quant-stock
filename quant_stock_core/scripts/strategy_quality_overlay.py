from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


QUALITY_FEATURES = [
    "small_cap_quality_score",
    "risk_penalty_score",
    "quality_gate",
    "market_state_score",
    "attack_weight",
    "defense_weight",
    "goodwill_to_equity",
    "recent_holder_reduce",
    "loss_streak",
]


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def clip01(value: pd.Series | float) -> pd.Series | float:
    if isinstance(value, pd.Series):
        return value.clip(lower=0.0, upper=1.0)
    return max(0.0, min(1.0, safe_float(value)))


def attach_asof_reports(
    market: pd.DataFrame,
    reports: pd.DataFrame,
    *,
    report_date_col: str,
    value_cols: Iterable[str],
) -> pd.DataFrame:
    value_cols = list(value_cols)
    if market.empty:
        return market
    out = market.sort_values(["ts_code", "trade_date"]).reset_index(drop=True).copy()
    for col in value_cols:
        if col not in out.columns:
            out[col] = 0.0
    if reports.empty:
        return out

    reports = reports.copy()
    reports[report_date_col] = reports[report_date_col].astype(str)
    reports["report_dt"] = pd.to_datetime(reports[report_date_col], format="%Y%m%d", errors="coerce")
    reports = reports.dropna(subset=["report_dt"])
    for col in value_cols:
        if col not in reports.columns:
            reports[col] = 0.0
        reports[col] = pd.to_numeric(reports[col], errors="coerce").fillna(0.0)
    report_groups = {code: group.sort_values("report_dt") for code, group in reports.groupby("ts_code", sort=False)}

    parts: list[pd.DataFrame] = []
    for code, group in out.groupby("ts_code", sort=False):
        current = group.copy()
        current["trade_dt"] = pd.to_datetime(current["trade_date"], format="%Y%m%d", errors="coerce")
        report = report_groups.get(str(code))
        if report is None or report.empty:
            current = current.drop(columns=["trade_dt"])
            parts.append(current)
            continue
        joined = pd.merge_asof(
            current.sort_values("trade_dt"),
            report[["report_dt", *value_cols]].sort_values("report_dt"),
            left_on="trade_dt",
            right_on="report_dt",
            direction="backward",
            suffixes=("", "_report"),
        )
        for col in value_cols:
            report_col = f"{col}_report"
            if report_col in joined.columns:
                joined[col] = joined[report_col].fillna(joined[col]).fillna(0.0)
                joined = joined.drop(columns=[report_col])
            else:
                joined[col] = joined[col].fillna(0.0)
        parts.append(joined.drop(columns=["trade_dt", "report_dt"]))
    return pd.concat(parts, ignore_index=True).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def attach_recent_holder_reduce(market: pd.DataFrame, holder: pd.DataFrame, *, window_days: int = 180) -> pd.DataFrame:
    if market.empty:
        return market
    out = market.copy()
    out["recent_holder_reduce"] = 0.0
    if holder.empty:
        return out
    holder = holder.copy()
    holder["ann_date"] = holder["ann_date"].astype(str)
    holder["ann_dt"] = pd.to_datetime(holder["ann_date"], format="%Y%m%d", errors="coerce")
    holder = holder.dropna(subset=["ann_dt"])
    if holder.empty:
        return out
    holder["change_ratio"] = pd.to_numeric(holder.get("change_ratio", 0), errors="coerce").fillna(0.0)
    holder["change_vol"] = pd.to_numeric(holder.get("change_vol", 0), errors="coerce").fillna(0.0)
    holder["in_de"] = holder.get("in_de", "").astype(str)
    reduce_mask = holder["in_de"].str.contains("减", na=False) | (holder["change_ratio"] < 0) | (holder["change_vol"] < 0)
    holder = holder[reduce_mask]
    if holder.empty:
        return out
    holder_groups = {code: group.sort_values("ann_dt") for code, group in holder.groupby("ts_code", sort=False)}
    parts: list[pd.DataFrame] = []
    for code, group in out.groupby("ts_code", sort=False):
        current = group.copy()
        events = holder_groups.get(str(code))
        if events is None or events.empty:
            parts.append(current)
            continue
        trade_dt = pd.to_datetime(current["trade_date"], format="%Y%m%d", errors="coerce")
        values: list[float] = []
        for dt in trade_dt:
            if pd.isna(dt):
                values.append(0.0)
                continue
            start = dt - pd.Timedelta(days=window_days)
            recent = events[(events["ann_dt"] <= dt) & (events["ann_dt"] >= start)]
            values.append(float(min(len(recent), 5)) / 5.0)
        current["recent_holder_reduce"] = values
        parts.append(current)
    return pd.concat(parts, ignore_index=True).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def balance_quality_reports(balance: pd.DataFrame) -> pd.DataFrame:
    if balance.empty:
        return pd.DataFrame(columns=["ts_code", "report_date", "goodwill_to_equity"])
    out = balance.copy()
    out["report_date"] = out.get("ann_date", out.get("end_date", "")).astype(str)
    out["goodwill"] = pd.to_numeric(out.get("goodwill", 0), errors="coerce").fillna(0.0)
    equity = pd.to_numeric(out.get("equity", out.get("total_hldr_eqy_exc_min_int", 0)), errors="coerce").fillna(0.0)
    out["goodwill_to_equity"] = np.where(equity > 0, out["goodwill"] / equity, 0.0)
    return out[["ts_code", "report_date", "goodwill_to_equity"]]


def income_loss_streak_reports(income: pd.DataFrame) -> pd.DataFrame:
    if income.empty:
        return pd.DataFrame(columns=["ts_code", "report_date", "loss_streak"])
    out = income.copy()
    out["report_date"] = out.get("ann_date", out.get("end_date", "")).astype(str)
    out["end_date"] = out.get("end_date", "").astype(str)
    out["profit"] = pd.to_numeric(out.get("n_income_attr_p", out.get("n_income", 0)), errors="coerce").fillna(0.0)
    out = out[out["end_date"].str.endswith("1231", na=False)].copy()
    if out.empty:
        return pd.DataFrame(columns=["ts_code", "report_date", "loss_streak"])
    rows: list[dict[str, object]] = []
    for code, group in out.sort_values(["ts_code", "end_date", "report_date"]).groupby("ts_code", sort=False):
        streak = 0
        for row in group.drop_duplicates("end_date", keep="last").itertuples(index=False):
            streak = streak + 1 if safe_float(getattr(row, "profit", 0)) < 0 else 0
            rows.append({"ts_code": str(code), "report_date": str(getattr(row, "report_date", "")), "loss_streak": float(streak)})
    return pd.DataFrame(rows)


def add_quality_overlay(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in [
        "close",
        "amount",
        "turnover_rate",
        "volume_ratio",
        "total_mv",
        "circ_mv",
        "pb",
        "roe",
        "netprofit_margin",
        "debt_to_assets",
        "goodwill_to_equity",
        "recent_holder_reduce",
        "loss_streak",
        "market_up_ratio",
        "market_up_ratio_3",
        "market_up_ratio_5",
        "market_limit_up_ratio",
        "market_limit_up_ratio_3",
        "market_limit_pressure",
        "market_risk_pressure",
    ]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)

    circ_mv = out["circ_mv"].where(out["circ_mv"] > 0, out["total_mv"])
    size_score = clip01((1_200_000.0 - circ_mv) / 950_000.0)
    price_score = clip01((18.0 - out["close"]) / 15.0)
    liquidity_score = clip01((out["amount"] - 30_000.0) / 120_000.0)
    pb_score = np.where(out["pb"] <= 0, 0.45, clip01((8.0 - out["pb"]) / 7.0))
    roe_score = clip01((out["roe"] + 2.0) / 14.0)
    debt_score = np.where(out["debt_to_assets"] <= 0, 0.55, clip01((82.0 - out["debt_to_assets"]) / 52.0))
    margin_score = clip01((out["netprofit_margin"] + 3.0) / 18.0)
    goodwill_score = np.where(out["goodwill_to_equity"] <= 0, 0.75, clip01((0.65 - out["goodwill_to_equity"]) / 0.65))
    loss_score = clip01((2.1 - out["loss_streak"]) / 2.1)

    out["small_cap_quality_score"] = (
        size_score * 25.0
        + price_score * 10.0
        + liquidity_score * 16.0
        + pb_score * 13.0
        + roe_score * 16.0
        + debt_score * 10.0
        + margin_score * 5.0
        + goodwill_score * 3.0
        + loss_score * 2.0
    )

    name = out.get("name", pd.Series("", index=out.index)).astype(str).str.upper()
    list_status = out.get("list_status", pd.Series("L", index=out.index)).astype(str)
    st_or_delist = name.str.contains("ST", na=False) | name.str.contains("退市", na=False) | (list_status != "L")
    risk = pd.Series(0.0, index=out.index, dtype="float64")
    risk += st_or_delist.astype(float) * 100.0
    risk += (out["amount"] < 25_000.0).astype(float) * 28.0
    risk += ((out["pb"] > 12.0) | ((out["pb"] > 0) & (out["pb"] < 0.35))).astype(float) * 18.0
    risk += (out["roe"] < -2.0).astype(float) * 16.0
    risk += (out["debt_to_assets"] > 82.0).astype(float) * 22.0
    risk += (out["goodwill_to_equity"] > 0.65).astype(float) * 20.0
    risk += (out["loss_streak"] >= 2.0).astype(float) * 22.0
    risk += out["recent_holder_reduce"].clip(0, 1) * 18.0
    out["risk_penalty_score"] = risk.clip(0, 100)
    out["quality_gate"] = ((out["small_cap_quality_score"] >= 42.0) & (out["risk_penalty_score"] <= 42.0)).astype(int)

    up_ratio = out["market_up_ratio_5"].where(out["market_up_ratio_5"] > 0, out["market_up_ratio_3"])
    up_ratio = up_ratio.where(up_ratio > 0, out["market_up_ratio"])
    limit_ratio = out["market_limit_up_ratio_3"].where(out["market_limit_up_ratio_3"] > 0, out["market_limit_up_ratio"])
    pressure = out["market_limit_pressure"].where(out["market_limit_pressure"] > 0, 1.0 - out["market_risk_pressure"])
    out["market_state_score"] = (
        up_ratio.clip(0, 1) * 42.0
        + (limit_ratio / 0.018).clip(0, 1) * 28.0
        + pressure.clip(0, 1) * 30.0
    ).fillna(45.0)
    weak = (55.0 - out["market_state_score"]).clip(lower=0.0) / 55.0
    out["attack_weight"] = (1.08 - weak * 0.34).clip(0.70, 1.10)
    out["defense_weight"] = (0.92 + weak * 0.46).clip(0.90, 1.38)
    out[QUALITY_FEATURES] = out[QUALITY_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out
