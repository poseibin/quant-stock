"""策略9：业绩预告 / 盈利上修

利用 forecast 业绩预告中的预增、扭亏、续盈信号，过滤公告后过热、
估值过高和流动性不足的标的，形成短中期事件型持仓。
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

import pandas as pd

from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from research.factors.event import performance_forecast
from .base import BaseStrategy, StrategyConfig
from .registry import register

log = get_logger("strategy.forecast_revision")


class ForecastRevision(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        f = self.cfg.filters
        p = self.cfg.position
        events = performance_forecast(start, end, only_increase=True)
        if events.empty:
            return pd.DataFrame()

        candidates = self._build_events(events, start, end, f)
        if candidates.empty:
            return pd.DataFrame()
        return self._weight_panel(candidates, start, end, p)

    def _build_events(self, events: pd.DataFrame, start: str, end: str, f: dict) -> pd.DataFrame:
        df = events.copy()
        df["ts_code"] = df["ts_code"].astype(str)
        df["ann_date"] = df["ann_date"].astype(str)
        df["p_change_min"] = self._numeric_col(df, "p_change_min")
        df["p_change_max"] = self._numeric_col(df, "p_change_max")
        df["growth"] = df[["p_change_min", "p_change_max"]].max(axis=1)
        df["event_type"] = self._text_col(df, "type")
        df["net_profit_min"] = self._numeric_col(df, "net_profit_min")

        trade_days = dq.get_trade_dates(start, str(int(end[:4]) + 2) + "1231")
        if not trade_days:
            return pd.DataFrame()

        df["buy_date"] = df["ann_date"].map(lambda d: self._next_trade_date_from_calendar(d, trade_days))
        df = df[df["buy_date"].notna() & (df["buy_date"] <= end)].copy()
        if df.empty:
            return pd.DataFrame()

        holding_days = int(f.get("holding_days", 40))
        df["sell_date"] = df["buy_date"].map(
            lambda d: self._add_trade_days_from_calendar(str(d), holding_days, trade_days) or end
        )
        df["buy_date"] = df["buy_date"].map(lambda d: max(str(d), start))
        df["sell_date"] = df["sell_date"].map(lambda d: min(str(d), end))

        min_growth = float(f.get("min_profit_growth", 30.0))
        min_turnaround_profit = float(f.get("min_turnaround_profit", 20_000_000))
        df = df[
            ((df["event_type"] != "扭亏") & (df["growth"] >= min_growth))
            | ((df["event_type"] == "扭亏") & (df["net_profit_min"] >= min_turnaround_profit))
        ].copy()
        if df.empty:
            return pd.DataFrame()

        daily_basic = dq.get_daily_basic(
            df["ts_code"].unique().tolist(),
            str(df["buy_date"].min()),
            str(df["buy_date"].max()),
        )
        if daily_basic.empty:
            return pd.DataFrame()
        daily_basic = daily_basic[daily_basic["trade_date"].astype(str).isin(set(df["buy_date"]))]
        keep_cols = ["ts_code", "trade_date", "pb", "pe_ttm", "circ_mv", "total_mv", "dv_ttm"]
        daily_basic = daily_basic[[c for c in keep_cols if c in daily_basic.columns]].copy()
        df = df.merge(
            daily_basic,
            left_on=["ts_code", "buy_date"],
            right_on=["ts_code", "trade_date"],
            how="left",
        )
        df = df[df["trade_date"].notna()].copy()
        if df.empty:
            return pd.DataFrame()

        max_pe = float(f.get("max_pe_ttm", 80.0))
        max_pb = float(f.get("max_pb", 8.0))
        for col in ("pb", "pe_ttm", "total_mv"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        total_mv = df["total_mv"].fillna(0.0) * 10_000
        df = df[
            (df["pe_ttm"].isna() | (df["pe_ttm"] <= max_pe))
            & (df["pb"].isna() | (df["pb"] <= max_pb))
            & (total_mv >= float(f.get("min_total_mv", 2_000_000_000)))
            & (total_mv <= float(f.get("max_total_mv", 80_000_000_000)))
        ].copy()
        if df.empty:
            return pd.DataFrame()

        features = self._price_features_bulk(df, int(f.get("lookback_days", 20)))
        if features.empty:
            return pd.DataFrame()
        df = df.merge(features, on=["ts_code", "ann_date", "buy_date"], how="left")
        df = df[df["post_return"].notna() & df["avg_amount"].notna()].copy()
        df = df[
            (df["post_return"] <= float(f.get("max_post_ann_return", 0.18)))
            & (df["avg_amount"] >= float(f.get("min_avg_amount", 20_000_000)))
        ].copy()
        if df.empty:
            return pd.DataFrame()

        df["score"] = df["growth"] + (df["event_type"].eq("扭亏").astype(float) * 80) - df["post_return"] * 100
        return df[["ts_code", "buy_date", "sell_date", "score"]].reset_index(drop=True)

    @staticmethod
    def _numeric_col(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
        if col not in df.columns:
            return pd.Series(default, index=df.index, dtype="float64")
        return pd.to_numeric(df[col], errors="coerce").fillna(default)

    @staticmethod
    def _text_col(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
        if col not in df.columns:
            return pd.Series(default, index=df.index, dtype="object")
        return df[col].fillna(default).astype(str)

    @staticmethod
    def _price_features_bulk(events: pd.DataFrame, window: int) -> pd.DataFrame:
        start_pad = (
            datetime.strptime(str(events["ann_date"].min()), "%Y%m%d")
            - timedelta(days=max(window * 3, 90))
        ).strftime("%Y%m%d")
        px = dq.get_price(
            events["ts_code"].unique().tolist(),
            start_pad,
            str(events["buy_date"].max()),
            cols=("ts_code", "trade_date", "close", "amount"),
        )
        if px.empty:
            return pd.DataFrame()
        px["trade_date"] = px["trade_date"].astype(str)
        by_code = {code: g.sort_values("trade_date") for code, g in px.groupby("ts_code", sort=False)}

        rows = []
        for ev in events[["ts_code", "ann_date", "buy_date"]].itertuples(index=False):
            hist = by_code.get(ev.ts_code)
            if hist is None or hist.empty:
                continue
            until_buy = hist[hist["trade_date"] <= ev.buy_date]
            until_ann = hist[hist["trade_date"] <= ev.ann_date]
            if until_buy.empty or until_ann.empty:
                continue
            ann_close = float(until_ann["close"].iloc[-1])
            buy_close = float(until_buy["close"].iloc[-1])
            if ann_close <= 0:
                continue
            avg_amount = float(until_buy.tail(window)["amount"].mean() or 0) * 1000
            rows.append({
                "ts_code": ev.ts_code,
                "ann_date": ev.ann_date,
                "buy_date": ev.buy_date,
                "post_return": buy_close / ann_close - 1,
                "avg_amount": avg_amount,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _price_features(code: str, ann_date: str, buy_date: str, window: int) -> dict | None:
        pad = (datetime.strptime(buy_date, "%Y%m%d") - timedelta(days=window * 3)).strftime("%Y%m%d")
        df = dq.sql(f"""
            SELECT trade_date, close, amount
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
            WHERE ts_code = '{code}' AND trade_date >= '{pad}' AND trade_date <= '{buy_date}'
            ORDER BY trade_date
        """)
        if df.empty:
            return None
        ann_px = df[df["trade_date"] <= ann_date].tail(1)
        buy_px = df[df["trade_date"] <= buy_date].tail(1)
        if ann_px.empty or buy_px.empty:
            return None
        ann_close = float(ann_px["close"].iloc[0])
        buy_close = float(buy_px["close"].iloc[0])
        avg_amount = float(df.tail(window)["amount"].mean() or 0) * 1000
        return {"post_return": buy_close / ann_close - 1 if ann_close > 0 else 0, "avg_amount": avg_amount}

    @staticmethod
    def _next_trade_date(date: str) -> str | None:
        days = dq.get_trade_dates(date, str(int(date[:4]) + 1) + "1231")
        return days[1] if len(days) > 1 else (days[0] if days and days[0] > date else None)

    @staticmethod
    def _next_trade_date_from_calendar(date: str, trade_days: list[str]) -> str | None:
        idx = bisect_right(trade_days, date)
        return trade_days[idx] if idx < len(trade_days) else None

    @staticmethod
    def _add_trade_days(date: str, n: int) -> str | None:
        days = dq.get_trade_dates(date, str(int(date[:4]) + 2) + "1231")
        if not days:
            return None
        return days[min(n, len(days) - 1)]

    @staticmethod
    def _add_trade_days_from_calendar(date: str, n: int, trade_days: list[str]) -> str | None:
        idx = bisect_left(trade_days, date)
        if idx >= len(trade_days):
            return None
        return trade_days[min(idx + n, len(trade_days) - 1)]

    @staticmethod
    def _weight_panel(events: pd.DataFrame, start: str, end: str, p: dict) -> pd.DataFrame:
        dates = dq.get_trade_dates(start, end)
        if not dates:
            return pd.DataFrame()
        max_holdings = int(p.get("max_active_events", 20))
        max_w = float(p.get("max_single_weight", 0.04))
        weights = {d: {} for d in dates}
        for d in dates:
            active = events[(events["buy_date"] <= d) & (events["sell_date"] >= d)]
            if active.empty:
                continue
            active = active.sort_values("score", ascending=False).head(max_holdings)
            w = min(max_w, 1.0 / len(active))
            for code in active["ts_code"]:
                weights[d][code] = w
        out = pd.DataFrame(weights).T.fillna(0.0)
        out.index.name = "trade_date"
        return out


@register("forecast_revision", "业绩预告")
def build_strategy() -> ForecastRevision:
    cfg = StrategyConfig.from_yaml("forecast_revision")
    return ForecastRevision(cfg)
