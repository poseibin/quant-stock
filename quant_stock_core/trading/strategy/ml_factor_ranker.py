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
        preds = _apply_universe(preds, self.cfg)
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
    with duckdb.connect() as conn:
        conn.register("pred_keys", keys)
        info = conn.execute(
            f"""
            SELECT k.trade_date, k.ts_code,
                   sb.name, sb.industry,
                   db.total_mv * 10000 AS total_mv,
                   db.circ_mv * 10000 AS circ_mv,
                   db.turnover_rate,
                   d.amount * 1000 AS amount,
                   d.pct_chg / 100.0 AS pct_chg
            FROM pred_keys k
            LEFT JOIN read_parquet('{dq.RAW_DIR / "stock_basic" / "data.parquet"}') sb
              ON k.ts_code = sb.ts_code
            LEFT JOIN read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}') db
              ON k.trade_date = db.trade_date AND k.ts_code = db.ts_code
            LEFT JOIN read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
              ON k.trade_date = d.trade_date AND k.ts_code = d.ts_code
            """
        ).fetchdf()
    out = preds.merge(info, on=["trade_date", "ts_code"], how="left")
    return out.replace([np.inf, -np.inf], np.nan)


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
