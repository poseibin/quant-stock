"""策略8：低波红利

选择股息率较高、估值不过分、波动较低且财务质量稳定的股票。
该策略提供偏防守的收益来源，用于平滑事件和成长/趋势策略的净值波动。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from research.universe import UniverseConfig, build
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register

log = get_logger("strategy.dividend_low_vol")


class DividendLowVol(BaseStrategy):

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
            min_listed_days=u.get("min_listed_days", 730),
            min_avg_amount=u.get("min_avg_amount", 30_000_000),
            avg_amount_window=u.get("avg_amount_window", 20),
            min_total_mv=u.get("min_total_mv", 5_000_000_000),
            max_total_mv=u.get("max_total_mv", 120_000_000_000),
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
                log.warning(f"{date} 低波红利选股失败: {exc}")
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
        codes_sql = ",".join(f"'{c}'" for c in codes)

        min_mv = float(f.get("min_total_mv", 8_000_000_000)) / 10_000
        max_pb = float(f.get("max_pb", 3.0))
        min_dv_ttm = float(f.get("min_dv_ttm", 2.0))
        valuation = dq.sql(f"""
            SELECT ts_code, total_mv, circ_mv, pb, pe_ttm, dv_ttm, turnover_rate
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date = '{date}'
              AND ts_code IN ({codes_sql})
              AND total_mv >= {min_mv}
              AND pb IS NOT NULL AND pb > 0 AND pb <= {max_pb}
              AND dv_ttm IS NOT NULL AND dv_ttm >= {min_dv_ttm}
        """)
        if valuation.empty:
            return []

        price = self._price_features(valuation["ts_code"].tolist(), date, int(f.get("vol_window", 60)))
        if price.empty:
            return []
        df = valuation.merge(price, on="ts_code", how="inner")
        if df.empty:
            return []

        quality = self._quality_features(df["ts_code"].tolist(), date)
        if not quality.empty:
            df = df.merge(quality, on="ts_code", how="left")
            min_roe = float(f.get("min_roe", 0.07)) * 100
            max_debt = float(f.get("max_debt_ratio", 0.70)) * 100
            df = df[
                (df["roe"].fillna(min_roe) >= min_roe)
                & (df["debt_to_assets"].fillna(max_debt) <= max_debt)
            ]
        if df.empty:
            return []

        weights = f.get("score_weights") or {
            "dividend": 0.40,
            "low_vol": 0.25,
            "low_pb": 0.15,
            "quality": 0.15,
            "liquidity": 0.05,
        }
        df["score"] = 0.0

        def add_rank(col: str, weight: float, ascending: bool) -> None:
            if weight == 0 or col not in df.columns:
                return
            s = df[col].replace([float("inf"), float("-inf")], pd.NA)
            if s.notna().sum() < 2:
                return
            df["score"] += s.rank(pct=True, ascending=ascending).fillna(0.5) * weight

        add_rank("dv_ttm", float(weights.get("dividend", 0.0)), ascending=True)
        add_rank("vol", float(weights.get("low_vol", 0.0)), ascending=False)
        add_rank("pb", float(weights.get("low_pb", 0.0)), ascending=False)
        add_rank("roe", float(weights.get("quality", 0.0)), ascending=True)
        add_rank("amount", float(weights.get("liquidity", 0.0)), ascending=True)

        basic = dq.get_stock_basic()[["ts_code", "industry"]]
        df = df.merge(basic, on="ts_code", how="left")
        return self._limit_industry(df, p)

    @staticmethod
    def _price_features(codes: list[str], date: str, window: int) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()
        codes_sql = ",".join(f"'{c}'" for c in codes)
        start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=window * 3)).strftime("%Y%m%d")
        px = dq.sql(f"""
            SELECT d.trade_date, d.ts_code,
                   d.close * a.adj_factor AS adj_close,
                   d.amount * 1000 AS amount
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
            JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.trade_date >= '{start}' AND d.trade_date <= '{date}'
              AND d.ts_code IN ({codes_sql})
        """)
        if px.empty:
            return pd.DataFrame()
        close = px.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
        if len(close) < window:
            return pd.DataFrame()
        ret = close.pct_change()
        vol = ret.rolling(window).std().iloc[-1]
        mom = close.pct_change(window).iloc[-1]
        latest = px.sort_values("trade_date").groupby("ts_code").tail(1)
        out = latest[["ts_code", "amount"]].copy()
        out["vol"] = out["ts_code"].map(vol)
        out["momentum"] = out["ts_code"].map(mom)
        max_momentum = 0.35
        out = out[out["momentum"].fillna(0) <= max_momentum]
        return out.dropna(subset=["vol"])

    @staticmethod
    def _quality_features(codes: list[str], date: str) -> pd.DataFrame:
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
        n_hold = int(p.get("n_holdings", 20))
        max_industry_weight = p.get("max_industry_weight", 0.25)
        max_per_industry = max(1, int(n_hold * float(max_industry_weight))) if max_industry_weight else n_hold
        picked: list[str] = []
        industry_counts: dict[str, int] = {}
        ranked = df.sort_values(["score", "vol"], ascending=[False, True])
        for _, row in ranked.iterrows():
            industry = str(row.get("industry") or "未知")
            if industry_counts.get(industry, 0) >= max_per_industry:
                continue
            picked.append(str(row["ts_code"]))
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            if len(picked) >= n_hold:
                break
        return picked


@register("dividend_low_vol", "低波红利")
def build_strategy() -> DividendLowVol:
    cfg = StrategyConfig.from_yaml("dividend_low_vol")
    return DividendLowVol(cfg)
