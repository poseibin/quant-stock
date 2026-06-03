"""策略5：龙虎榜机构跟随（备选）"""
from __future__ import annotations

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.event import institution_net_buy
from .base import BaseStrategy, StrategyConfig
from .registry import register


class LhbFollow(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        f = self.cfg.filters
        p = self.cfg.position

        events = institution_net_buy(start, end,
                                     min_net=f.get("min_inst_net_buy", 50_000_000))
        if events.empty:
            return pd.DataFrame()

        # 过滤涨停
        keep = []
        for _, ev in events.iterrows():
            code, d = ev["ts_code"], ev["trade_date"]
            day = dq.sql(f"""
                SELECT open, high, low, close, pre_close
                FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
                WHERE ts_code = '{code}' AND trade_date = '{d}'
            """)
            if day.empty:
                continue
            row = day.iloc[0]
            if f.get("exclude_limit_up", True):
                if row["close"] >= row["pre_close"] * 1.099:
                    continue
            keep.append({"ts_code": code, "trade_date": d})

        if not keep:
            return pd.DataFrame()
        df = pd.DataFrame(keep)
        holding_days = int(f.get("holding_days", 7))
        max_w = p.get("max_single_weight", 0.04)

        all_dates = dq.get_trade_dates(start, end)
        date_to_idx = {d: i for i, d in enumerate(all_dates)}
        weight_panel = pd.DataFrame(0.0, index=all_dates, columns=sorted(df["ts_code"].unique()))

        for _, ev in df.iterrows():
            code = ev["ts_code"]
            event_d = ev["trade_date"]
            if event_d not in date_to_idx:
                continue
            i0 = date_to_idx[event_d] + 1   # 次日开盘买入
            i1 = min(i0 + holding_days, len(all_dates) - 1)
            for j in range(i0, i1 + 1):
                weight_panel.iloc[j, weight_panel.columns.get_loc(code)] = max_w

        # 行总和缩放
        row_sum = weight_panel.sum(axis=1)
        scale = (1 / row_sum).where(row_sum > 1, 1.0)
        return weight_panel.mul(scale, axis=0)


@register("lhb_follow", "龙虎榜")
def build_strategy() -> LhbFollow:
    cfg = StrategyConfig.from_yaml("lhb_follow")
    return LhbFollow(cfg)
