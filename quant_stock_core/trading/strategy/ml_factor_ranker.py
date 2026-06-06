"""LightGBM factor score strategy."""
from __future__ import annotations

import os

import duckdb
import numpy as np
import pandas as pd

from common.infra.db import connect_db
from common.config.settings import DATA_ROOT
from research.data.storage import duckdb_query as dq
from trading.strategy.base import BaseStrategy, StrategyConfig
from trading.strategy.registry import register


class MLFactorRankerStrategy(BaseStrategy):
    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        preds = _load_predictions(start, end, str((self.cfg.selection or {}).get("run_id") or ""))
        if preds.empty:
            return pd.DataFrame()
        preds = _enrich_stock_info(preds)
        preds = _attach_market_risk_state(preds)
        preds = _apply_universe(preds, self.cfg)
        preds = _apply_stress_controls(preds, self.cfg)
        preds = _apply_crash_warning_candidate_controls(preds, self.cfg)
        if preds.empty:
            return pd.DataFrame()

        frames: list[pd.DataFrame] = []
        regime = (self.cfg.filters or {}).get("market_regime") or {}
        daily_overlay = bool(regime.get("daily_risk_overlay", False))
        exposures = _market_exposure_map(sorted(preds["trade_date"].astype(str).unique().tolist()), self.cfg) if not daily_overlay else {}
        for date, group in preds.groupby("trade_date", sort=True):
            weights = _weights_from_predictions(group, str(date), self.cfg)
            if not weights.empty:
                if not daily_overlay:
                    weights = weights * exposures.get(str(date), 1.0)
                frames.append(weights)
        if not frames:
            return pd.DataFrame()
        base = pd.concat(frames).sort_index().fillna(0.0)
        base = _apply_crash_rebalance_gate(base, self.cfg)
        base = _apply_crash_warning_overlay(base, start, end, self.cfg)
        base = _apply_crash_warning_model_overlay(base, start, end, self.cfg)
        base = _apply_intramonth_crash_exit(base, start, end, self.cfg)
        if daily_overlay:
            return _apply_daily_exposure_overlay(base, start, end, self.cfg)
        return base


def _load_predictions(start: str, end: str, run_id: str) -> pd.DataFrame:
    db_path = os.getenv("DESKTOP_DB_PATH") or str(DATA_ROOT / "meta.db")
    with connect_db(db_path) as conn:
        if not run_id:
            row = conn.execute(
                "SELECT run_id FROM factor_model_runs WHERE status = ? ORDER BY updated_at DESC LIMIT 1",
                ("success",),
            ).fetchone()
            run_id = str(row[0]) if row else ""
        if not run_id:
            return pd.DataFrame()
        rows = conn.execute(
            """
            SELECT trade_date, ts_code, pred_score, pred_rank, realized_return, test_year
            FROM factor_model_predictions
            WHERE run_id = ? AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date, pred_score DESC
            """,
            (run_id, start, end),
        ).fetchall()
    return pd.DataFrame(rows, columns=["trade_date", "ts_code", "pred_score", "pred_rank", "realized_return", "test_year"])


def _enrich_stock_info(preds: pd.DataFrame) -> pd.DataFrame:
    if preds.empty:
        return preds
    keys = preds[["trade_date", "ts_code"]].drop_duplicates().copy()
    keys["trade_date"] = keys["trade_date"].astype(str)
    keys["ts_code"] = keys["ts_code"].astype(str)
    start = (pd.to_datetime(keys["trade_date"].min(), format="%Y%m%d") - pd.Timedelta(days=220)).strftime("%Y%m%d")
    end = str(keys["trade_date"].max())
    with duckdb.connect() as conn:
        conn.register("pred_keys", keys)
        info = conn.execute(
            f"""
            WITH daily_metrics AS (
              SELECT d.trade_date, d.ts_code,
                     d.amount * 1000 AS amount,
                     d.pct_chg / 100.0 AS pct_chg,
                     d.close / NULLIF(lag(d.close, 20) OVER w, 0) - 1 AS ret20,
                     stddev_pop(d.pct_chg / 100.0) OVER (
                       PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                     ) * sqrt(244.0) AS vol20,
                     d.amount / NULLIF(avg(d.amount) OVER (
                       PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                     ), 0) - 1 AS amount_chg20,
                     d.close / NULLIF(max(d.close) OVER (
                       PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                     ), 0) - 1 AS dist_high60
              FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
              WHERE d.trade_date BETWEEN '{start}' AND '{end}'
              WINDOW w AS (PARTITION BY d.ts_code ORDER BY d.trade_date)
            )
            SELECT k.trade_date, k.ts_code,
                   sb.name, sb.industry,
                   db.total_mv * 10000 AS total_mv,
                   db.circ_mv * 10000 AS circ_mv,
                   db.turnover_rate,
                   dm.amount,
                   dm.pct_chg,
                   dm.ret20,
                   dm.vol20,
                   dm.amount_chg20,
                   dm.dist_high60
            FROM pred_keys k
            LEFT JOIN read_parquet('{dq.RAW_DIR / "stock_basic" / "data.parquet"}') sb
              ON k.ts_code = sb.ts_code
            LEFT JOIN read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}') db
              ON k.trade_date = db.trade_date AND k.ts_code = db.ts_code
            LEFT JOIN daily_metrics dm
              ON k.trade_date = dm.trade_date AND k.ts_code = dm.ts_code
            """
        ).fetchdf()
    out = preds.merge(info, on=["trade_date", "ts_code"], how="left")
    return out.replace([np.inf, -np.inf], np.nan)


def _attach_market_risk_state(preds: pd.DataFrame) -> pd.DataFrame:
    if preds.empty:
        return preds
    dates = sorted(preds["trade_date"].astype(str).unique().tolist())
    db_path = os.getenv("DESKTOP_DB_PATH") or str(DATA_ROOT / "meta.db")
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT trade_date, state, COALESCE(risk_score, 0), COALESCE(limit_down_ratio5, 0),
                       COALESCE(small_large_rel20, 0), COALESCE(drawdown60, 0), COALESCE(volatility20, 0)
                FROM market_risk_state_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (min(dates), max(dates)),
            ).fetchall()
    except Exception:
        rows = []
    if not rows:
        out = preds.copy()
        out["market_state"] = "normal"
        out["market_risk_score"] = 0.0
        out["market_limit_down_ratio5"] = 0.0
        out["market_small_large_rel20"] = 0.0
        out["market_drawdown60"] = 0.0
        out["market_volatility20"] = 0.0
        return out
    states = pd.DataFrame(
        rows,
        columns=[
            "trade_date", "market_state", "market_risk_score", "market_limit_down_ratio5",
            "market_small_large_rel20", "market_drawdown60", "market_volatility20",
        ],
    )
    states["trade_date"] = states["trade_date"].astype(str)
    out = preds.merge(states, on="trade_date", how="left")
    out["market_state"] = out["market_state"].fillna("normal")
    for col in ["market_risk_score", "market_limit_down_ratio5", "market_small_large_rel20", "market_drawdown60", "market_volatility20"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out


def _apply_universe(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    u = cfg.universe or {}
    f = cfg.filters or {}
    out = df.copy()
    if f.get("exclude_st", True):
        out = out[~out["name"].fillna("").str.contains("ST", na=False)]
    if u.get("exclude_bj", True):
        out = out[~out["ts_code"].astype(str).str.endswith(".BJ")]
    if u.get("min_total_mv") is not None:
        out = out[pd.to_numeric(out["total_mv"], errors="coerce").fillna(0) >= float(u["min_total_mv"])]
    if u.get("max_total_mv") is not None:
        out = out[pd.to_numeric(out["total_mv"], errors="coerce").fillna(0) <= float(u["max_total_mv"])]
    if u.get("min_amount") is not None:
        out = out[pd.to_numeric(out["amount"], errors="coerce").fillna(0) >= float(u["min_amount"])]
    if f.get("max_day_return") is not None:
        out = out[pd.to_numeric(out["pct_chg"], errors="coerce").fillna(0) <= float(f["max_day_return"])]
    min_rank = float((cfg.selection or {}).get("min_pred_rank", 0.95))
    out = out[pd.to_numeric(out["pred_rank"], errors="coerce").fillna(0) >= min_rank]
    return out


def _apply_stress_controls(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    controls = (cfg.filters or {}).get("stress_controls") or {}
    if df.empty or not bool(controls.get("enabled", False)):
        return df
    out = df.copy()
    state = out["market_state"].fillna("normal").astype(str) if "market_state" in out.columns else pd.Series("normal", index=out.index)
    stress_mask = state.isin([str(x) for x in controls.get("states", ["weak", "crash"])])
    if not stress_mask.any():
        return out

    crash_mask = state.eq("crash")
    weak_mask = state.eq("weak")
    min_amount_mult = float(controls.get("stress_min_amount_mult", 1.5))
    min_amount = float((cfg.universe or {}).get("min_amount") or 0.0) * min_amount_mult
    max_ret20 = float(controls.get("max_ret20", 0.25))
    max_vol20 = float(controls.get("max_vol20", 0.75))
    max_amount_chg20 = float(controls.get("max_amount_chg20", 3.0))
    max_turnover = float(controls.get("max_turnover_rate", 18.0))
    if min_amount > 0:
        out = out[~stress_mask | (pd.to_numeric(out["amount"], errors="coerce").fillna(0.0) >= min_amount)]
        stress_mask = out["market_state"].fillna("normal").astype(str).isin([str(x) for x in controls.get("states", ["weak", "crash"])])
        crash_mask = out["market_state"].fillna("normal").astype(str).eq("crash")
        weak_mask = out["market_state"].fillna("normal").astype(str).eq("weak")
    for col, limit in [
        ("ret20", max_ret20),
        ("vol20", max_vol20),
        ("amount_chg20", max_amount_chg20),
        ("turnover_rate", max_turnover),
    ]:
        if col in out.columns:
            values = pd.to_numeric(out[col], errors="coerce")
            out = out[~stress_mask | values.isna() | (values <= limit)]
            stress_mask = out["market_state"].fillna("normal").astype(str).isin([str(x) for x in controls.get("states", ["weak", "crash"])])
            crash_mask = out["market_state"].fillna("normal").astype(str).eq("crash")
            weak_mask = out["market_state"].fillna("normal").astype(str).eq("weak")
    if out.empty:
        return out

    penalty = pd.Series(0.0, index=out.index, dtype="float64")
    ret20 = pd.to_numeric(out.get("ret20", 0.0), errors="coerce").fillna(0.0)
    vol20 = pd.to_numeric(out.get("vol20", 0.0), errors="coerce").fillna(0.0)
    amount_chg20 = pd.to_numeric(out.get("amount_chg20", 0.0), errors="coerce").fillna(0.0)
    turnover = pd.to_numeric(out.get("turnover_rate", 0.0), errors="coerce").fillna(0.0)
    dist_high60 = pd.to_numeric(out.get("dist_high60", 0.0), errors="coerce").fillna(0.0)
    penalty += stress_mask.astype(float) * (
        ret20.clip(lower=0.0) * float(controls.get("ret20_penalty", 0.20))
        + vol20.clip(lower=0.0) * float(controls.get("vol20_penalty", 0.08))
        + amount_chg20.clip(lower=0.0) * float(controls.get("amount_chg20_penalty", 0.015))
        + (turnover / 100.0).clip(lower=0.0) * float(controls.get("turnover_penalty", 0.08))
    )
    penalty += crash_mask.astype(float) * dist_high60.clip(upper=0.0).abs() * float(controls.get("crash_drawdown_penalty", 0.10))
    penalty += weak_mask.astype(float) * float(controls.get("weak_base_penalty", 0.0))
    out["stress_adjusted_score"] = pd.to_numeric(out["pred_score"], errors="coerce") - penalty
    if bool(controls.get("use_adjusted_score", True)):
        out["pred_score"] = out["stress_adjusted_score"]
    return out


def _apply_crash_warning_candidate_controls(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    controls = (cfg.filters or {}).get("crash_warning_candidates") or {}
    if df.empty or not bool(controls.get("enabled", False)):
        return df

    dates = sorted(df["trade_date"].astype(str).unique().tolist())
    prob = _crash_warning_probability_series(dates, str(controls.get("run_id") or "").strip())
    if prob.empty:
        return df
    prob = prob.reindex(dates, method="ffill").fillna(0.0).astype(float)

    out = df.copy()
    out["crash_warning_prob"] = out["trade_date"].astype(str).map(prob).fillna(0.0).astype(float)
    threshold = float(controls.get("threshold", 0.45))
    severe_threshold = float(controls.get("severe_threshold", 0.65))
    warning_mask = out["crash_warning_prob"] >= threshold
    if not warning_mask.any():
        return out

    severe_mask = out["crash_warning_prob"] >= severe_threshold
    min_amount_mult = float(controls.get("min_amount_mult", 1.0))
    severe_min_amount_mult = float(controls.get("severe_min_amount_mult", min_amount_mult))
    base_min_amount = float((cfg.universe or {}).get("min_amount") or 0.0)
    if base_min_amount > 0 and min_amount_mult > 0:
        amount = pd.to_numeric(out.get("amount", 0.0), errors="coerce").fillna(0.0)
        min_amount = base_min_amount * min_amount_mult
        severe_min_amount = base_min_amount * severe_min_amount_mult
        keep = ~warning_mask | (amount >= min_amount)
        keep &= ~severe_mask | (amount >= severe_min_amount)
        out = out[keep]
        if out.empty:
            return out
        warning_mask = out["crash_warning_prob"] >= threshold
        severe_mask = out["crash_warning_prob"] >= severe_threshold

    for col, cfg_key, severe_key in [
        ("ret20", "max_ret20", "severe_max_ret20"),
        ("vol20", "max_vol20", "severe_max_vol20"),
        ("amount_chg20", "max_amount_chg20", "severe_max_amount_chg20"),
        ("turnover_rate", "max_turnover_rate", "severe_max_turnover_rate"),
    ]:
        if col not in out.columns or controls.get(cfg_key) is None:
            continue
        values = pd.to_numeric(out[col], errors="coerce")
        limit = float(controls[cfg_key])
        severe_limit = float(controls.get(severe_key, limit))
        keep = ~warning_mask | values.isna() | (values <= limit)
        keep &= ~severe_mask | values.isna() | (values <= severe_limit)
        out = out[keep]
        if out.empty:
            return out
        warning_mask = out["crash_warning_prob"] >= threshold
        severe_mask = out["crash_warning_prob"] >= severe_threshold

    penalty = pd.Series(0.0, index=out.index, dtype="float64")
    ret20 = pd.to_numeric(out.get("ret20", 0.0), errors="coerce").fillna(0.0)
    vol20 = pd.to_numeric(out.get("vol20", 0.0), errors="coerce").fillna(0.0)
    amount_chg20 = pd.to_numeric(out.get("amount_chg20", 0.0), errors="coerce").fillna(0.0)
    turnover = pd.to_numeric(out.get("turnover_rate", 0.0), errors="coerce").fillna(0.0)
    warning_strength = ((out["crash_warning_prob"] - threshold) / max(1e-6, 1.0 - threshold)).clip(0.0, 1.0)
    penalty += warning_mask.astype(float) * warning_strength * (
        ret20.clip(lower=0.0) * float(controls.get("ret20_penalty", 0.08))
        + vol20.clip(lower=0.0) * float(controls.get("vol20_penalty", 0.04))
        + amount_chg20.clip(lower=0.0) * float(controls.get("amount_chg20_penalty", 0.015))
        + (turnover / 100.0).clip(lower=0.0) * float(controls.get("turnover_penalty", 0.04))
    )
    out["crash_warning_adjusted_score"] = pd.to_numeric(out["pred_score"], errors="coerce") - penalty
    if bool(controls.get("use_adjusted_score", True)):
        out["pred_score"] = out["crash_warning_adjusted_score"]
    return out


def _apply_crash_rebalance_gate(weights: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    gate = (cfg.filters or {}).get("crash_gate") or {}
    if weights.empty or not bool(gate.get("enabled", False)):
        return weights

    dates = sorted(str(date) for date in weights.index.astype(str).tolist())
    states = _market_state_series(dates, int(gate.get("lookback_days", 10)))
    if states.empty:
        return weights

    mode = str(gate.get("mode", "skip_rebalance"))
    crash_states = {str(x) for x in gate.get("crash_states", ["crash"])}
    recovery_states = {str(x) for x in gate.get("recovery_states", ["liquidity_squeeze", "post_crash_repair", "normal"])}
    lookback_days = max(1, int(gate.get("lookback_days", 10)))
    hold_previous = bool(gate.get("hold_previous", mode != "cash"))
    cash_exposure = float(gate.get("cash_exposure", 0.0))
    max_skip_periods = int(gate.get("max_skip_periods", 2))

    out_rows: list[pd.Series] = []
    out_index: list[str] = []
    previous: pd.Series | None = None
    in_cooldown = False
    skipped_periods = 0

    for date in dates:
        target = weights.loc[date].astype(float).copy()
        recent = states.loc[states.index <= date].tail(lookback_days)
        latest_state = str(recent.iloc[-1]) if not recent.empty else "normal"
        recent_crash = bool(recent.isin(crash_states).any()) if not recent.empty else False
        recovered = latest_state in recovery_states and not recent_crash

        if mode == "cash":
            if recent_crash:
                target = target * cash_exposure
        elif mode == "recovery_confirm":
            if recent_crash:
                in_cooldown = True
                skipped_periods = 0
            if in_cooldown:
                if recovered or (max_skip_periods > 0 and skipped_periods >= max_skip_periods):
                    in_cooldown = False
                else:
                    target = previous.copy() if hold_previous and previous is not None else target * cash_exposure
                    skipped_periods += 1
        else:
            if recent_crash:
                target = previous.copy() if hold_previous and previous is not None else target * cash_exposure

        out_rows.append(target)
        out_index.append(date)
        previous = target.copy()

    return pd.DataFrame(out_rows, index=out_index).reindex(columns=weights.columns).fillna(0.0)


def _market_state_series(dates: list[str], lookback_days: int) -> pd.Series:
    if not dates:
        return pd.Series(dtype="object")
    pad_days = max(lookback_days * 4, 30)
    start = (pd.to_datetime(min(dates), format="%Y%m%d") - pd.Timedelta(days=pad_days)).strftime("%Y%m%d")
    end = max(dates)
    db_path = os.getenv("DESKTOP_DB_PATH") or str(DATA_ROOT / "meta.db")
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT trade_date, state
                FROM market_risk_state_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (start, end),
            ).fetchall()
    except Exception:
        return pd.Series(dtype="object")
    if not rows:
        return pd.Series(dtype="object")
    series = pd.Series({str(date): str(state) for date, state in rows}, dtype="object")
    return series.sort_index()


def _market_risk_frame(dates: list[str], lookback_days: int) -> pd.DataFrame:
    if not dates:
        return pd.DataFrame()
    pad_days = max(lookback_days * 4, 30)
    start = (pd.to_datetime(min(dates), format="%Y%m%d") - pd.Timedelta(days=pad_days)).strftime("%Y%m%d")
    end = max(dates)
    db_path = os.getenv("DESKTOP_DB_PATH") or str(DATA_ROOT / "meta.db")
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT trade_date, state, COALESCE(risk_score, 0), COALESCE(market_return, 0),
                       COALESCE(up_ratio, 0), COALESCE(breadth20, 0),
                       COALESCE(limit_down_ratio, 0), COALESCE(limit_down_ratio5, 0),
                       COALESCE(amount_chg20, 0), COALESCE(small_large_rel20, 0),
                       COALESCE(drawdown20, 0), COALESCE(drawdown60, 0),
                       COALESCE(volatility20, 0)
                FROM market_risk_state_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (start, end),
            ).fetchall()
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows,
        columns=[
            "trade_date", "state", "risk_score", "market_return", "up_ratio", "breadth20",
            "limit_down_ratio", "limit_down_ratio5", "amount_chg20", "small_large_rel20",
            "drawdown20", "drawdown60", "volatility20",
        ],
    )
    frame["trade_date"] = frame["trade_date"].astype(str)
    for col in frame.columns:
        if col not in {"trade_date", "state"}:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    return frame.set_index("trade_date").sort_index()


def _apply_crash_warning_overlay(weights: pd.DataFrame, start: str, end: str, cfg: StrategyConfig) -> pd.DataFrame:
    warning = (cfg.filters or {}).get("crash_warning") or {}
    if weights.empty or not bool(warning.get("enabled", False)):
        return weights

    dates = dq.get_trade_dates(start, end)
    if not dates:
        return weights
    dates = [date for date in dates if date >= str(weights.index.min()) and date <= end]
    if not dates:
        return weights

    risk = _market_risk_frame(dates, int(warning.get("lookback_days", 5)))
    if risk.empty:
        return weights
    risk = risk.reindex(dates, method="ffill")

    normal_exposure = float(warning.get("normal_exposure", 1.0))
    warning_exposure = float(warning.get("warning_exposure", 0.65))
    severe_exposure = float(warning.get("severe_exposure", 0.35))
    min_risk_score = float(warning.get("min_risk_score", 38.0))
    severe_risk_score = float(warning.get("severe_risk_score", 55.0))
    max_market_return = float(warning.get("max_market_return", -0.035))
    severe_market_return = float(warning.get("severe_market_return", -0.05))
    max_up_ratio = float(warning.get("max_up_ratio", 0.22))
    max_breadth20 = float(warning.get("max_breadth20", 0.40))
    min_limit_down_ratio = float(warning.get("min_limit_down_ratio", 0.012))
    min_limit_down_ratio5 = float(warning.get("min_limit_down_ratio5", 0.010))
    max_drawdown20 = float(warning.get("max_drawdown20", -0.08))
    max_small_large_rel20 = float(warning.get("max_small_large_rel20", -0.10))
    cooldown_days = max(0, int(warning.get("cooldown_days", 1)))
    severe_cooldown_days = max(cooldown_days, int(warning.get("severe_cooldown_days", cooldown_days + 1)))

    daily = weights.reindex(dates).ffill().fillna(0.0)
    exposure = pd.Series(normal_exposure, index=dates, dtype="float64")
    cooldown_left = 0
    cooldown_exposure = normal_exposure

    for date in dates:
        row = risk.loc[date]
        score = float(row.get("risk_score") or 0.0)
        market_return = float(row.get("market_return") or 0.0)
        up_ratio = float(row.get("up_ratio") or 0.0)
        breadth20 = float(row.get("breadth20") or 0.0)
        limit_down = float(row.get("limit_down_ratio") or 0.0)
        limit_down5 = float(row.get("limit_down_ratio5") or 0.0)
        drawdown20 = float(row.get("drawdown20") or 0.0)
        rel20 = float(row.get("small_large_rel20") or 0.0)

        warning_hit = (
            score >= min_risk_score
            or market_return <= max_market_return
            or (limit_down5 >= min_limit_down_ratio5 and breadth20 <= max_breadth20)
            or (limit_down >= min_limit_down_ratio and up_ratio <= max_up_ratio)
            or (drawdown20 <= max_drawdown20 and breadth20 <= max_breadth20)
            or (rel20 <= max_small_large_rel20 and breadth20 <= max_breadth20)
        )
        severe_hit = (
            score >= severe_risk_score
            or market_return <= severe_market_return
            or limit_down >= min_limit_down_ratio * 2.0
        )

        if severe_hit:
            cooldown_left = severe_cooldown_days
            cooldown_exposure = severe_exposure
        elif warning_hit and cooldown_left <= 0:
            cooldown_left = cooldown_days
            cooldown_exposure = warning_exposure

        if cooldown_left > 0:
            exposure.loc[date] = min(exposure.loc[date], cooldown_exposure)
            cooldown_left -= 1

    return daily.mul(exposure, axis=0).fillna(0.0)


def _apply_crash_warning_model_overlay(weights: pd.DataFrame, start: str, end: str, cfg: StrategyConfig) -> pd.DataFrame:
    model_cfg = (cfg.filters or {}).get("crash_warning_model") or {}
    if weights.empty or not bool(model_cfg.get("enabled", False)):
        return weights

    dates = dq.get_trade_dates(start, end)
    if not dates:
        return weights
    dates = [date for date in dates if date >= str(weights.index.min()) and date <= end]
    if not dates:
        return weights

    run_id = str(model_cfg.get("run_id") or "").strip()
    prob = _crash_warning_probability_series(dates, run_id)
    if prob.empty:
        return weights
    prob = prob.reindex(dates, method="ffill").fillna(0.0).astype(float)
    condition = _crash_warning_condition_mask(dates, weights, start, end, model_cfg)

    warning_threshold = float(model_cfg.get("warning_threshold", 0.45))
    severe_threshold = float(model_cfg.get("severe_threshold", 0.65))
    warning_exposure = float(model_cfg.get("warning_exposure", 0.80))
    severe_exposure = float(model_cfg.get("severe_exposure", 0.55))
    cooldown_days = max(0, int(model_cfg.get("cooldown_days", 1)))
    severe_cooldown_days = max(cooldown_days, int(model_cfg.get("severe_cooldown_days", cooldown_days + 1)))

    daily = weights.reindex(dates).ffill().fillna(0.0)
    exposure = pd.Series(1.0, index=dates, dtype="float64")
    cooldown_left = 0
    cooldown_exposure = 1.0
    for date in dates:
        value = float(prob.get(date) or 0.0)
        allowed = bool(condition.get(date, True))
        if allowed and value >= severe_threshold:
            cooldown_left = severe_cooldown_days
            cooldown_exposure = severe_exposure
        elif allowed and value >= warning_threshold and cooldown_left <= 0:
            cooldown_left = cooldown_days
            cooldown_exposure = warning_exposure
        if cooldown_left > 0:
            exposure.loc[date] = min(exposure.loc[date], cooldown_exposure)
            cooldown_left -= 1
    return daily.mul(exposure, axis=0).fillna(0.0)


def _crash_warning_probability_series(dates: list[str], run_id: str) -> pd.Series:
    if not dates:
        return pd.Series(dtype="float64")
    db_path = os.getenv("DESKTOP_DB_PATH") or str(DATA_ROOT / "meta.db")
    try:
        with connect_db(db_path) as conn:
            if not run_id:
                row = conn.execute(
                    "SELECT run_id FROM market_crash_warning_runs WHERE status = ? ORDER BY updated_at DESC LIMIT 1",
                    ("success",),
                ).fetchone()
                run_id = str(row[0]) if row else ""
            if not run_id:
                return pd.Series(dtype="float64")
            rows = conn.execute(
                """
                SELECT trade_date, COALESCE(shock_prob, 0)
                FROM market_crash_warning_predictions
                WHERE run_id = ? AND trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (run_id, min(dates), max(dates)),
            ).fetchall()
    except Exception:
        return pd.Series(dtype="float64")
    if not rows:
        return pd.Series(dtype="float64")
    return pd.Series({str(date): float(prob or 0.0) for date, prob in rows}, dtype="float64").sort_index()


def _crash_warning_condition_mask(
    dates: list[str],
    weights: pd.DataFrame,
    start: str,
    end: str,
    model_cfg: dict,
) -> pd.Series:
    condition_cfg = model_cfg.get("condition") or {}
    if not bool(condition_cfg.get("enabled", False)):
        return pd.Series(True, index=dates, dtype=bool)

    daily = weights.reindex(dates).ffill().fillna(0.0)
    metrics = _portfolio_stress_metrics(daily, start, end)
    if metrics.empty:
        return pd.Series(True, index=dates, dtype=bool)
    metrics = metrics.reindex(dates).fillna(0.0)

    mask = pd.Series(False, index=dates, dtype=bool)
    min_triggers = max(1, int(condition_cfg.get("min_triggers", 1)))
    trigger_count = pd.Series(0, index=dates, dtype=int)
    checks = [
        ("max_ret20", "ret20", ">="),
        ("max_vol20", "vol20", ">="),
        ("max_amount_chg20", "amount_chg20", ">="),
        ("max_turnover_rate", "turnover_rate", ">="),
        ("min_amount", "amount", "<="),
    ]
    for cfg_key, metric_col, op in checks:
        if condition_cfg.get(cfg_key) is None or metric_col not in metrics.columns:
            continue
        threshold = float(condition_cfg[cfg_key])
        if op == ">=":
            trigger = pd.to_numeric(metrics[metric_col], errors="coerce").fillna(0.0) >= threshold
        else:
            trigger = pd.to_numeric(metrics[metric_col], errors="coerce").fillna(0.0) <= threshold
        trigger_count += trigger.astype(int)
    mask |= trigger_count >= min_triggers

    states = {str(x) for x in condition_cfg.get("states", [])}
    if states:
        state_series = _market_state_series(dates, 5).reindex(dates, method="ffill").fillna("normal").astype(str)
        mask |= state_series.isin(states)
    return mask.astype(bool)


def _portfolio_stress_metrics(weights: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if weights.empty:
        return pd.DataFrame()
    active_codes = [str(c) for c in weights.columns if float(weights[c].abs().sum()) > 0]
    if not active_codes:
        return pd.DataFrame()
    start_warmup = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=220)).strftime("%Y%m%d")
    keys = pd.DataFrame({"ts_code": active_codes})
    with duckdb.connect() as conn:
        conn.register("target_codes", keys)
        metrics = conn.execute(
            f"""
            WITH daily_metrics AS (
              SELECT d.trade_date, d.ts_code,
                     d.amount * 1000 AS amount,
                     d.close / NULLIF(lag(d.close, 20) OVER w, 0) - 1 AS ret20,
                     stddev_pop(d.pct_chg / 100.0) OVER (
                       PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                     ) * sqrt(244.0) AS vol20,
                     d.amount / NULLIF(avg(d.amount) OVER (
                       PARTITION BY d.ts_code ORDER BY d.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                     ), 0) - 1 AS amount_chg20
              FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
              JOIN target_codes c ON d.ts_code = c.ts_code
              WHERE d.trade_date BETWEEN '{start_warmup}' AND '{end}'
              WINDOW w AS (PARTITION BY d.ts_code ORDER BY d.trade_date)
            )
            SELECT dm.trade_date, dm.ts_code, dm.amount, dm.ret20, dm.vol20, dm.amount_chg20,
                   db.turnover_rate
            FROM daily_metrics dm
            LEFT JOIN read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}') db
              ON dm.trade_date = db.trade_date AND dm.ts_code = db.ts_code
            WHERE dm.trade_date BETWEEN '{start}' AND '{end}'
            """
        ).fetchdf()
    if metrics.empty:
        return pd.DataFrame()
    metrics["trade_date"] = metrics["trade_date"].astype(str)
    metrics["ts_code"] = metrics["ts_code"].astype(str)
    out = pd.DataFrame(index=weights.index.astype(str), columns=["ret20", "vol20", "amount_chg20", "turnover_rate", "amount"], dtype="float64")
    for col in out.columns:
        pivot = metrics.pivot(index="trade_date", columns="ts_code", values=col).reindex(index=out.index, columns=weights.columns).fillna(0.0)
        numerator = (weights * pivot).sum(axis=1)
        denom = weights.where(pivot.notna(), 0.0).sum(axis=1).replace(0.0, np.nan)
        out[col] = (numerator / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def _apply_intramonth_crash_exit(weights: pd.DataFrame, start: str, end: str, cfg: StrategyConfig) -> pd.DataFrame:
    exit_cfg = (cfg.filters or {}).get("crash_exit") or {}
    if weights.empty or not bool(exit_cfg.get("enabled", False)):
        return weights

    dates = dq.get_trade_dates(start, end)
    if not dates:
        return weights
    dates = [date for date in dates if date >= str(weights.index.min()) and date <= end]
    if not dates:
        return weights

    states = _market_state_series(dates, int(exit_cfg.get("lookback_days", 5)))
    if states.empty:
        return weights
    states = states.reindex(dates, method="ffill").fillna("normal").astype(str)

    trigger_states = {str(x) for x in exit_cfg.get("trigger_states", ["crash"])}
    recovery_states = {str(x) for x in exit_cfg.get("recovery_states", ["liquidity_squeeze", "post_crash_repair", "normal"])}
    exit_exposure = float(exit_cfg.get("exit_exposure", 0.0))
    squeeze_exposure = exit_cfg.get("liquidity_squeeze_exposure")
    squeeze_exposure = float(squeeze_exposure) if squeeze_exposure is not None else None
    min_exit_days = max(0, int(exit_cfg.get("min_exit_days", 1)))
    max_exit_days = max(0, int(exit_cfg.get("max_exit_days", 8)))

    daily = weights.reindex(dates).ffill().fillna(0.0)
    out = daily.copy()
    in_exit = False
    exit_days = 0

    for date in dates:
        state = str(states.get(date) or "normal")
        if state in trigger_states:
            in_exit = True
            exit_days = 0

        if in_exit:
            can_recover = exit_days >= min_exit_days and state in recovery_states
            timed_out = max_exit_days > 0 and exit_days >= max_exit_days
            if can_recover or timed_out:
                in_exit = False
            else:
                exposure = exit_exposure
                if squeeze_exposure is not None and state == "liquidity_squeeze":
                    exposure = squeeze_exposure
                out.loc[date] = daily.loc[date] * exposure
                exit_days += 1

    return out.fillna(0.0)


def _weights_from_predictions(df: pd.DataFrame, date: str, cfg: StrategyConfig) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    p = cfg.position or {}
    n_hold = int(p.get("n_holdings", 30))
    max_weight = float(p.get("max_single_weight", 0.05))
    max_industry_weight = float(p.get("max_industry_weight", 0.25))
    max_per_industry = max(1, int(n_hold * max_industry_weight)) if max_industry_weight > 0 else n_hold
    ranked = df.dropna(subset=["pred_score"]).sort_values("pred_score", ascending=False)
    picked = []
    counts: dict[str, int] = {}
    for _, row in ranked.iterrows():
        industry = str(row.get("industry") or "")
        if counts.get(industry, 0) >= max_per_industry:
            continue
        picked.append(row)
        counts[industry] = counts.get(industry, 0) + 1
        if len(picked) >= n_hold:
            break
    if not picked:
        return pd.DataFrame()
    selected = pd.DataFrame(picked)
    raw = pd.to_numeric(selected["pred_score"], errors="coerce")
    raw = raw - raw.min() + 0.01
    raw = raw / raw.sum()
    raw = raw.clip(upper=max_weight)
    if raw.sum() > 0:
        raw = raw / raw.sum()
        raw = raw.clip(upper=max_weight)
    return pd.DataFrame([dict(zip(selected["ts_code"].astype(str), raw.astype(float)))], index=[date]).fillna(0.0)


def _market_exposure_map(dates: list[str], cfg: StrategyConfig) -> dict[str, float]:
    if not dates:
        return {}
    regime = (cfg.filters or {}).get("market_regime") or {}
    if not regime:
        return {date: 1.0 for date in dates}
    risk_state_exposures = _risk_state_exposure_map(dates, cfg)
    if risk_state_exposures and bool(regime.get("risk_state_only", False)):
        return risk_state_exposures
    trend_window = int(regime.get("trend_window", 60))
    breadth_window = int(regime.get("breadth_window", 20))
    min_breadth = float(regime.get("min_breadth", 0.45))
    normal_exposure = float(regime.get("normal_exposure", 1.0))
    weak_exposure = float(regime.get("weak_exposure", 0.50))
    bear_exposure = float(regime.get("bear_exposure", 0.25))
    continuous = bool(regime.get("continuous", False))
    crisis_guard = bool(regime.get("crisis_guard", False))
    crisis_exposure = float(regime.get("crisis_exposure", min(bear_exposure, 0.15)))
    crisis_drawdown = float(regime.get("crisis_drawdown", -0.12))
    crisis_short_return = float(regime.get("crisis_short_return", -0.06))
    crisis_breadth = float(regime.get("crisis_breadth", min_breadth * 0.75))
    drawdown_window = int(regime.get("drawdown_window", 120))
    volatility_window = int(regime.get("volatility_window", 20))
    pad_days = max(trend_window, breadth_window, drawdown_window, volatility_window) * 4
    start = (pd.to_datetime(min(dates), format="%Y%m%d") - pd.Timedelta(days=pad_days)).strftime("%Y%m%d")
    end = max(dates)
    data = dq.sql(
        f"""
        SELECT trade_date, ts_code, close, pct_chg
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date >= '{start}' AND trade_date <= '{end}'
        ORDER BY trade_date, ts_code
        """
    )
    if data.empty:
        return {date: 1.0 for date in dates}
    close = data.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    pct = data.pivot(index="trade_date", columns="ts_code", values="pct_chg").sort_index() / 100
    trend = close.mean(axis=1).pct_change(trend_window)
    breadth = pct.gt(0).mean(axis=1).rolling(breadth_window).mean()
    market_close = close.mean(axis=1)
    drawdown = market_close / market_close.rolling(drawdown_window).max() - 1.0
    short_return = market_close.pct_change(5)
    market_vol = pct.mean(axis=1).rolling(volatility_window).std() * np.sqrt(244.0)
    trend = trend.reindex(dates, method="ffill")
    breadth = breadth.reindex(dates, method="ffill")
    drawdown = drawdown.reindex(dates, method="ffill")
    short_return = short_return.reindex(dates, method="ffill")
    market_vol = market_vol.reindex(dates, method="ffill")
    out: dict[str, float] = {}
    for date in dates:
        market_trend = float(trend.get(date, np.nan))
        market_breadth = float(breadth.get(date, np.nan))
        market_drawdown = float(drawdown.get(date, np.nan))
        market_short_return = float(short_return.get(date, np.nan))
        market_volatility = float(market_vol.get(date, np.nan))
        if not np.isfinite(market_trend) or not np.isfinite(market_breadth):
            out[date] = 1.0
        elif continuous:
            trend_score = _clip01((market_trend + 0.12) / 0.18)
            breadth_floor = min_breadth * 0.6
            breadth_score = _clip01((market_breadth - breadth_floor) / max(0.01, 0.72 - breadth_floor))
            drawdown_score = _clip01((market_drawdown + 0.22) / 0.22) if np.isfinite(market_drawdown) else 0.5
            volatility_score = _clip01((0.28 - market_volatility) / 0.22) if np.isfinite(market_volatility) else 0.5
            health = 0.35 * trend_score + 0.35 * breadth_score + 0.20 * drawdown_score + 0.10 * volatility_score
            if health <= 0.5:
                exposure = bear_exposure + (weak_exposure - bear_exposure) * (health / 0.5)
            else:
                exposure = weak_exposure + (normal_exposure - weak_exposure) * ((health - 0.5) / 0.5)
            out[date] = float(np.clip(exposure, min(bear_exposure, normal_exposure), max(bear_exposure, normal_exposure)))
        elif market_trend < -0.06 and market_breadth < min_breadth * 0.8:
            out[date] = bear_exposure
        elif market_trend < 0 or market_breadth < min_breadth:
            out[date] = weak_exposure
        else:
            out[date] = normal_exposure
        if (
            crisis_guard
            and np.isfinite(market_drawdown)
            and np.isfinite(market_short_return)
            and (
                market_drawdown <= crisis_drawdown
                or (market_short_return <= crisis_short_return and market_breadth <= crisis_breadth)
            )
        ):
            out[date] = min(out[date], crisis_exposure)
        if risk_state_exposures:
            out[date] = min(out[date], risk_state_exposures.get(date, 1.0))
    return out


def _apply_daily_exposure_overlay(weights: pd.DataFrame, start: str, end: str, cfg: StrategyConfig) -> pd.DataFrame:
    if weights.empty:
        return weights
    dates = dq.get_trade_dates(start, end)
    if not dates:
        return weights
    dates = [date for date in dates if date >= str(weights.index.min()) and date <= end]
    if not dates:
        return weights
    daily = weights.reindex(dates).ffill().fillna(0.0)
    exposures = _market_exposure_map(dates, cfg)
    exposure_series = pd.Series({date: exposures.get(date, 1.0) for date in dates}, dtype="float64")
    return daily.mul(exposure_series, axis=0).fillna(0.0)


def _risk_state_exposure_map(dates: list[str], cfg: StrategyConfig) -> dict[str, float]:
    if not dates:
        return {}
    regime = (cfg.filters or {}).get("market_regime") or {}
    risk_cfg = regime.get("risk_state") or {}
    if not risk_cfg or not bool(risk_cfg.get("enabled", False)):
        return {}
    exposures = {
        "normal": float(risk_cfg.get("normal_exposure", 1.0)),
        "weak": float(risk_cfg.get("weak_exposure", regime.get("weak_exposure", 0.45))),
        "post_crash_repair": float(risk_cfg.get("post_crash_repair_exposure", 0.35)),
        "liquidity_squeeze": float(risk_cfg.get("liquidity_squeeze_exposure", 0.10)),
        "crash": float(risk_cfg.get("crash_exposure", 0.05)),
    }
    db_path = os.getenv("DESKTOP_DB_PATH") or str(DATA_ROOT / "meta.db")
    try:
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """
                SELECT trade_date, state
                FROM market_risk_state_daily
                WHERE trade_date BETWEEN ? AND ?
                ORDER BY trade_date
                """,
                (min(dates), max(dates)),
            ).fetchall()
    except Exception:
        return {}
    if not rows:
        return {}
    state_series = pd.Series({str(date): str(state) for date, state in rows})
    state_series = state_series.reindex(dates, method="ffill")
    return {date: exposures.get(str(state_series.get(date) or "normal"), 1.0) for date in dates}


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _quote(values: list[str]) -> str:
    if not values:
        return "''"
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


@register("ml_factor_ranker", "机器学习因子")
def build_strategy():
    return MLFactorRankerStrategy(StrategyConfig.from_yaml("ml_factor_ranker"))
