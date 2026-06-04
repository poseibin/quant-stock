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
        stock_where.append("(exchange = 'BJ' OR market = '北交所')")
    else:
        stock_where.append("COALESCE(exchange, '') <> 'BJ'")
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
        ["roe", "q_roe", "grossprofit_margin", "netprofit_yoy", "or_yoy", "debt_to_assets", "ocf_yoy"],
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


def _market_exposure(date: str, cfg: StrategyConfig) -> float:
    regime = (cfg.filters or {}).get("market_regime") or {}
    if not regime:
        return 1.0
    trend_window = int(regime.get("trend_window", 60))
    breadth_window = int(regime.get("breadth_window", 20))
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
        return float(regime.get("bear_exposure", 0.25))
    if market_trend < 0 or breadth < float(regime.get("min_breadth", 0.45)):
        return float(regime.get("weak_exposure", 0.50))
    return float(regime.get("normal_exposure", 1.0))


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
        out = out[pd.to_numeric(out.get("roe"), errors="coerce").fillna(-999) >= float(f["min_roe"]) * 100]
    if f.get("min_roe_ttm") is not None:
        out = out[pd.to_numeric(out.get("roe"), errors="coerce").fillna(-999) >= float(f["min_roe_ttm"]) * 100]
    if f.get("max_debt_ratio") is not None:
        out = out[pd.to_numeric(out.get("debt_to_assets"), errors="coerce").fillna(999) <= float(f["max_debt_ratio"]) * 100]
    return out


def _trend_pullback_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = _quality_filter(df, cfg)
    out = out[pd.to_numeric(out.get("ret_60"), errors="coerce").fillna(-999) >= float(f.get("min_mid_return", 0.06))]
    out = out[pd.to_numeric(out.get("ret_20"), errors="coerce").fillna(999) <= float(f.get("max_short_return", 0.18))]
    out = out[pd.to_numeric(out.get("pullback_20"), errors="coerce").fillna(-999).between(-0.18, -0.02)]
    return out


def _dividend_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    out = _quality_filter(df, cfg)
    out = out[pd.to_numeric(out.get("dv_ttm"), errors="coerce").fillna(0) >= float(f.get("min_dv_ttm", 2.0))]
    out = out[pd.to_numeric(out.get("pb"), errors="coerce").fillna(999) <= float(f.get("max_pb", 3.0))]
    return out


def _earnings_filter(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    f = cfg.filters or {}
    growth = _num_col(df, "forecast_growth").fillna(_num_col(df, "netprofit_yoy"))
    out = df[growth >= float(f.get("min_profit_growth", 25.0))].copy()
    out = out[pd.to_numeric(out.get("ret_20"), errors="coerce").fillna(999) <= float(f.get("max_post_ann_return", 0.15))]
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


@register("small_cap_quality", "小盘质量")
def build_research_small_cap_quality():
    return ResearchSmallCapQuality(StrategyConfig.from_yaml("small_cap_quality"))


@register("trend_pullback", "趋势回撤")
def build_trend_pullback():
    return TrendPullback(StrategyConfig.from_yaml("trend_pullback"))


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
