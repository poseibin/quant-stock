"""策略7：趋势质量

选择中期趋势已经走强、短期没有明显过热，同时财务质量可接受的股票。
该策略用于补充组合的趋势暴露，避免组合只依赖小盘、事件和反转信号。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from research.universe import UniverseConfig, build
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register

log = get_logger("strategy.trend_quality")


class TrendQuality(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        cfg = self.cfg
        u = cfg.universe
        f = cfg.filters
        p = cfg.position

        rebalance_days = get_rebalance_dates(start, end, cfg.rebalance)
        if not rebalance_days:
            return pd.DataFrame()

        u_cfg = UniverseConfig(
            profile=u.get("profile", "retail_edge"),
            exclude_st=f.get("exclude_st", True),
            exclude_delisted=True,
            min_listed_days=u.get("min_listed_days", 365),
            min_avg_amount=u.get("min_avg_amount", 50_000_000),
            avg_amount_window=u.get("avg_amount_window", 20),
            min_total_mv=u.get("min_total_mv"),
            max_total_mv=u.get("max_total_mv", 80_000_000_000),
            max_20d_return=u.get("max_20d_return"),
            max_60d_return=u.get("max_60d_return"),
            max_amount_spike=u.get("max_amount_spike"),
            exclude_markets=["BJ"],
            require_tradable=True,
        )

        rows = []
        for date in rebalance_days:
            try:
                holdings = self._select(date, u_cfg, f, p)
            except Exception as exc:
                log.warning(f"{date} 趋势质量选股失败: {exc}")
                continue
            if not holdings:
                continue
            weight = min(float(p.get("max_single_weight", 0.05)), 1.0 / len(holdings))
            for code in holdings:
                rows.append({"trade_date": date, "ts_code": code, "weight": weight})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df.pivot(index="trade_date", columns="ts_code", values="weight").fillna(0.0)

    def _select(self, date: str, u_cfg: UniverseConfig, f: dict, p: dict) -> list[str]:
        codes = build(date, u_cfg)
        if not codes:
            return []

        features = self._price_features(
            codes,
            date,
            long_window=int(f.get("long_window", 120)),
            mid_window=int(f.get("mid_window", 60)),
            short_window=int(f.get("short_window", 20)),
        )
        if features.empty:
            return []

        min_mid_ret = float(f.get("min_mid_return", 0.08))
        max_short_ret = float(f.get("max_short_return", 0.25))
        features = features[
            (features["ret_mid"] >= min_mid_ret)
            & (features["ret_short"] <= max_short_ret)
            & (features["adj_close"] >= features["ma_long"])
            & (features["amount"] > 0)
        ].copy()
        if features.empty:
            return []

        quality = self._quality_features(features["ts_code"].tolist(), date, f)
        if not quality.empty:
            features = features.merge(quality, on="ts_code", how="left")
            min_roe = float(f.get("min_roe", 0.06)) * 100
            max_debt = float(f.get("max_debt_ratio", 0.75)) * 100
            features = features[
                (features["roe"].fillna(min_roe) >= min_roe)
                & (features["debt_to_assets"].fillna(max_debt) <= max_debt)
            ]
        if features.empty:
            return []

        weights = f.get("score_weights") or {
            "trend": 0.45,
            "breakout": 0.20,
            "liquidity": 0.15,
            "low_vol": 0.10,
            "quality": 0.10,
        }
        features["score"] = 0.0

        def add_rank(col: str, weight: float, ascending: bool) -> None:
            if weight == 0 or col not in features.columns:
                return
            s = features[col].replace([float("inf"), float("-inf")], pd.NA)
            if s.notna().sum() < 2:
                return
            features["score"] += s.rank(pct=True, ascending=ascending).fillna(0.5) * weight

        add_rank("ret_long", float(weights.get("trend", 0.0)), ascending=True)
        add_rank("dist_ma_long", float(weights.get("breakout", 0.0)), ascending=True)
        add_rank("amount", float(weights.get("liquidity", 0.0)), ascending=True)
        add_rank("vol_short", float(weights.get("low_vol", 0.0)), ascending=False)
        add_rank("roe", float(weights.get("quality", 0.0)), ascending=True)

        basic = dq.get_stock_basic()[["ts_code", "industry"]]
        features = features.merge(basic, on="ts_code", how="left")
        return self._limit_industry(features, p)

    @staticmethod
    def _price_features(
        codes: list[str],
        date: str,
        *,
        long_window: int,
        mid_window: int,
        short_window: int,
    ) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()
        codes_sql = ",".join(f"'{c}'" for c in codes)
        lookback = max(long_window, mid_window, short_window) + 80
        start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=lookback * 2)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT d.trade_date, d.ts_code,
                   d.close * a.adj_factor AS adj_close,
                   d.close,
                   d.amount * 1000 AS amount
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
            JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.trade_date >= '{start}' AND d.trade_date <= '{date}'
              AND d.ts_code IN ({codes_sql})
        """)
        if df.empty:
            return pd.DataFrame()

        close = df.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
        if len(close) < max(long_window, mid_window, short_window) + 1:
            return pd.DataFrame()
        latest = df.sort_values("trade_date").groupby("ts_code").tail(1)
        out = latest[["ts_code", "close", "amount"]].copy()
        ret_long = close.pct_change(long_window).iloc[-1]
        ret_mid = close.pct_change(mid_window).iloc[-1]
        ret_short = close.pct_change(short_window).iloc[-1]
        vol_short = close.pct_change().rolling(short_window).std().iloc[-1]
        ma_long = close.rolling(long_window).mean().iloc[-1]
        latest_adj = close.iloc[-1]
        out["ret_long"] = out["ts_code"].map(ret_long)
        out["ret_mid"] = out["ts_code"].map(ret_mid)
        out["ret_short"] = out["ts_code"].map(ret_short)
        out["vol_short"] = out["ts_code"].map(vol_short)
        out["ma_long"] = out["ts_code"].map(ma_long)
        out["adj_close"] = out["ts_code"].map(latest_adj)
        out["dist_ma_long"] = out["adj_close"] / out["ma_long"] - 1
        return out.dropna(subset=["ret_long", "ret_mid", "ret_short", "vol_short", "ma_long"])

    @staticmethod
    def _quality_features(codes: list[str], date: str, f: dict) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()
        codes_sql = ",".join(f"'{c}'" for c in codes)
        ann_start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=540)).strftime("%Y%m%d")
        fin = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, roe, debt_to_assets
            FROM read_parquet('{dq.RAW_DIR / "fina_indicator" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{date}'
              AND ts_code IN ({codes_sql})
        """)
        if fin.empty:
            return pd.DataFrame()
        return fin.sort_values(["ts_code", "ann_date"]).groupby("ts_code").tail(1)

    @staticmethod
    def _limit_industry(df: pd.DataFrame, p: dict) -> list[str]:
        n_hold = int(p.get("n_holdings", 18))
        max_industry_weight = p.get("max_industry_weight", 0.30)
        max_per_industry = max(1, int(n_hold * float(max_industry_weight))) if max_industry_weight else n_hold
        picked: list[str] = []
        industry_counts: dict[str, int] = {}
        ranked = df.sort_values(["score", "ret_short"], ascending=[False, True])
        for _, row in ranked.iterrows():
            industry = str(row.get("industry") or "未知")
            if industry_counts.get(industry, 0) >= max_per_industry:
                continue
            picked.append(str(row["ts_code"]))
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            if len(picked) >= n_hold:
                break
        return picked


@register("trend_quality", "趋势质量")
def build_strategy() -> TrendQuality:
    cfg = StrategyConfig.from_yaml("trend_quality")
    return TrendQuality(cfg)
