"""策略6：行业轮动

按行业近中期强度选择强势行业，再在行业内选择流动性较好的中大市值股票。
该策略用于补充小盘质量和事件策略的风格暴露，降低组合对单一小盘因子的依赖。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.universe import build, UniverseConfig
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register


class IndustryRotation(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        cfg = self.cfg
        u = cfg.universe
        sel = cfg.selection
        p = cfg.position

        rebalance_days = get_rebalance_dates(start, end, cfg.rebalance)
        if not rebalance_days:
            return pd.DataFrame()

        u_cfg = UniverseConfig(
            profile=u.get("profile", "retail_edge"),
            exclude_st=True,
            exclude_delisted=True,
            min_listed_days=u.get("min_listed_days", 250),
            min_avg_amount=u.get("min_avg_amount", 30_000_000),
            min_total_mv=u.get("min_total_mv"),
            max_total_mv=u.get("max_total_mv", 120_000_000_000),
            max_20d_return=u.get("max_20d_return"),
            max_60d_return=u.get("max_60d_return"),
            max_amount_spike=u.get("max_amount_spike"),
            exclude_markets=["BJ"],
        )

        rows = []
        for date in rebalance_days:
            picks = self._select(date, u_cfg, sel, p)
            if not picks:
                continue
            weight = min(p.get("max_single_weight", 0.05), 1.0 / len(picks))
            for code in picks:
                rows.append({"trade_date": date, "ts_code": code, "weight": weight})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df.pivot(index="trade_date", columns="ts_code", values="weight").fillna(0.0)

    def _select(self, date: str, u_cfg: UniverseConfig, sel: dict, p: dict) -> list[str]:
        codes = build(date, u_cfg)
        if not codes:
            return []

        features = self._price_features(codes, date, int(sel.get("momentum_window", 20)))
        if features.empty:
            return []

        basic = dq.get_stock_basic()[["ts_code", "industry"]].dropna(subset=["industry"])
        features = features.merge(basic, on="ts_code", how="inner")
        if features.empty:
            return []

        min_industry_size = int(sel.get("min_industry_size", 5))
        industry_rank = (
            features.groupby("industry")
            .agg(
                industry_ret=("ret", "median"),
                industry_vol=("vol", "median"),
                n=("ts_code", "count"),
            )
            .reset_index()
        )
        industry_rank = industry_rank[industry_rank["n"] >= min_industry_size]
        if industry_rank.empty:
            return []
        industry_rank["score"] = (
            industry_rank["industry_ret"].rank(pct=True) * 0.75
            + industry_rank["industry_vol"].rank(pct=True, ascending=False) * 0.25
        )
        top_n = int(sel.get("top_n_industries", 4))
        top_industries = industry_rank.nlargest(top_n, "score")["industry"].tolist()

        pool = features[features["industry"].isin(top_industries)].copy()
        if pool.empty:
            return []

        rank_range = sel.get("rank_within_industry", [3, 10])
        lo = int(rank_range[0]) if len(rank_range) >= 1 else 1
        hi = int(rank_range[1]) if len(rank_range) >= 2 else 10
        lo = max(1, lo)
        hi = max(lo, hi)

        pool["size_rank"] = pool.groupby("industry")["circ_mv"].rank(
            method="first", ascending=False
        )
        pool = pool[(pool["size_rank"] >= lo) & (pool["size_rank"] <= hi)]
        if pool.empty:
            return []

        pool["stock_score"] = (
            pool.groupby("industry")["ret"].rank(pct=True) * 0.55
            + pool.groupby("industry")["vol"].rank(pct=True, ascending=False) * 0.25
            + pool.groupby("industry")["amount"].rank(pct=True) * 0.20
        )
        per_industry = int(sel.get("stocks_per_industry", 3))
        n_hold = int(p.get("n_holdings", top_n * per_industry))
        picked = (
            pool.sort_values(["industry", "stock_score"], ascending=[True, False])
            .groupby("industry")
            .head(per_industry)
            .sort_values("stock_score", ascending=False)
            .head(n_hold)
        )
        return picked["ts_code"].tolist()

    @staticmethod
    def _price_features(codes: list[str], date: str, window: int) -> pd.DataFrame:
        codes_sql = ",".join(f"'{c}'" for c in codes)
        pad = (datetime.strptime(date, "%Y%m%d") - timedelta(days=int(window * 3))).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT d.trade_date, d.ts_code,
                   d.close * a.adj_factor AS adj_close,
                   d.amount * 1000 AS amount,
                   db.circ_mv
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
            JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            JOIN read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}') db
              ON d.ts_code = db.ts_code AND d.trade_date = db.trade_date
            WHERE d.trade_date >= '{pad}' AND d.trade_date <= '{date}'
              AND d.ts_code IN ({codes_sql})
        """)
        if df.empty:
            return pd.DataFrame()
        close = df.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
        ret = close.pct_change(window).iloc[-1]
        vol = close.pct_change().rolling(window).std().iloc[-1]
        latest = df.sort_values("trade_date").groupby("ts_code").tail(1)
        out = latest[["ts_code", "amount", "circ_mv"]].copy()
        out["ret"] = out["ts_code"].map(ret)
        out["vol"] = out["ts_code"].map(vol)
        return out.dropna(subset=["ret", "vol", "circ_mv"])


@register("industry_rotation", "行业轮动")
def build_strategy() -> IndustryRotation:
    cfg = StrategyConfig.from_yaml("industry_rotation")
    return IndustryRotation(cfg)
