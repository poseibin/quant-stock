"""策略11：资金流低吸 / 强势回踩

基于龙虎榜净买入、成交额放大和中期趋势筛选强势股回踩机会，
严格限制短期追高。
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta

import pandas as pd

from common.utils import get_logger
from research.data.storage import duckdb_query as dq
from .base import BaseStrategy, StrategyConfig
from .registry import register

log = get_logger("strategy.moneyflow_pullback")


class MoneyflowPullback(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        f = self.cfg.filters
        p = self.cfg.position
        events = self._events(start, end, f)
        if events.empty:
            return pd.DataFrame()
        candidates = self._build_events(events, start, end, f)
        if candidates.empty:
            return pd.DataFrame()
        return self._weight_panel(candidates, start, end, p)

    @staticmethod
    def _events(start: str, end: str, f: dict) -> pd.DataFrame:
        min_net = float(f.get("min_net_amount", 30_000_000))
        min_amount_rate = float(f.get("min_amount_rate", 1.0))
        df = dq.sql(f"""
            SELECT tl.ts_code, tl.trade_date, tl.pct_change, tl.amount, tl.net_amount,
                   tl.amount_rate, tl.turnover_rate, tl.reason,
                   COALESCE(ti.inst_net_buy, 0) AS inst_net_buy
            FROM read_parquet('{dq.RAW_DIR / "top_list" / "*.parquet"}') tl
            LEFT JOIN (
                SELECT ts_code, trade_date, SUM(net_buy) AS inst_net_buy
                FROM read_parquet('{dq.RAW_DIR / "top_inst" / "*.parquet"}')
                GROUP BY ts_code, trade_date
            ) ti ON tl.ts_code = ti.ts_code AND tl.trade_date = ti.trade_date
            WHERE tl.trade_date >= '{start}' AND tl.trade_date <= '{end}'
              AND (tl.net_amount >= {min_net} OR COALESCE(ti.inst_net_buy, 0) >= {min_net})
              AND tl.amount_rate >= {min_amount_rate}
        """)
        if df.empty:
            return df
        return df.sort_values(["trade_date", "net_amount"], ascending=[True, False]).reset_index(drop=True)

    def _build_events(self, events: pd.DataFrame, start: str, end: str, f: dict) -> pd.DataFrame:
        df = events.copy()
        df["ts_code"] = df["ts_code"].astype(str)
        df["trade_date"] = df["trade_date"].astype(str)
        df["pct_change"] = pd.to_numeric(df.get("pct_change"), errors="coerce").fillna(0.0)
        df["amount_rate"] = pd.to_numeric(df.get("amount_rate"), errors="coerce").fillna(0.0)
        df["turnover_rate"] = pd.to_numeric(df.get("turnover_rate"), errors="coerce").fillna(0.0)
        df["inst_net_buy"] = pd.to_numeric(df.get("inst_net_buy"), errors="coerce").fillna(0.0)

        max_event_return = min(
            float(f.get("max_event_day_return", 9.5)),
            float(f.get("max_event_day_return_cap", 6.0)),
        )
        df = df[
            (df["pct_change"] <= max_event_return)
            & (df["amount_rate"] <= float(f.get("max_amount_rate", 200.0)))
            & (df["turnover_rate"] >= float(f.get("min_turnover_rate", 0.0)))
            & (df["turnover_rate"] <= float(f.get("max_turnover_rate", 100.0)))
            & (df["inst_net_buy"] >= float(f.get("min_inst_net_buy", -1_000_000_000_000)))
            & (df["inst_net_buy"] <= float(f.get("max_inst_net_buy", 1_000_000_000_000)))
        ].copy()
        if df.empty:
            return pd.DataFrame()

        db = dq.get_daily_basic(
            df["ts_code"].unique().tolist(),
            str(df["trade_date"].min()),
            str(df["trade_date"].max()),
        )
        if db.empty or "total_mv" not in db.columns:
            return pd.DataFrame()
        db["trade_date"] = db["trade_date"].astype(str)
        db = db[db["trade_date"].isin(set(df["trade_date"]))]
        db = db[["ts_code", "trade_date", "total_mv"]].copy()
        db["total_mv"] = pd.to_numeric(db["total_mv"], errors="coerce").fillna(0.0) * 10_000
        df = df.merge(db, on=["ts_code", "trade_date"], how="left")
        df = df[
            (df["total_mv"] >= float(f.get("min_total_mv", 2_000_000_000)))
            & (df["total_mv"] <= float(f.get("max_total_mv", 80_000_000_000)))
        ].copy()
        if df.empty:
            return pd.DataFrame()

        trade_days = dq.get_trade_dates(str(df["trade_date"].min()), str(int(end[:4]) + 1) + "1231")
        if not trade_days:
            return pd.DataFrame()
        last_scan = self._last_scan_date(df["trade_date"].tolist(), end, int(f.get("entry_wait_days", 5)), trade_days)
        if not last_scan:
            return pd.DataFrame()

        hist_start = (
            datetime.strptime(str(df["trade_date"].min()), "%Y%m%d") - timedelta(days=140)
        ).strftime("%Y%m%d")
        px = dq.get_price(
            df["ts_code"].unique().tolist(),
            hist_start,
            last_scan,
            cols=("ts_code", "trade_date", "close", "amount"),
        )
        if px.empty:
            return pd.DataFrame()
        px["trade_date"] = px["trade_date"].astype(str)
        by_code = {code: g.sort_values("trade_date") for code, g in px.groupby("ts_code", sort=False)}

        rows = []
        for ev in df.itertuples(index=False):
            try:
                buy_date = self._entry_date_from_history(
                    str(ev.ts_code), str(ev.trade_date), end, f, by_code, trade_days
                )
            except Exception as exc:
                log.warning(f"资金流事件处理失败: {exc}")
                continue
            if not buy_date:
                continue
            holding_days = int(f.get("holding_days", 10))
            sell_date = self._add_trade_days_from_calendar(buy_date, holding_days, trade_days) or end
            rows.append({
                "ts_code": str(ev.ts_code),
                "buy_date": max(buy_date, start),
                "sell_date": min(sell_date, end),
                "score": float(getattr(ev, "net_amount", 0) or 0) + float(getattr(ev, "inst_net_buy", 0) or 0),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _last_scan_date(event_dates: list[str], end: str, wait_days: int, trade_days: list[str]) -> str | None:
        last = None
        for d in event_dates:
            idx = bisect_left(trade_days, d)
            if idx >= len(trade_days):
                continue
            scan_idx = min(idx + wait_days + 1, len(trade_days) - 1)
            scan_date = min(trade_days[scan_idx], end)
            if last is None or scan_date > last:
                last = scan_date
        return last

    def _build_event(self, ev: pd.Series, start: str, end: str, f: dict) -> dict | None:
        code = str(ev["ts_code"])
        event_date = str(ev["trade_date"])
        if float(ev.get("pct_change") or 0) > float(f.get("max_event_day_return", 9.5)):
            return None
        if not self._retail_edge_check(code, event_date, f):
            return None

        buy_date = self._entry_date(code, event_date, end, f)
        if not buy_date:
            return None
        holding_days = int(f.get("holding_days", 10))
        sell_date = self._add_trade_days(buy_date, holding_days) or end
        return {
            "ts_code": code,
            "buy_date": max(buy_date, start),
            "sell_date": min(sell_date, end),
            "score": float(ev.get("net_amount") or 0) + float(ev.get("inst_net_buy") or 0),
        }

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
        return (
            total_mv >= float(f.get("min_total_mv", 2_000_000_000))
            and total_mv <= float(f.get("max_total_mv", 80_000_000_000))
        )

    def _entry_date_from_history(
        self,
        code: str,
        event_date: str,
        end: str,
        f: dict,
        by_code: dict[str, pd.DataFrame],
        trade_days: list[str],
    ) -> str | None:
        wait_days = int(f.get("entry_wait_days", 5))
        min_pullback = float(f.get("min_pullback_from_event_close", -1.00))
        max_pullback = float(f.get("max_pullback_from_event_close", -0.03))
        max_20d_high_dist = min(
            float(f.get("max_dist_to_20d_high", 0.08)),
            float(f.get("max_dist_to_20d_high_cap", 0.06)),
        )
        min_60d_return = max(
            float(f.get("min_60d_return", 0.08)),
            float(f.get("min_60d_return_floor", 0.10)),
        )
        min_close_to_ma20 = float(f.get("min_close_to_ma20", 0.0))
        min_close_to_ma60 = float(f.get("min_close_to_ma60", 0.0))

        idx = bisect_left(trade_days, event_date)
        if idx >= len(trade_days):
            return None
        scan = [d for d in trade_days[idx + 1:min(len(trade_days), idx + wait_days + 2)] if d <= end]
        if not scan:
            return None
        hist = by_code.get(code)
        if hist is None or hist.empty:
            return None
        until_event = hist[hist["trade_date"] <= event_date]
        if until_event.empty:
            return None
        event_close = float(until_event["close"].iloc[-1])
        if event_close <= 0:
            return None

        for d in scan:
            cur = hist[hist["trade_date"] <= d].tail(60)
            if len(cur) < 30:
                continue
            close = float(cur["close"].iloc[-1])
            base = float(cur["close"].iloc[0])
            if close <= 0 or base <= 0:
                continue
            ret_60 = close / base - 1
            high_20 = float(cur.tail(20)["close"].max())
            ma20 = float(cur.tail(20)["close"].mean())
            ma60 = float(cur["close"].mean())
            pullback = close / event_close - 1
            dist_high = close / high_20 - 1 if high_20 > 0 else 0
            if ret_60 <= min_60d_return:
                continue
            if pullback < min_pullback or pullback > max_pullback:
                continue
            if abs(dist_high) > max_20d_high_dist:
                continue
            if ma20 > 0 and close / ma20 < min_close_to_ma20:
                continue
            if ma60 > 0 and close / ma60 < min_close_to_ma60:
                continue
            return d
        return None

    def _entry_date(self, code: str, event_date: str, end: str, f: dict) -> str | None:
        wait_days = int(f.get("entry_wait_days", 5))
        min_pullback = float(f.get("min_pullback_from_event_close", -1.00))
        max_pullback = float(f.get("max_pullback_from_event_close", -0.03))
        max_20d_high_dist = min(
            float(f.get("max_dist_to_20d_high", 0.08)),
            float(f.get("max_dist_to_20d_high_cap", 0.06)),
        )
        min_60d_return = max(
            float(f.get("min_60d_return", 0.08)),
            float(f.get("min_60d_return_floor", 0.10)),
        )
        min_close_to_ma20 = float(f.get("min_close_to_ma20", 0.0))
        min_close_to_ma60 = float(f.get("min_close_to_ma60", 0.0))
        dates = dq.get_trade_dates(event_date, end)
        if len(dates) < 2:
            return None
        scan = dates[1:min(len(dates), wait_days + 2)]
        hist = self._price_history(code, event_date, scan[-1])
        if hist.empty:
            return None
        event_close = float(hist.loc[hist["trade_date"] <= event_date, "close"].iloc[-1])
        for d in scan:
            cur = hist[hist["trade_date"] <= d].tail(60)
            if len(cur) < 30:
                continue
            close = float(cur["close"].iloc[-1])
            ret_60 = close / float(cur["close"].iloc[0]) - 1
            high_20 = float(cur.tail(20)["close"].max())
            ma20 = float(cur.tail(20)["close"].mean())
            ma60 = float(cur["close"].mean())
            pullback = close / event_close - 1
            dist_high = close / high_20 - 1
            if ret_60 <= min_60d_return:
                continue
            if pullback < min_pullback or pullback > max_pullback:
                continue
            if abs(dist_high) > max_20d_high_dist:
                continue
            if ma20 > 0 and close / ma20 < min_close_to_ma20:
                continue
            if ma60 > 0 and close / ma60 < min_close_to_ma60:
                continue
            return d
        return None

    @staticmethod
    def _price_history(code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pad = (datetime.strptime(start_date, "%Y%m%d") - timedelta(days=140)).strftime("%Y%m%d")
        return dq.sql(f"""
            SELECT trade_date, close, amount
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
            WHERE ts_code = '{code}' AND trade_date >= '{pad}' AND trade_date <= '{end_date}'
            ORDER BY trade_date
        """)

    @staticmethod
    def _add_trade_days(date: str, n: int) -> str | None:
        days = dq.get_trade_dates(date, str(int(date[:4]) + 1) + "1231")
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
        max_holdings = int(p.get("max_active_events", 15))
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


@register("moneyflow_pullback", "资金低吸")
def build_strategy() -> MoneyflowPullback:
    cfg = StrategyConfig.from_yaml("moneyflow_pullback")
    return MoneyflowPullback(cfg)
