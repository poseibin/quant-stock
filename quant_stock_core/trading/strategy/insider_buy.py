"""策略3：大股东增持事件

事件触发：公告 5% 以上股东或董监高完成增持，金额 > 1000 万。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.factors.event import insider_buy_events
from .base import BaseStrategy, StrategyConfig
from .registry import register
from common.utils import get_logger

log = get_logger("strategy.insider_buy")


class InsiderBuy(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        f = self.cfg.filters
        p = self.cfg.position

        events = insider_buy_events(start, end,
                                    min_amount=f.get("min_increase_amount", 10_000_000))
        if events.empty:
            return pd.DataFrame()

        # 关联当前价（公告次日开盘价）
        rows = []
        for _, ev in events.iterrows():
            code = ev["ts_code"]
            ann_date = str(ev["ann_date"])
            avg_price = float(ev["avg_price"]) if ev["avg_price"] else 0
            buy_date = self._next_trade_date(ann_date)
            if buy_date is None or buy_date > end:
                continue

            # 检查公告后股价已涨幅
            cur_price_df = dq.sql(f"""
                SELECT close FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
                WHERE ts_code = '{code}' AND trade_date = '{buy_date}'
            """)
            if cur_price_df.empty:
                continue
            cur_price = float(cur_price_df["close"].iloc[0])
            if avg_price > 0:
                ratio = avg_price / cur_price
                if ratio < f.get("min_avg_to_current_price_ratio", 0.95):
                    continue

            edge = self._retail_edge_check(code, buy_date, f)
            if not edge:
                continue

            # 不追：公告后股价已涨 > 20%
            ann_close_df = dq.sql(f"""
                SELECT close FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
                WHERE ts_code = '{code}' AND trade_date <= '{ann_date}'
                ORDER BY trade_date DESC LIMIT 1
            """)
            if not ann_close_df.empty:
                ann_close = float(ann_close_df["close"].iloc[0])
                if cur_price / ann_close > 1 + f.get("max_post_ann_return", 0.20):
                    continue

            sell_date = self._add_trade_days(buy_date, f.get("holding_days_max", 60))
            rows.append({
                "ts_code": code,
                "buy_date": buy_date,
                "sell_date": sell_date or end,
            })

        if not rows:
            return pd.DataFrame()
        events_df = pd.DataFrame(rows)
        return self._build_weight_panel(events_df, start, end, p)

    @staticmethod
    def _next_trade_date(date: str) -> str | None:
        days = dq.get_trade_dates(date, str(int(date[:4]) + 1) + "1231")
        return days[1] if len(days) > 1 else (days[0] if days and days[0] > date else None)

    @staticmethod
    def _add_trade_days(date: str, n: int) -> str | None:
        end_year = str(int(date[:4]) + 2) + "1231"
        days = dq.get_trade_dates(date, end_year)
        if len(days) <= n:
            return days[-1] if days else None
        return days[n]

    def _build_weight_panel(self, events_df: pd.DataFrame, start: str, end: str,
                            p: dict) -> pd.DataFrame:
        """把事件持仓转化成每日目标权重矩阵。"""
        all_dates = dq.get_trade_dates(start, end)
        if not all_dates:
            return pd.DataFrame()
        max_w = p.get("max_single_weight", 0.05)

        # 每日的 active 持仓
        weights = {d: {} for d in all_dates}
        for _, ev in events_df.iterrows():
            buy_d = ev["buy_date"]
            sell_d = ev["sell_date"]
            for d in all_dates:
                if buy_d <= d <= sell_d:
                    weights[d][ev["ts_code"]] = max_w

        # 归一化（如果同日触发太多事件，整体权重 ≤ 1）
        df = pd.DataFrame(weights).T.fillna(0.0)
        df.index.name = "trade_date"
        # 行总和如果超过 1，按比例缩放
        row_sum = df.sum(axis=1)
        scale = (1 / row_sum).where(row_sum > 1, 1.0)
        df = df.mul(scale, axis=0)
        return df

    @staticmethod
    def _retail_edge_check(code: str, date: str, f: dict) -> bool:
        db = dq.sql(f"""
            SELECT total_mv
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date = '{date}' AND ts_code = '{code}'
        """)
        if db.empty:
            return False
        total_mv = float(db["total_mv"].iloc[0] or 0) * 10_000
        if total_mv < float(f.get("min_total_mv", 2_000_000_000)):
            return False
        if total_mv > float(f.get("max_total_mv", 80_000_000_000)):
            return False
        pad = (datetime.strptime(date, "%Y%m%d") - timedelta(days=80)).strftime("%Y%m%d")
        px = dq.sql(f"""
            SELECT trade_date, close, amount
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
            WHERE ts_code = '{code}' AND trade_date >= '{pad}' AND trade_date <= '{date}'
            ORDER BY trade_date
        """)
        if len(px) < 20:
            return False
        avg_amount = float(px.tail(20)["amount"].mean() or 0) * 1000
        if avg_amount < float(f.get("min_avg_amount", 20_000_000)):
            return False
        ret_20 = float(px["close"].pct_change(20).iloc[-1] or 0)
        return ret_20 <= float(f.get("max_20d_return", 0.35))


@register("insider_buy", "高管增持")
def build_strategy() -> InsiderBuy:
    cfg = StrategyConfig.from_yaml("insider_buy")
    return InsiderBuy(cfg)
