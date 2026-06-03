"""策略10：质量成长 GARP

选择收入和利润增长稳健、ROE/毛利率质量较好，同时估值不过分的股票。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from research.universe import UniverseConfig, build
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register

log = get_logger("strategy.garp_quality")


class GarpQuality(BaseStrategy):

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
            min_avg_amount=u.get("min_avg_amount", 40_000_000),
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
                picks = self._select(date, u_cfg, f, p)
            except Exception as exc:
                log.warning(f"{date} GARP 选股失败: {exc}")
                continue
            if not picks:
                continue
            weight = min(float(p.get("max_single_weight", 0.05)), 1.0 / len(picks))
            for code in picks:
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
        val = dq.sql(f"""
            SELECT ts_code, pe_ttm, pb, ps_ttm, circ_mv
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date = '{date}' AND ts_code IN ({codes_sql})
              AND pe_ttm IS NOT NULL AND pe_ttm > 0 AND pe_ttm <= {float(f.get("max_pe_ttm", 60))}
              AND pb IS NOT NULL AND pb > 0 AND pb <= {float(f.get("max_pb", 8))}
              AND ps_ttm IS NOT NULL AND ps_ttm > 0 AND ps_ttm <= {float(f.get("max_ps_ttm", 12))}
        """)
        if val.empty:
            return []
        quality = self._quality_features(val["ts_code"].tolist(), date)
        if quality.empty:
            return []
        df = val.merge(quality, on="ts_code", how="inner")
        df = df[
            (df["roe"].fillna(0) >= float(f.get("min_roe", 0.08)) * 100)
            & (df["grossprofit_margin"].fillna(0) >= float(f.get("min_gross_margin", 0.15)) * 100)
            & (df["tr_yoy"].fillna(-999) >= float(f.get("min_revenue_yoy", 0.08)) * 100)
            & (df["netprofit_yoy"].fillna(-999) >= float(f.get("min_profit_yoy", 0.08)) * 100)
        ].copy()
        if df.empty:
            return []
        df["peg"] = df["pe_ttm"] / df["netprofit_yoy"].clip(lower=1)
        df["score"] = (
            df["roe"].rank(pct=True) * 0.25
            + df["grossprofit_margin"].rank(pct=True) * 0.20
            + df["tr_yoy"].rank(pct=True) * 0.20
            + df["netprofit_yoy"].rank(pct=True) * 0.20
            + df["peg"].rank(pct=True, ascending=False) * 0.15
        )
        basic = dq.get_stock_basic()[["ts_code", "industry"]]
        df = df.merge(basic, on="ts_code", how="left")
        return self._limit_industry(df, p)

    @staticmethod
    def _quality_features(codes: list[str], date: str) -> pd.DataFrame:
        codes_sql = ",".join(f"'{c}'" for c in codes)
        ann_start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=540)).strftime("%Y%m%d")
        fin = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, roe, grossprofit_margin,
                   tr_yoy, netprofit_yoy, debt_to_assets
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
        max_per_industry = max(1, int(n_hold * float(p.get("max_industry_weight", 0.30))))
        picked: list[str] = []
        counts: dict[str, int] = {}
        for _, row in df.sort_values("score", ascending=False).iterrows():
            industry = str(row.get("industry") or "未知")
            if counts.get(industry, 0) >= max_per_industry:
                continue
            picked.append(str(row["ts_code"]))
            counts[industry] = counts.get(industry, 0) + 1
            if len(picked) >= n_hold:
                break
        return picked


@register("garp_quality", "质量成长")
def build_strategy() -> GarpQuality:
    cfg = StrategyConfig.from_yaml("garp_quality")
    return GarpQuality(cfg)
