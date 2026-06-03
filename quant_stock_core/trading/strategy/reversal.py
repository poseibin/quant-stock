"""策略2：困境反转

触发条件：
- 上一年度扣非净利润 < 0 或 同比下滑 > 50%
- 最新季报扣非净利润同比转正且 > 30%
- 营收同比 > 0
- 经营现金流 / 净利润 > 0.5
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.universe import build, UniverseConfig
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register
from common.utils import get_logger

log = get_logger("strategy.reversal")


class Reversal(BaseStrategy):

    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        cfg = self.cfg
        f = cfg.filters
        p = cfg.position

        rebalance_days = get_rebalance_dates(start, end, cfg.rebalance)
        if not rebalance_days:
            return pd.DataFrame()

        u_cfg = UniverseConfig(
            profile=f.get("universe_profile", "retail_edge"),
            exclude_st=f.get("exclude_st", True),
            exclude_delisted=True,
            min_listed_days=f.get("min_listed_days", 365),
            min_avg_amount=f.get("min_avg_amount", 20_000_000),
            min_total_mv=f.get("min_total_mv"),
            max_total_mv=f.get("max_total_mv", 80_000_000_000),
            max_20d_return=f.get("max_20d_return"),
            max_60d_return=f.get("max_60d_return"),
            max_amount_spike=f.get("max_amount_spike"),
            exclude_markets=["BJ"],
        )

        rows = []
        for date in rebalance_days:
            try:
                holdings = self._select(date, u_cfg, f, p)
            except Exception as e:
                log.warning(f"{date} 选股失败: {e}")
                continue
            if not holdings:
                continue
            weight = min(p.get("max_single_weight", 0.08), 1.0 / len(holdings))
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

        # 拉取最近 2 年的财务数据
        ann_start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
        inc = dq.sql(f"""
            SELECT ts_code, ann_date, end_date,
                   n_income_attr_p, total_revenue,
                   COALESCE(n_income_attr_p, 0) -
                     COALESCE(non_oper_income, 0) +
                     COALESCE(non_oper_exp, 0) AS approx_dedu_profit
            FROM read_parquet('{dq.RAW_DIR / "income" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{date}'
              AND ts_code IN ({codes_sql})
        """)
        if inc.empty:
            return []
        inc = inc.sort_values(["ts_code", "end_date", "ann_date"]).drop_duplicates(
            ["ts_code", "end_date"], keep="last")

        # 现金流
        cf = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, n_cashflow_act
            FROM read_parquet('{dq.RAW_DIR / "cashflow" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{date}'
              AND ts_code IN ({codes_sql})
        """)
        cf = cf.sort_values(["ts_code", "end_date", "ann_date"]).drop_duplicates(
            ["ts_code", "end_date"], keep="last") if not cf.empty else cf

        scored = []
        for code, g in inc.groupby("ts_code"):
            g = g.sort_values("end_date").reset_index(drop=True)
            if len(g) < 5:    # 至少需要 4 个季度 + 上年度同期
                continue

            latest = g.iloc[-1]
            same_period_last_year = self._find_same_period(g, latest["end_date"], -4)
            last_year_end = self._find_year_end(g, latest["end_date"])
            prev_year_end = self._find_same_period(g, last_year_end["end_date"] if last_year_end is not None else "", -4) if last_year_end is not None else None

            if same_period_last_year is None or last_year_end is None:
                continue

            # 条件 1：上年度扣非利润为负 或 同比下滑 > 50%
            ly_profit = last_year_end.get("approx_dedu_profit", 0) or 0
            if prev_year_end is not None:
                py_profit = prev_year_end.get("approx_dedu_profit", 0) or 0
                year_decline = (ly_profit < 0) or (
                    py_profit > 0 and (ly_profit - py_profit) / abs(py_profit) < -f.get("last_year_negative_or_decline", 0.5)
                )
            else:
                year_decline = ly_profit < 0
            if not year_decline:
                continue

            # 条件 2：最新季报扣非利润同比转正 + 增速 > 30%
            cur_profit = latest.get("approx_dedu_profit", 0) or 0
            sp_profit = same_period_last_year.get("approx_dedu_profit", 0) or 0
            if cur_profit <= 0:
                continue
            if sp_profit > 0:
                growth = (cur_profit - sp_profit) / abs(sp_profit)
                if growth < f.get("min_quarter_profit_yoy", 0.30):
                    continue
            else:
                growth = 1.0

            # 条件 3：营收同比 > 0
            cur_rev = latest.get("total_revenue", 0) or 0
            sp_rev = same_period_last_year.get("total_revenue", 0) or 0
            if sp_rev > 0 and (cur_rev - sp_rev) / sp_rev <= f.get("min_yoy_revenue", 0):
                continue
            rev_growth = (cur_rev - sp_rev) / sp_rev if sp_rev > 0 else 0.0

            # 条件 4：经营现金流 / 净利润 > 0.5
            cf_ratio_ok = True
            cf_ratio = 0.0
            if not cf.empty:
                cf_g = cf[cf["ts_code"] == code]
                if not cf_g.empty:
                    cf_latest = cf_g[cf_g["end_date"] == latest["end_date"]]
                    if not cf_latest.empty and cur_profit > 0:
                        cf_ratio = (cf_latest["n_cashflow_act"].iloc[0] or 0) / cur_profit
                        if cf_ratio < f.get("min_cfo_to_ni_ratio", 0.5):
                            cf_ratio_ok = False
            if not cf_ratio_ok:
                continue

            scored.append({
                "ts_code": code,
                "profit_growth": growth,
                "revenue_growth": rev_growth,
                "cfo_to_profit": cf_ratio,
            })

        if not scored:
            return []

        score_df = pd.DataFrame(scored)
        for col in ["profit_growth", "revenue_growth", "cfo_to_profit"]:
            score_df[col] = score_df[col].clip(lower=-2, upper=5)
        score_df["score"] = (
            score_df["profit_growth"].rank(pct=True) * 0.50
            + score_df["revenue_growth"].rank(pct=True) * 0.25
            + score_df["cfo_to_profit"].rank(pct=True) * 0.25
        )
        score_df = score_df.sort_values("score", ascending=False)

        # 限制行业集中度，避免反转名单全挤在同一个困境行业。
        max_industry_weight = p.get("max_industry_weight")
        max_per_industry = 0
        n_hold = int(p.get("n_holdings", 15))
        if max_industry_weight:
            max_per_industry = max(1, int(n_hold * float(max_industry_weight)))
        if max_per_industry <= 0:
            return score_df.head(n_hold)["ts_code"].tolist()

        basic = dq.get_stock_basic()[["ts_code", "industry"]]
        score_df = score_df.merge(basic, on="ts_code", how="left")
        picked: list[str] = []
        industry_counts: dict[str, int] = {}
        for _, row in score_df.iterrows():
            industry = str(row.get("industry") or "未知")
            if industry_counts.get(industry, 0) >= max_per_industry:
                continue
            picked.append(str(row["ts_code"]))
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            if len(picked) >= n_hold:
                break
        return picked

    @staticmethod
    def _find_year_end(g: pd.DataFrame, ref_end: str) -> pd.Series | None:
        """找到 ref_end 之前最近的一个 12-31 报告期。"""
        candidates = g[g["end_date"].str.endswith("1231") & (g["end_date"] < ref_end)]
        return candidates.iloc[-1] if not candidates.empty else None

    @staticmethod
    def _find_same_period(g: pd.DataFrame, ref_end: str, offset: int) -> pd.Series | None:
        """根据 offset 偏移季度，查找同期数据。offset=-4 表示上年同期。"""
        if not ref_end or ref_end not in set(g["end_date"]):
            return None
        idx = g.index[g["end_date"] == ref_end].tolist()
        if not idx:
            return None
        target_idx = idx[0] + offset
        if target_idx < g.index.min() or target_idx > g.index.max():
            return None
        try:
            return g.loc[target_idx]
        except KeyError:
            return None


@register("reversal", "反转")
def build_strategy() -> Reversal:
    cfg = StrategyConfig.from_yaml("reversal")
    return Reversal(cfg)
