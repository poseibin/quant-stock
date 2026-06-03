"""策略4：北交所策略"""
from __future__ import annotations

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.universe import build, UniverseConfig
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register


class BeijingSE(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        u = self.cfg.universe
        f = self.cfg.filters
        p = self.cfg.position

        rebalance_days = get_rebalance_dates(start, end, self.cfg.rebalance)
        if not rebalance_days:
            return pd.DataFrame()

        u_cfg = UniverseConfig(
            exclude_st=True,
            exclude_delisted=True,
            min_listed_days=120,
            min_avg_amount=u.get("min_avg_amount", 5_000_000),
            keep_markets=["BSE"],         # tushare exchange = BSE 表示北交所
        )

        rows = []
        for date in rebalance_days:
            codes = build(date, u_cfg)
            if not codes:
                continue
            sql = ",".join(f"'{c}'" for c in codes)
            df = dq.sql(f"""
                SELECT db.ts_code, db.pb, db.pe_ttm, db.circ_mv
                FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}') db
                WHERE db.trade_date = '{date}'
                  AND db.ts_code IN ({sql})
                  AND db.pb IS NOT NULL AND db.pb > 0
            """)
            if df.empty:
                continue
            df = df.sort_values("pb", ascending=True)
            n_hold = int(p.get("n_holdings", 12))
            picks = df.head(n_hold)["ts_code"].tolist()
            if not picks:
                continue
            weight = min(p.get("max_single_weight", 0.08), 1.0 / len(picks))
            for code in picks:
                rows.append({"trade_date": date, "ts_code": code, "weight": weight})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df.pivot(index="trade_date", columns="ts_code", values="weight").fillna(0.0)


@register("beijing_se", "北交所")
def build_strategy() -> BeijingSE:
    cfg = StrategyConfig.from_yaml("beijing_se")
    return BeijingSE(cfg)
