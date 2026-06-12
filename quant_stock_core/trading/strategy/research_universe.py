"""Independent research strategy universe.

The desktop-facing strategies in this module are implemented as first-class
research rules.  They share a compact factor engine, but each strategy owns its
own filters, scoring weights, rebalance style, and capacity limits.

Design principles:
- use only information available on or before the rebalance date;
- prefer robust ranks and broad filters over brittle single thresholds;
- keep event strategies as low-capacity satellite sleeves;
- make rules parameterized so the evaluation loop can optimize ranges later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import numpy as np
import pandas as pd

from common.utils.market import bj_include_sql, restricted_exclude_sql
from research.data.storage import duckdb_query as dq
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register


def _quote(items: list[str]) -> str:
    return ",".join(f"'{item}'" for item in items)


def _pad_date(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")


def _rank(series: pd.Series, *, high_good: bool = True) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if values.notna().sum() <= 1:
        return pd.Series(0.5, index=series.index)
    return values.rank(pct=True, ascending=not high_good).fillna(0.5)


def _winsor(series: pd.Series, lower: float = 0.02, upper: float = 0.98) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if values.notna().sum() < 5:
        return values
    return values.clip(values.quantile(lower), values.quantile(upper))


def _num_col(df: pd.DataFrame, name: str, default: float = np.nan) -> pd.Series:
    if name not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[name], errors="coerce")


def _market_cutoff(date: str, min_listed_days: int) -> str:
    return _pad_date(date, int(min_listed_days * 1.45))


def _latest_by_ann(table: str, date: str, columns: list[str]) -> pd.DataFrame:
    select = ["ts_code", "ann_date"] + columns
    return dq.sql(f"""
        SELECT {", ".join(select)}
        FROM (
            SELECT {", ".join(select)},
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY ann_date DESC, end_date DESC) AS rn
            FROM read_parquet('{dq.RAW_DIR / table / "*.parquet"}')
            WHERE ann_date IS NOT NULL AND ann_date <= '{date}'
        )
        WHERE rn = 1
    """)


def _recent_event_count(table: str, date: str, days: int, where: str = "1=1", value_expr: str = "1") -> pd.DataFrame:
    start = _pad_date(date, days)
    return dq.sql(f"""
        SELECT ts_code, COUNT(*) AS event_count, SUM({value_expr}) AS event_value
        FROM read_parquet('{dq.RAW_DIR / table / "*.parquet"}')
        WHERE ann_date >= '{start}' AND ann_date <= '{date}' AND {where}
        GROUP BY ts_code
    """)


def _feature_frame(date: str, cfg: StrategyConfig, *, bj_only: bool = False) -> pd.DataFrame:
    u = cfg.universe or {}
    min_listed_days = int(u.get("min_listed_days", 250 if not bj_only else 120))
    min_amount = float(u.get("min_avg_amount", 20_000_000 if not bj_only else 5_000_000))
    max_amount_spike = float(u.get("max_amount_spike", 5.0))
    price_start = _pad_date(date, 260)

    stock_where = [
        "list_status = 'L'",
        f"list_date <= '{_market_cutoff(date, min_listed_days)}'",
    ]
    if bj_only:
        stock_where.append(bj_include_sql())
    else:
        stock_where.append(restricted_exclude_sql())
    stock = dq.sql(f"""
        SELECT ts_code, name, industry, exchange, list_date
        FROM read_parquet('{dq.RAW_DIR / "stock_basic" / "data.parquet"}')
        WHERE {" AND ".join(stock_where)}
    """)
    if stock.empty:
        return pd.DataFrame()

    codes = sorted(stock["ts_code"].astype(str).unique())
    code_sql = _quote(codes)
    basic = dq.sql(f"""
        SELECT *
        FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
        WHERE trade_date = '{date}' AND ts_code IN ({code_sql})
    """)
    if basic.empty:
        return pd.DataFrame()

    price = dq.sql(f"""
        SELECT d.trade_date, d.ts_code, d.close, d.pct_chg, d.amount, d.vol,
               COALESCE(a.adj_factor, 1.0) AS adj_factor
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
        LEFT JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
          ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
        WHERE d.trade_date >= '{price_start}' AND d.trade_date <= '{date}'
          AND d.ts_code IN ({code_sql})
        ORDER BY d.trade_date, d.ts_code
    """)
    if price.empty:
        return pd.DataFrame()

    price["adj_close"] = price["close"] * price["adj_factor"]
    close = price.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
    amount = price.pivot(index="trade_date", columns="ts_code", values="amount").sort_index() * 1000
    pct = price.pivot(index="trade_date", columns="ts_code", values="pct_chg").sort_index() / 100.0

    latest = pd.DataFrame(index=close.columns)
    latest["ret_5"] = close.pct_change(5).iloc[-1]
    latest["ret_20"] = close.pct_change(20).iloc[-1]
    latest["ret_60"] = close.pct_change(60).iloc[-1]
    latest["ret_120"] = close.pct_change(120).iloc[-1]
    latest["vol_20"] = pct.tail(20).std()
    latest["vol_60"] = pct.tail(60).std()
    latest["avg_amount_20"] = amount.tail(20).mean()
    latest["amount_spike"] = amount.iloc[-1] / amount.tail(20).mean().replace(0, np.nan)
    latest["dist_20_high"] = close.iloc[-1] / close.tail(20).max() - 1.0
    latest["pullback_20"] = close.iloc[-1] / close.tail(20).max() - 1.0
    latest["breadth_20"] = pct.tail(20).gt(0).mean()

    out = basic.merge(stock, on="ts_code", how="inner").merge(latest.reset_index().rename(columns={"index": "ts_code"}), on="ts_code", how="left")
    out["total_mv_yuan"] = pd.to_numeric(out.get("total_mv"), errors="coerce") * 10_000
    out["circ_mv_yuan"] = pd.to_numeric(out.get("circ_mv"), errors="coerce") * 10_000

    fi = _latest_by_ann(
        "fina_indicator",
        date,
        [
            "roe",
            "roe_dt",
            "q_roe",
            "roic",
            "grossprofit_margin",
            "netprofit_margin",
            "netprofit_yoy",
            "or_yoy",
            "tr_yoy",
            "q_sales_yoy",
            "q_op_qoq",
            "q_ocf_to_sales",
            "ocfps",
            "debt_to_assets",
            "ocf_yoy",
        ],
    )
    if not fi.empty:
        out = out.merge(fi.drop(columns=["ann_date"], errors="ignore"), on="ts_code", how="left")

    income = _latest_by_ann("income", date, ["n_income_attr_p", "total_revenue"])
    cash = _latest_by_ann("cashflow", date, ["im_net_cashflow_oper_act", "free_cashflow"])
    if not income.empty:
        out = out.merge(income.drop(columns=["ann_date"], errors="ignore"), on="ts_code", how="left")
    if not cash.empty:
        out = out.merge(cash.drop(columns=["ann_date"], errors="ignore"), on="ts_code", how="left")
    if "im_net_cashflow_oper_act" in out.columns and "n_income_attr_p" in out.columns:
        out["cfo_to_np"] = pd.to_numeric(out["im_net_cashflow_oper_act"], errors="coerce") / pd.to_numeric(out["n_income_attr_p"], errors="coerce").replace(0, np.nan)

    forecast = dq.sql(f"""
        SELECT ts_code,
               MAX(ann_date) AS forecast_ann_date,
               MAX(COALESCE(p_change_min, p_change_max, 0)) AS forecast_growth,
               MAX(COALESCE(net_profit_min, net_profit_max, 0)) AS forecast_profit
        FROM read_parquet('{dq.RAW_DIR / "forecast" / "*.parquet"}')
        WHERE ann_date >= '{_pad_date(date, 120)}' AND ann_date <= '{date}'
        GROUP BY ts_code
    """)
    if not forecast.empty:
        out = out.merge(forecast, on="ts_code", how="left")

    top = dq.sql(f"""
        SELECT ts_code,
               COUNT(*) AS lhb_count,
               SUM(COALESCE(net_amount, 0)) AS lhb_net_amount,
               AVG(COALESCE(amount_rate, 0)) AS lhb_amount_rate
        FROM read_parquet('{dq.RAW_DIR / "top_list" / "*.parquet"}')
        WHERE trade_date >= '{_pad_date(date, 30)}' AND trade_date <= '{date}'
        GROUP BY ts_code
    """)
    if not top.empty:
        out = out.merge(top, on="ts_code", how="left")

    inst = dq.sql(f"""
        SELECT ts_code, SUM(COALESCE(net_buy, 0)) AS inst_net_buy
        FROM read_parquet('{dq.RAW_DIR / "top_inst" / "*.parquet"}')
        WHERE trade_date >= '{_pad_date(date, 30)}' AND trade_date <= '{date}'
        GROUP BY ts_code
    """)
    if not inst.empty:
        out = out.merge(inst, on="ts_code", how="left")

    holder = _recent_event_count("stk_holdertrade", date, 180, "in_de = 'IN'", "COALESCE(change_vol, 0) * COALESCE(avg_price, 0)")
    if not holder.empty:
        out = out.merge(holder.rename(columns={"event_count": "holder_buy_count", "event_value": "holder_buy_value"}), on="ts_code", how="left")

    out = out[~out["name"].fillna("").str.contains("ST", na=False)].copy()
    out = out[pd.to_numeric(out["avg_amount_20"], errors="coerce").fillna(0) >= min_amount]
    if max_amount_spike > 0:
        out = out[pd.to_numeric(out["amount_spike"], errors="coerce").fillna(0) <= max_amount_spike]
    if u.get("min_total_mv") is not None:
        out = out[out["total_mv_yuan"] >= float(u["min_total_mv"])]
    if u.get("max_total_mv") is not None:
        out = out[out["total_mv_yuan"] <= float(u["max_total_mv"])]
    if u.get("min_circ_mv") is not None:
        out = out[out["circ_mv_yuan"] >= float(u["min_circ_mv"])]
    if u.get("max_circ_mv") is not None:
        out = out[out["circ_mv_yuan"] <= float(u["max_circ_mv"])]
    if u.get("max_20d_return") is not None:
        out = out[pd.to_numeric(out["ret_20"], errors="coerce").fillna(0) <= float(u["max_20d_return"])]
    return out.replace([np.inf, -np.inf], np.nan)


def _score(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    score = pd.Series(0.0, index=df.index)
    total = 0.0
    for key, weight in weights.items():
        if key not in df.columns or weight == 0:
            continue
        high_good = weight > 0
        score = score + _rank(_winsor(df[key]), high_good=high_good) * abs(float(weight))
        total += abs(float(weight))
    return score / total if total > 0 else pd.Series(0.0, index=df.index)


def _weights_from_scores(df: pd.DataFrame, date: str, cfg: StrategyConfig, scores: pd.Series) -> pd.DataFrame:
    if df.empty or scores.empty:
        return pd.DataFrame()
    p = cfg.position or {}
    n_hold = int(p.get("n_holdings", p.get("max_active_events", 20)))
    max_weight = float(p.get("max_single_weight", 0.05))
    min_score = float((cfg.selection or {}).get("min_score", 0.0))
    ranked = df.assign(_score=scores).dropna(subset=["_score"]).sort_values("_score", ascending=False)
    if min_score > 0:
        ranked = ranked[ranked["_score"] >= min_score]
    if ranked.empty:
        return pd.DataFrame()
    if p.get("max_industry_weight"):
        max_per_industry = max(1, int(n_hold * float(p["max_industry_weight"])))
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
        ranked = pd.DataFrame(picked)
    else:
        ranked = ranked.head(n_hold)
    if ranked.empty:
        return pd.DataFrame()
    raw = pd.to_numeric(ranked["_score"], errors="coerce").clip(lower=0.01)
    raw = raw / raw.sum()
    raw = raw.clip(upper=max_weight)
    total = raw.sum()
    if total > 0:
        raw = raw / total
        raw = raw.clip(upper=max_weight)
    return pd.DataFrame([dict(zip(ranked["ts_code"].astype(str), raw.astype(float)))], index=[date]).fillna(0.0)


_MARKET_EXPOSURE_CACHE: dict[tuple, float] = {}


def _market_exposure(date: str, cfg: StrategyConfig) -> float:
    regime = (cfg.filters or {}).get("market_regime") or {}
    if not regime:
        return 1.0
    trend_window = int(regime.get("trend_window", 60))
    breadth_window = int(regime.get("breadth_window", 20))
    cache_key = (
        date,
        trend_window,
        breadth_window,
        float(regime.get("min_breadth", 0.45)),
        float(regime.get("normal_exposure", 1.0)),
        float(regime.get("weak_exposure", 0.50)),
        float(regime.get("bear_exposure", 0.25)),
    )
    if cache_key in _MARKET_EXPOSURE_CACHE:
        return _MARKET_EXPOSURE_CACHE[cache_key]
    price_start = _pad_date(date, max(trend_window, breadth_window) * 3)
    data = dq.sql(f"""
        SELECT trade_date, ts_code, close, pct_chg
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date >= '{price_start}' AND trade_date <= '{date}'
        ORDER BY trade_date, ts_code
    """)
    if data.empty:
        return 1.0
    close = data.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    pct = data.pivot(index="trade_date", columns="ts_code", values="pct_chg").sort_index() / 100
    if len(close) <= trend_window:
        return 1.0
    market_trend = close.mean(axis=1).pct_change(trend_window).iloc[-1]
    breadth = pct.tail(breadth_window).gt(0).mean(axis=1).mean()
    if market_trend < -0.06 and breadth < float(regime.get("min_breadth", 0.45)) * 0.8:
        exposure = float(regime.get("bear_exposure", 0.25))
        _MARKET_EXPOSURE_CACHE[cache_key] = exposure
        return exposure
    if market_trend < 0 or breadth < float(regime.get("min_breadth", 0.45)):
        exposure = float(regime.get("weak_exposure", 0.50))
        _MARKET_EXPOSURE_CACHE[cache_key] = exposure
        return exposure
    exposure = float(regime.get("normal_exposure", 1.0))
    _MARKET_EXPOSURE_CACHE[cache_key] = exposure
    return exposure


@dataclass
class RuleBook:
    weights: dict[str, float]
    pre_filter: Callable[[pd.DataFrame, StrategyConfig], pd.DataFrame] | None = None
    bj_only: bool = False
    exposure_filter: bool = False


class QuantFactorStrategy(BaseStrategy):
    rule: RuleBook

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        frames = []
        rebalance = "weekly" if self.cfg.rebalance == "event" else self.cfg.rebalance
        for date in get_rebalance_dates(start, end, rebalance):
            df = _feature_frame(date, self.cfg, bj_only=self.rule.bj_only)
            if df.empty:
                continue
            if self.rule.pre_filter:
                df = self.rule.pre_filter(df, self.cfg)
            if df.empty:
                continue
            scores = _score(df, self.rule.weights)
            weights = _weights_from_scores(df, date, self.cfg, scores)
            if not weights.empty and self.rule.exposure_filter:
                weights = weights * _market_exposure(date, self.cfg)
            if not weights.empty:
                frames.append(weights)
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames).sort_index()
        return out.reindex(columns=sorted(out.columns)).fillna(0.0)


def _quality_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = df.copy()
    if f.get("min_roe") is not None:
        out = out[_num_col(out, "roe").fillna(-999) >= float(f["min_roe"]) * 100]
    if f.get("min_roe_ttm") is not None:
        out = out[_num_col(out, "roe").fillna(-999) >= float(f["min_roe_ttm"]) * 100]
    if f.get("max_debt_ratio") is not None:
        out = out[_num_col(out, "debt_to_assets").fillna(999) <= float(f["max_debt_ratio"]) * 100]
    return out


def _trend_pullback_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = _quality_filter(df, cfg)
    out = out[_num_col(out, "ret_60").fillna(-999) >= float(f.get("min_mid_return", 0.06))]
    out = out[_num_col(out, "ret_20").fillna(999) <= float(f.get("max_short_return", 0.18))]
    out = out[_num_col(out, "pullback_20").fillna(-999).between(-0.18, -0.02)]
    return out


def _dividend_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = _quality_filter(df, cfg)
    out = out[_num_col(out, "dv_ttm").fillna(0) >= float(f.get("min_dv_ttm", 2.0))]
    out = out[_num_col(out, "pb").fillna(999) <= float(f.get("max_pb", 3.0))]
    return out


def _earnings_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    growth = _num_col(df, "forecast_growth").fillna(_num_col(df, "netprofit_yoy"))
    out = df[growth >= float(f.get("min_profit_growth", 25.0))].copy()
    out = out[_num_col(out, "ret_20").fillna(999) <= float(f.get("max_post_ann_return", 0.15))]
    return out


def _event_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    event_score = (
        _num_col(df, "forecast_growth").fillna(0) / 100
        + _num_col(df, "lhb_net_amount").fillna(0) / 100_000_000
        + _num_col(df, "inst_net_buy").fillna(0) / 100_000_000
        + _num_col(df, "holder_buy_value").fillna(0) / 100_000_000
    )
    out = df[event_score > 0.25].copy()
    out["event_strength"] = event_score.loc[out.index]
    return out


def _rank_score(df: pd.DataFrame, columns: dict[str, bool]) -> pd.Series:
    parts = []
    for col, high_good in columns.items():
        if col in df.columns:
            parts.append(_rank(_winsor(df[col]), high_good=high_good))
    if not parts:
        return pd.Series(0.5, index=df.index)
    return pd.concat(parts, axis=1).mean(axis=1).fillna(0.5)


def _momentum_quality_guard_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = df.copy()
    out["quality_guard_score"] = _rank_score(
        out,
        {
            "roe": True,
            "roe_dt": True,
            "roic": True,
            "grossprofit_margin": True,
            "netprofit_margin": True,
            "debt_to_assets": False,
            "q_ocf_to_sales": True,
            "ocfps": True,
        },
    )
    out["momentum_score"] = _rank_score(out, {"ret_60": True, "ret_120": True})
    out["value_guard_score"] = _rank_score(out, {"pb": False, "ps_ttm": False, "pe_ttm": False, "dv_ttm": True})
    out = out[out["momentum_score"] >= float(f.get("min_momentum_score", 0.75))]
    out = out[out["quality_guard_score"] >= float(f.get("min_quality_score", 0.55))]
    out = out[_num_col(out, "ret_20").fillna(999) <= float(f.get("max_short_return", 0.30))]
    out = out[_num_col(out, "debt_to_assets").fillna(999) <= float(f.get("max_debt_ratio", 0.75)) * 100]
    if f.get("min_value_guard_score") is not None:
        out = out[out["value_guard_score"] >= float(f["min_value_guard_score"])]
    return out


def _quality_growth_cooldown_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = df.copy()
    out["quality_guard_score"] = _rank_score(
        out,
        {
            "roe": True,
            "roe_dt": True,
            "roic": True,
            "grossprofit_margin": True,
            "netprofit_margin": True,
            "debt_to_assets": False,
            "q_ocf_to_sales": True,
            "ocfps": True,
        },
    )
    out["growth_score"] = _rank_score(
        out,
        {"q_sales_yoy": True, "q_op_qoq": True, "netprofit_yoy": True, "tr_yoy": True, "or_yoy": True},
    )
    out["cooldown_score"] = _rank_score(out, {"vol_20": False, "turnover_rate": False})
    out["value_guard_score"] = _rank_score(out, {"pb": False, "ps_ttm": False, "pe_ttm": False, "dv_ttm": True})
    out = out[out["quality_guard_score"] >= float(f.get("min_quality_score", 0.70))]
    out = out[out["growth_score"] >= float(f.get("min_growth_score", 0.65))]
    out = out[_num_col(out, "ret_20").fillna(999) <= float(f.get("max_short_return", 0.25))]
    out = out[_num_col(out, "vol_20").fillna(999) <= float(f.get("max_vol_20", 0.70))]
    out = out[_num_col(out, "debt_to_assets").fillna(999) <= float(f.get("max_debt_ratio", 0.75)) * 100]
    if f.get("min_value_guard_score") is not None:
        out = out[out["value_guard_score"] >= float(f["min_value_guard_score"])]
    return out


class MarketRegimeTiming(QuantFactorStrategy):
    rule = RuleBook(
        weights={"ret_60": 0.22, "ret_20": -0.10, "roe": 0.20, "pb": -0.15, "vol_60": -0.18, "avg_amount_20": 0.10, "netprofit_yoy": 0.15},
        pre_filter=_quality_filter,
        exposure_filter=True,
    )


class MultiFactorComposite(QuantFactorStrategy):
    rule = RuleBook(
        weights={"roe": 0.18, "netprofit_yoy": 0.16, "pb": -0.14, "pe_ttm": -0.08, "ret_60": 0.18, "ret_20": -0.06, "vol_60": -0.12, "circ_mv_yuan": -0.08, "avg_amount_20": 0.10},
        pre_filter=_quality_filter,
    )


class MomentumQualityGuard(QuantFactorStrategy):
    rule = RuleBook(
        weights={
            "momentum_score": 0.30,
            "quality_guard_score": 0.24,
            "ret_120": 0.16,
            "ret_20": -0.10,
            "vol_20": -0.08,
            "debt_to_assets": -0.06,
            "value_guard_score": 0.06,
        },
        pre_filter=_momentum_quality_guard_filter,
        exposure_filter=True,
    )


class QualityGrowthCooldown(QuantFactorStrategy):
    rule = RuleBook(
        weights={
            "quality_guard_score": 0.30,
            "growth_score": 0.24,
            "cooldown_score": 0.16,
            "ret_60": 0.12,
            "value_guard_score": 0.10,
            "ret_20": -0.08,
        },
        pre_filter=_quality_growth_cooldown_filter,
        exposure_filter=True,
    )


class ResearchSmallCapQuality(QuantFactorStrategy):
    rule = RuleBook(
        weights={"circ_mv_yuan": -0.28, "pb": -0.18, "roe": 0.18, "cfo_to_np": 0.12, "ret_20": 0.12, "vol_20": -0.12},
        pre_filter=_quality_filter,
    )


class TrendPullback(QuantFactorStrategy):
    rule = RuleBook(
        weights={"ret_120": 0.22, "ret_60": 0.24, "pullback_20": -0.16, "vol_20": -0.12, "roe": 0.14, "avg_amount_20": 0.12},
        pre_filter=_trend_pullback_filter,
    )


class TurtleBreakout(BaseStrategy):
    """海龟突破策略。

    用纯价格系统补足现有因子策略：N 日突破入场、ATR 波动率定仓、
    0.5 ATR 金字塔加仓、跌破退出通道或 2 ATR 硬止损清仓。
    """

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        cfg = self.cfg
        f = cfg.filters or {}
        p = cfg.position or {}
        entry_window = int(f.get("entry_window", 55))
        exit_window = int(f.get("exit_window", 20))
        atr_window = int(f.get("atr_window", 20))
        trend_window = int(f.get("trend_window", 120))
        min_avg_amount = float((cfg.universe or {}).get("min_avg_amount", 50_000_000))
        min_total_mv = (cfg.universe or {}).get("min_total_mv")
        max_total_mv = (cfg.universe or {}).get("max_total_mv")
        max_20d_return = (cfg.universe or {}).get("max_20d_return", f.get("max_20d_return", 0.45))
        max_amount_spike = float((cfg.universe or {}).get("max_amount_spike", 5.0))
        n_holdings = int(p.get("n_holdings", 20))
        max_units = int(p.get("max_units", 4))
        add_atr_step = float(p.get("add_atr_step", 0.5))
        stop_atr = float(p.get("stop_atr", 2.0))
        risk_per_unit = float(p.get("risk_per_unit", 0.006))
        max_unit_weight = float(p.get("max_unit_weight", 0.02))
        max_single_weight = float(p.get("max_single_weight", 0.06))
        max_total_exposure = float(p.get("max_total_exposure", 1.0))

        data = self._load_price_data(
            start,
            end,
            lookback=max(entry_window, exit_window, atr_window, trend_window) + 80,
        )
        if data.empty:
            return pd.DataFrame()

        close = data.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
        high = data.pivot(index="trade_date", columns="ts_code", values="adj_high").sort_index()
        low = data.pivot(index="trade_date", columns="ts_code", values="adj_low").sort_index()
        amount = data.pivot(index="trade_date", columns="ts_code", values="amount_yuan").sort_index()
        total_mv = data.pivot(index="trade_date", columns="ts_code", values="total_mv_yuan").sort_index()
        list_date = data.sort_values("trade_date").groupby("ts_code")["list_date"].last().astype(str).to_dict()

        entry_high = close.rolling(entry_window, min_periods=entry_window).max().shift(1)
        exit_low = close.rolling(exit_window, min_periods=exit_window).min().shift(1)
        atr_pct = self._atr_pct(high, low, close, atr_window)
        avg_amount = amount.rolling(20, min_periods=10).mean()
        amount_spike = amount / avg_amount.replace(0, np.nan)
        ret_20 = close.pct_change(20)
        ret_trend = close.pct_change(trend_window)

        start_dates = [d for d in close.index.astype(str).tolist() if start <= d <= end]
        min_listed_days = int((cfg.universe or {}).get("min_listed_days", 260))
        positions: dict[str, dict[str, float]] = {}
        rows: list[pd.Series] = []
        known_codes: set[str] = set()

        for date in start_dates:
            if date not in close.index:
                continue
            current = close.loc[date]
            current_atr = atr_pct.loc[date]

            for code in list(positions.keys()):
                cur = current.get(code)
                atr = current_atr.get(code)
                if pd.isna(cur) or pd.isna(atr) or atr <= 0:
                    del positions[code]
                    continue
                stop_price = float(positions[code]["last_add_price"]) * (1.0 - stop_atr * float(atr))
                exit_price = exit_low.loc[date].get(code)
                if (not pd.isna(exit_price) and cur <= exit_price) or cur <= stop_price:
                    del positions[code]
                    continue
                while (
                    int(positions[code]["units"]) < max_units
                    and cur >= float(positions[code]["last_add_price"]) * (1.0 + add_atr_step * float(atr))
                ):
                    positions[code]["units"] += 1
                    positions[code]["last_add_price"] = float(cur)

            room = max(0, n_holdings - len(positions))
            if room > 0:
                candidates = self._entry_candidates(
                    date,
                    current,
                    entry_high.loc[date],
                    atr_pct.loc[date],
                    avg_amount.loc[date],
                    amount_spike.loc[date],
                    ret_20.loc[date],
                    ret_trend.loc[date],
                    total_mv.loc[date],
                    list_date,
                    min_listed_days=min_listed_days,
                    min_avg_amount=min_avg_amount,
                    min_total_mv=min_total_mv,
                    max_total_mv=max_total_mv,
                    max_20d_return=max_20d_return,
                    max_amount_spike=max_amount_spike,
                    exclude=set(positions),
                )
                for code in candidates[:room]:
                    cur = current.get(code)
                    if not pd.isna(cur):
                        positions[code] = {"units": 1.0, "last_add_price": float(cur)}

            row = self._position_row(positions, current_atr, max_units, risk_per_unit, max_unit_weight, max_single_weight)
            if row.empty:
                if not known_codes:
                    continue
                row = pd.Series({code: 0.0 for code in known_codes}, dtype=float)
            else:
                known_codes.update(row.index.astype(str))
                total = float(row.sum())
                if total > max_total_exposure > 0:
                    row = row * (max_total_exposure / total)
            row.name = date
            rows.append(row)

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_index().fillna(0.0)

    @staticmethod
    def _load_price_data(start: str, end: str, *, lookback: int) -> pd.DataFrame:
        pad = _pad_date(start, lookback * 2)
        return dq.sql(f"""
            SELECT d.trade_date, d.ts_code,
                   d.high * COALESCE(a.adj_factor, 1.0) AS adj_high,
                   d.low * COALESCE(a.adj_factor, 1.0) AS adj_low,
                   d.close * COALESCE(a.adj_factor, 1.0) AS adj_close,
                   d.amount * 1000 AS amount_yuan,
                   db.total_mv * 10000 AS total_mv_yuan,
                   sb.list_date
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
            LEFT JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            LEFT JOIN read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}') db
              ON d.ts_code = db.ts_code AND d.trade_date = db.trade_date
            JOIN read_parquet('{dq.RAW_DIR / "stock_basic" / "*.parquet"}') sb
              ON d.ts_code = sb.ts_code
            WHERE d.trade_date >= '{pad}' AND d.trade_date <= '{end}'
              AND COALESCE(sb.list_status, 'L') = 'L'
              AND COALESCE(sb.name, '') NOT LIKE '%ST%'
              AND {restricted_exclude_sql('sb')}
              AND d.close > 0 AND d.high > 0 AND d.low > 0
        """)

    @staticmethod
    def _atr_pct(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, window: int) -> pd.DataFrame:
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).stack(),
                (high - prev_close).abs().stack(),
                (low - prev_close).abs().stack(),
            ],
            axis=1,
        ).max(axis=1).unstack()
        atr = tr.rolling(window, min_periods=max(5, window // 2)).mean()
        return atr / close.replace(0, np.nan)

    @staticmethod
    def _entry_candidates(
        date: str,
        close: pd.Series,
        entry_high: pd.Series,
        atr_pct: pd.Series,
        avg_amount: pd.Series,
        amount_spike: pd.Series,
        ret_20: pd.Series,
        ret_trend: pd.Series,
        total_mv: pd.Series,
        list_date: dict[str, str],
        *,
        min_listed_days: int,
        min_avg_amount: float,
        min_total_mv,
        max_total_mv,
        max_20d_return,
        max_amount_spike: float,
        exclude: set[str],
    ) -> list[str]:
        df = pd.DataFrame({
            "close": close,
            "entry_high": entry_high,
            "atr_pct": atr_pct,
            "avg_amount": avg_amount,
            "amount_spike": amount_spike,
            "ret_20": ret_20,
            "ret_trend": ret_trend,
            "total_mv": total_mv,
        }).dropna(subset=["close", "entry_high", "atr_pct", "avg_amount"])
        if df.empty:
            return []
        cutoff = _market_cutoff(date, min_listed_days)
        df = df[
            (df["close"] > df["entry_high"])
            & (df["atr_pct"] > 0)
            & (df["avg_amount"] >= min_avg_amount)
            & (df["amount_spike"].fillna(0) <= max_amount_spike)
        ]
        if max_20d_return is not None:
            df = df[df["ret_20"].fillna(0) <= float(max_20d_return)]
        if min_total_mv is not None:
            df = df[df["total_mv"].fillna(0) >= float(min_total_mv)]
        if max_total_mv is not None:
            df = df[df["total_mv"].fillna(float("inf")) <= float(max_total_mv)]
        if exclude:
            df = df[~df.index.isin(exclude)]
        if df.empty:
            return []
        listed_ok = pd.Series({code: str(list_date.get(code, "")) <= cutoff for code in df.index})
        df = df[listed_ok.reindex(df.index).fillna(False)]
        if df.empty:
            return []
        df["breakout_strength"] = df["close"] / df["entry_high"] - 1.0
        df["score"] = (
            _rank(df["breakout_strength"], high_good=True) * 0.35
            + _rank(df["ret_trend"], high_good=True) * 0.30
            + _rank(df["avg_amount"], high_good=True) * 0.20
            + _rank(df["atr_pct"], high_good=False) * 0.15
        )
        return df.sort_values(["score", "breakout_strength"], ascending=False).index.astype(str).tolist()

    @staticmethod
    def _position_row(
        positions: dict[str, dict[str, float]],
        atr_pct: pd.Series,
        max_units: int,
        risk_per_unit: float,
        max_unit_weight: float,
        max_single_weight: float,
    ) -> pd.Series:
        weights: dict[str, float] = {}
        for code, state in positions.items():
            atr = atr_pct.get(code)
            if pd.isna(atr) or atr <= 0:
                continue
            unit_weight = min(max_unit_weight, risk_per_unit / max(float(atr), 1e-6))
            units = min(max_units, int(state.get("units", 1)))
            weights[code] = min(max_single_weight, unit_weight * units)
        return pd.Series(weights, dtype=float)


class DividendQuality(QuantFactorStrategy):
    rule = RuleBook(
        weights={"dv_ttm": 0.26, "vol_60": -0.20, "pb": -0.16, "roe": 0.16, "cfo_to_np": 0.12, "debt_to_assets": -0.10},
        pre_filter=_dividend_filter,
    )


class EarningsRevision(QuantFactorStrategy):
    rule = RuleBook(
        weights={"forecast_growth": 0.28, "forecast_profit": 0.14, "netprofit_yoy": 0.16, "ret_20": -0.12, "avg_amount_20": 0.12, "roe": 0.10, "pb": -0.08},
        pre_filter=_earnings_filter,
    )


class IndustryProsperity(QuantFactorStrategy):
    rule = RuleBook(
        weights={"ret_60": 0.24, "ret_20": 0.12, "breadth_20": 0.18, "netprofit_yoy": 0.18, "or_yoy": 0.12, "avg_amount_20": 0.10, "vol_20": -0.06},
        pre_filter=_quality_filter,
    )

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        frames = []
        rebalance = "weekly" if self.cfg.rebalance == "event" else self.cfg.rebalance
        for date in get_rebalance_dates(start, end, rebalance):
            df = _feature_frame(date, self.cfg)
            if df.empty:
                continue
            df = _quality_filter(df, self.cfg)
            if df.empty:
                continue
            if "netprofit_yoy" not in df.columns:
                df["netprofit_yoy"] = np.nan
            industry_score = df.groupby("industry").apply(
                lambda x: 0.45 * pd.to_numeric(x["ret_60"], errors="coerce").median()
                + 0.25 * pd.to_numeric(x["breadth_20"], errors="coerce").median()
                + 0.30 * pd.to_numeric(x["netprofit_yoy"], errors="coerce").median() / 100
            )
            top_n = int((self.cfg.selection or {}).get("top_n_industries", 4))
            selected = set(industry_score.sort_values(ascending=False).head(top_n).index)
            df = df[df["industry"].isin(selected)]
            scores = _score(df, self.rule.weights)
            weights = _weights_from_scores(df, date, self.cfg, scores)
            if not weights.empty:
                frames.append(weights)
        return pd.concat(frames).sort_index().fillna(0.0) if frames else pd.DataFrame()


class LowCrowdingReversal(QuantFactorStrategy):
    rule = RuleBook(
        weights={"ret_60": -0.16, "ret_20": -0.20, "amount_spike": -0.14, "vol_20": -0.10, "netprofit_yoy": 0.18, "cfo_to_np": 0.12, "pb": -0.10, "roe": 0.10},
        pre_filter=_quality_filter,
    )


class EventEnhanced(QuantFactorStrategy):
    rule = RuleBook(
        weights={"event_strength": 0.30, "forecast_growth": 0.18, "inst_net_buy": 0.16, "holder_buy_value": 0.14, "ret_20": -0.12, "avg_amount_20": 0.10},
        pre_filter=_event_filter,
    )


class BeijingSatellite(QuantFactorStrategy):
    rule = RuleBook(
        weights={"ret_60": 0.20, "ret_20": -0.12, "netprofit_yoy": 0.22, "roe": 0.18, "vol_60": -0.18, "avg_amount_20": 0.10},
        pre_filter=_quality_filter,
        bj_only=True,
    )


@register("market_regime_timing", "市场状态择时")
def build_market_regime_timing():
    return MarketRegimeTiming(StrategyConfig.from_yaml("market_regime_timing"))


@register("multi_factor_composite", "多因子综合")
def build_multi_factor_composite():
    return MultiFactorComposite(StrategyConfig.from_yaml("multi_factor_composite"))


@register("momentum_quality_guard", "动量质量护栏")
def build_momentum_quality_guard():
    return MomentumQualityGuard(StrategyConfig.from_yaml("momentum_quality_guard"))


@register("quality_growth_cooldown", "质量成长冷却")
def build_quality_growth_cooldown():
    return QualityGrowthCooldown(StrategyConfig.from_yaml("quality_growth_cooldown"))


@register("small_cap_quality", "小盘质量")
def build_research_small_cap_quality():
    return ResearchSmallCapQuality(StrategyConfig.from_yaml("small_cap_quality"))


@register("trend_pullback", "趋势回撤")
def build_trend_pullback():
    return TrendPullback(StrategyConfig.from_yaml("trend_pullback"))


@register("turtle_breakout", "海龟突破")
def build_turtle_breakout():
    return TurtleBreakout(StrategyConfig.from_yaml("turtle_breakout"))


@register("dividend_quality", "红利质量")
def build_dividend_quality():
    return DividendQuality(StrategyConfig.from_yaml("dividend_quality"))


@register("earnings_revision", "盈利预期修正")
def build_earnings_revision():
    return EarningsRevision(StrategyConfig.from_yaml("earnings_revision"))


@register("industry_prosperity", "行业景气")
def build_industry_prosperity():
    return IndustryProsperity(StrategyConfig.from_yaml("industry_prosperity"))


@register("low_crowding_reversal", "低拥挤反转")
def build_low_crowding_reversal():
    return LowCrowdingReversal(StrategyConfig.from_yaml("low_crowding_reversal"))


@register("event_enhanced", "事件增强")
def build_event_enhanced():
    return EventEnhanced(StrategyConfig.from_yaml("event_enhanced"))


@register("beijing_satellite", "北交所卫星")
def build_beijing_satellite():
    return BeijingSatellite(StrategyConfig.from_yaml("beijing_satellite"))
