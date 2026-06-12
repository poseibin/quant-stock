"""策略1：小市值 + 质量过滤（Baseline）

选股规则（详见 desktop MySQL 配置）：
- 流通市值 20-50 亿
- 排除 ST、次新（< 250 天）、非流动性股
- ROE_TTM > 5%、负债率 < 70%、商誉/净资产 < 50%
- 连续 2 年净利润为正
- 剔除 PB 最高 10%
- 按小市值、低 PB、短期动量、低波动做综合排序，取 N 只
- 月频调仓，单票上限 5%
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.data.storage import duckdb_query as dq
from research.universe import build, UniverseConfig
from .base import BaseStrategy, StrategyConfig, get_rebalance_dates
from .registry import register
from common.utils import get_logger
from tqdm import tqdm

log = get_logger("strategy.small_cap_quality")


class SmallCapQuality(BaseStrategy):

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
            min_listed_days=u.get("min_listed_days", 250),
            min_avg_amount=u.get("min_avg_amount", 20_000_000),
            min_total_mv=u.get("min_total_mv"),
            max_total_mv=u.get("max_total_mv", 50_000_000_000),
            max_20d_return=u.get("max_20d_return"),
            max_60d_return=u.get("max_60d_return"),
            max_amount_spike=u.get("max_amount_spike"),
            exclude_markets=["BJ"],   # 默认主策略不含北交所
        )

        rows = []
        for date in tqdm(rebalance_days, desc=f"select {cfg.name}", unit="period"):
            try:
                holdings = self._select(date, u_cfg, u, f, p)
            except Exception as e:
                log.warning(f"{date} 选股失败: {e}")
                continue
            if not holdings:
                continue
            n = len(holdings)
            weight = min(p.get("max_single_weight", 0.05), 1.0 / n)
            for code in holdings:
                rows.append({"trade_date": date, "ts_code": code, "weight": weight})

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df.pivot(index="trade_date", columns="ts_code", values="weight").fillna(0.0)

    # ------------------------------------------------------------------
    def _select(self, date: str, u_cfg: UniverseConfig,
                u: dict, f: dict, p: dict) -> list[str]:
        codes = build(date, u_cfg)
        if not codes:
            return []
        codes_sql = ",".join(f"'{c}'" for c in codes)

        min_mv = u.get("min_circ_mv", 2_000_000_000) / 10_000   # daily_basic 中 circ_mv 单位是万元
        max_mv = u.get("max_circ_mv", 5_000_000_000) / 10_000

        # 1) 流通市值 + PB 过滤（来自 daily_basic）
        df = dq.sql(f"""
            SELECT ts_code, circ_mv, pb, pe_ttm
            FROM read_parquet('{dq.RAW_DIR / "daily_basic" / "*.parquet"}')
            WHERE trade_date = '{date}'
              AND ts_code IN ({codes_sql})
              AND circ_mv BETWEEN {min_mv} AND {max_mv}
              AND pb IS NOT NULL AND pb > 0
        """)
        if df.empty:
            return []

        # 剔除 PB 最高 10%
        drop_top = f.get("drop_pb_top_pct", 0.10)
        if drop_top > 0:
            cutoff = df["pb"].quantile(1 - drop_top)
            df = df[df["pb"] <= cutoff]

        # 2) 财务质量过滤
        ann_start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
        codes_left_sql = ",".join(f"'{c}'" for c in df["ts_code"].tolist())

        # ROE_TTM 与负债率 - 取每只股票最新一期数据
        fin = dq.sql(f"""
            SELECT ts_code, ann_date, end_date, roe, debt_to_assets
            FROM read_parquet('{dq.RAW_DIR / "fina_indicator" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{date}'
              AND ts_code IN ({codes_left_sql})
        """)
        if not fin.empty:
            fin = (fin.sort_values(["ts_code", "ann_date"])
                      .groupby("ts_code").tail(1))
            min_roe = f.get("min_roe_ttm", 0.05) * 100  # tushare 单位是 %
            max_debt = f.get("max_debt_ratio", 0.70) * 100
            fin = fin[(fin["roe"].fillna(-999) >= min_roe) &
                      (fin["debt_to_assets"].fillna(999) <= max_debt)]
            df = df[df["ts_code"].isin(fin["ts_code"])]
        if df.empty:
            return []

        # 商誉 / 净资产
        codes_left_sql = ",".join(f"'{c}'" for c in df["ts_code"].tolist())
        bs = dq.sql(f"""
            SELECT ts_code, ann_date, goodwill, total_hldr_eqy_exc_min_int AS equity
            FROM read_parquet('{dq.RAW_DIR / "balancesheet" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{date}'
              AND ts_code IN ({codes_left_sql})
              AND total_hldr_eqy_exc_min_int > 0
        """)
        if not bs.empty:
            bs = bs.sort_values(["ts_code", "ann_date"]).groupby("ts_code").tail(1)
            bs["gw_ratio"] = bs["goodwill"].fillna(0) / bs["equity"]
            max_gw = f.get("max_goodwill_to_equity", 0.50)
            ok = bs.loc[bs["gw_ratio"] <= max_gw, "ts_code"]
            df = df[df["ts_code"].isin(ok)]
        if df.empty:
            return []

        # 连续 N 年净利润为正
        n_years = int(f.get("min_consecutive_profit_years", 2))
        if n_years > 0:
            df = self._filter_consecutive_profit(df, date, n_years)
        if df.empty:
            return []

        df = self._score_candidates(df, date, f)
        n_hold = int(p.get("n_holdings", 25))
        return df.head(n_hold)["ts_code"].tolist()

    # ------------------------------------------------------------------
    def _filter_consecutive_profit(self, df: pd.DataFrame, date: str, n_years: int) -> pd.DataFrame:
        """要求最近 n_years 个年度（12-31 报告期）净利润为正。"""
        codes_sql = ",".join(f"'{c}'" for c in df["ts_code"].tolist())
        ann_start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=365 * (n_years + 2))).strftime("%Y%m%d")
        inc = dq.sql(f"""
            SELECT ts_code, end_date, n_income_attr_p
            FROM read_parquet('{dq.RAW_DIR / "income" / "*.parquet"}')
            WHERE ann_date >= '{ann_start}' AND ann_date <= '{date}'
              AND end_date LIKE '%1231'
              AND ts_code IN ({codes_sql})
        """)
        if inc.empty:
            return df
        inc = (inc.sort_values(["ts_code", "end_date"])
                  .drop_duplicates(["ts_code", "end_date"], keep="last"))

        ok_codes = []
        for code, g in inc.groupby("ts_code"):
            recent = g.tail(n_years)
            if len(recent) >= n_years and (recent["n_income_attr_p"].fillna(-1) > 0).all():
                ok_codes.append(code)
        return df[df["ts_code"].isin(ok_codes)]

    def _score_candidates(self, df: pd.DataFrame, date: str, f: dict) -> pd.DataFrame:
        """过滤后的横截面综合打分。

        默认仍以小市值为主，但加入估值、近 20 日相对强度和低波动，避免只押单一小市值暴露。
        """
        weights = f.get("score_weights") or {
            "small_size": 0.45,
            "low_pb": 0.25,
            "momentum_20d": 0.20,
            "low_vol_20d": 0.10,
        }
        out = df.copy()
        out["score"] = 0.0

        def add_rank(col: str, weight: float, ascending: bool) -> None:
            if weight == 0 or col not in out.columns:
                return
            s = out[col].replace([float("inf"), float("-inf")], pd.NA)
            if s.notna().sum() < 2:
                return
            out["score"] += s.rank(pct=True, ascending=ascending).fillna(0.5) * weight

        add_rank("circ_mv", float(weights.get("small_size", 0.0)), ascending=False)
        add_rank("pb", float(weights.get("low_pb", 0.0)), ascending=False)

        prices = self._recent_price_features(out["ts_code"].tolist(), date)
        if not prices.empty:
            out = out.merge(prices, on="ts_code", how="left")
            add_rank("ret_20d", float(weights.get("momentum_20d", 0.0)), ascending=True)
            add_rank("vol_20d", float(weights.get("low_vol_20d", 0.0)), ascending=False)

        return out.sort_values(["score", "circ_mv"], ascending=[False, True])

    @staticmethod
    def _recent_price_features(codes: list[str], date: str) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()
        codes_sql = ",".join(f"'{c}'" for c in codes)
        pad = (datetime.strptime(date, "%Y%m%d") - timedelta(days=80)).strftime("%Y%m%d")
        px = dq.sql(f"""
            SELECT d.trade_date, d.ts_code, d.close * a.adj_factor AS adj_close
            FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
            JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
              ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
            WHERE d.trade_date >= '{pad}' AND d.trade_date <= '{date}'
              AND d.ts_code IN ({codes_sql})
        """)
        if px.empty:
            return pd.DataFrame()
        wide = px.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
        ret = wide.pct_change(20).iloc[-1]
        vol = wide.pct_change().rolling(20).std().iloc[-1]
        return pd.DataFrame({
            "ts_code": wide.columns,
            "ret_20d": ret.reindex(wide.columns).values,
            "vol_20d": vol.reindex(wide.columns).values,
        })


@register("small_cap_quality", "小盘质量")
def build_strategy() -> SmallCapQuality:
    cfg = StrategyConfig.from_yaml("small_cap_quality")
    return SmallCapQuality(cfg)
