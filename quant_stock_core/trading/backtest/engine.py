"""向量化回测引擎

设计要点：
- 输入：每个调仓日的目标持仓权重（DataFrame[trade_date x ts_code]）
- 自动处理：T+1（信号 t 日产生，t+1 开盘买入）、涨跌停过滤、停牌、复权、成本
- 输出：每日组合收益、净值、持仓、换手率
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from tqdm import tqdm

from research.data.storage import duckdb_query as dq
from .cost_model import CostModel
from .metrics import summary as metric_summary


@dataclass
class BacktestConfig:
    start: str
    end: str
    initial_cash: float = 1_000_000
    cost: CostModel = None
    benchmark: str | None = None     # 例如 "000300.SH"
    allow_partial_fill: bool = True  # 涨跌停 / 停牌时是否跳过该笔交易（保留前一日权重）
    progress: bool = True            # 是否显示进度条

    def __post_init__(self):
        if self.cost is None:
            self.cost = CostModel()


@dataclass
class BacktestResult:
    returns: pd.Series                 # 日度收益率
    equity: pd.Series                  # 净值
    weights: pd.DataFrame              # 实际持仓权重（每日）
    target_weights: pd.DataFrame       # 目标权重（调仓日）
    summary: dict
    benchmark: pd.Series | None = None


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _load_price_panel(
    start: str,
    end: str,
    ts_codes: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """加载回测所需价格面板。

    Returns:
        adj_close: 前复权收盘价 [date x code]
        adj_open:  前复权开盘价  [date x code]
        can_buy:   当日开盘是否可以买入 bool [date x code]
        can_sell:  当日开盘是否可以卖出 bool [date x code]
    """
    if not ts_codes:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    codes_sql = ",".join(f"'{c}'" for c in ts_codes)
    df = dq.sql(f"""
        SELECT d.trade_date, d.ts_code,
               d.open  * a.adj_factor AS adj_open,
               d.close * a.adj_factor AS adj_close,
               d.open, d.high, d.low, d.close, d.pre_close, d.vol,
               sb.name, sb.market, sb.exchange, sb.list_date, sb.delist_date
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}') d
        JOIN read_parquet('{dq.RAW_DIR / "adj_factor" / "*.parquet"}') a
          ON d.ts_code = a.ts_code AND d.trade_date = a.trade_date
        LEFT JOIN read_parquet('{dq.RAW_DIR / "stock_basic" / "*.parquet"}') sb
          ON d.ts_code = sb.ts_code
        WHERE d.trade_date >= '{start}' AND d.trade_date <= '{end}'
          AND d.ts_code IN ({codes_sql})
    """)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    adj_close = df.pivot(index="trade_date", columns="ts_code", values="adj_close").sort_index()
    adj_open = df.pivot(index="trade_date", columns="ts_code", values="adj_open").sort_index()

    base_tradable = (df["vol"] > 0) & (df["high"] != df["low"])
    limit_pct = _price_limit_pct(df)
    limit_up_price = (df["pre_close"] * (1 + limit_pct)).round(2)
    limit_down_price = (df["pre_close"] * (1 - limit_pct)).round(2)
    tolerance = 0.001
    limit_up = df["open"] >= limit_up_price * (1 - tolerance)
    limit_down = df["open"] <= limit_down_price * (1 + tolerance)
    df["can_buy"] = base_tradable & (~limit_up)
    df["can_sell"] = base_tradable & (~limit_down)

    can_buy = df.pivot(index="trade_date", columns="ts_code", values="can_buy").fillna(False)
    can_sell = df.pivot(index="trade_date", columns="ts_code", values="can_sell").fillna(False)
    return adj_close, adj_open, can_buy, can_sell


def _price_limit_pct(df: pd.DataFrame) -> pd.Series:
    """按 A 股历史交易制度估计个股当日涨跌停幅度。

    规则近似：
    - IPO 初期无涨跌幅限制：主板上市首个交易日；科创/创业/北交所前 5 个交易日
    - 退市整理期：统一近似 10%
    - ST / *ST: 5%
    - 科创板：2019-07-22 后 20%
    - 创业板：2020-08-24 后 20%，之前 10%
    - 北交所：2021-11-15 后 30%，之前按精选层近似 30%
    - 其他主板：10%
    """
    ts_code = df["ts_code"].astype(str)
    trade_date = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    list_date = pd.to_datetime(
        df.get("list_date", pd.Series("", index=df.index)).astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    delist_date = pd.to_datetime(
        df.get("delist_date", pd.Series("", index=df.index)).astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    name = df.get("name", pd.Series("", index=df.index)).fillna("").astype(str)
    market = df.get("market", pd.Series("", index=df.index)).fillna("").astype(str)
    exchange = df.get("exchange", pd.Series("", index=df.index)).fillna("").astype(str)

    pct = pd.Series(0.10, index=df.index, dtype=float)
    is_st = name.str.contains("ST", na=False)
    is_bj = exchange.eq("BSE") | market.str.contains("北交所", na=False) | ts_code.str.endswith(".BJ")
    is_kcb = market.str.contains("科创", na=False) | ts_code.str.startswith("688")
    is_gem = market.str.contains("创业", na=False) | ts_code.str.startswith("300") | ts_code.str.startswith("301")

    kcb_20 = is_kcb & (trade_date >= pd.Timestamp("2019-07-22"))
    gem_20 = is_gem & (trade_date >= pd.Timestamp("2020-08-24"))
    bj_30 = is_bj & (trade_date >= pd.Timestamp("2021-11-15"))

    pct.loc[kcb_20 | gem_20] = 0.20
    pct.loc[bj_30 | is_bj] = 0.30
    pct.loc[is_st] = 0.05

    delist_window = delist_date.notna() & (trade_date <= delist_date) & ((delist_date - trade_date).dt.days <= 30)
    pct.loc[delist_window] = 0.10

    listed_trading_days = _listed_trading_day_number(df)
    mainboard_ipo_free = (~is_kcb & ~is_gem & ~is_bj) & (listed_trading_days == 1)
    registration_ipo_free = (is_kcb | gem_20 | is_bj) & (listed_trading_days >= 1) & (listed_trading_days <= 5)
    pct.loc[mainboard_ipo_free | registration_ipo_free] = np.inf
    return pct


def _listed_trading_day_number(df: pd.DataFrame) -> pd.Series:
    """计算每只股票自上市日起的第几个有行情交易日（首日=1）。"""
    tmp = df[["ts_code", "trade_date", "list_date"]].copy()
    tmp["trade_date"] = tmp["trade_date"].astype(str)
    tmp["list_date"] = tmp["list_date"].astype(str)
    tmp = tmp.sort_values(["ts_code", "trade_date"])
    valid = tmp["list_date"].notna() & (tmp["list_date"] != "") & (tmp["trade_date"] >= tmp["list_date"])
    out = pd.Series(np.nan, index=tmp.index, dtype=float)
    out.loc[valid] = tmp.loc[valid].groupby("ts_code").cumcount() + 1
    return out.reindex(df.index)


# ---------------------------------------------------------------------------
# 主回测函数
# ---------------------------------------------------------------------------
def run(target_weights: pd.DataFrame, cfg: BacktestConfig) -> BacktestResult:
    """运行向量化回测。

    target_weights: index=调仓日（trade_date），columns=ts_code，值为目标权重。
                   不必每天都有，缺失行表示该日无调仓（沿用前一日权重）。
    """
    if target_weights.empty:
        raise ValueError("目标权重为空")

    target_weights = target_weights.copy()
    target_weights.index = target_weights.index.astype(str)
    target_weights = target_weights.sort_index()

    all_codes = sorted(target_weights.columns.tolist())
    adj_close, adj_open, can_buy, can_sell = _load_price_panel(cfg.start, cfg.end, all_codes)
    if adj_close.empty:
        raise ValueError("没有可用价格数据，请先更新行情")

    trade_dates = adj_close.index.tolist()
    target_full = target_weights.reindex(trade_dates).ffill().fillna(0.0)
    target_full = target_full.reindex(columns=all_codes, fill_value=0.0)

    actual = pd.DataFrame(0.0, index=trade_dates, columns=all_codes)
    daily_ret = pd.Series(0.0, index=trade_dates, name="ret")
    cost_pct = cfg.cost.commission + cfg.cost.slippage
    sell_cost_pct = cfg.cost.commission + cfg.cost.slippage + cfg.cost.stamp_tax

    prev_weights = pd.Series(0.0, index=all_codes)

    iterator = enumerate(trade_dates)
    if cfg.progress:
        iterator = tqdm(iterator, total=len(trade_dates), desc="backtest", unit="day")

    for i, date in iterator:
        if i == 0:
            actual.loc[date] = prev_weights.values
            continue

        prev_date = trade_dates[i - 1]
        target_exec = target_full.loc[prev_date]

        prev_close = adj_close.loc[prev_date].reindex(all_codes)
        open_price = adj_open.loc[date].reindex(all_codes)
        close_price = adj_close.loc[date].reindex(all_codes)

        overnight_ret = (open_price / prev_close - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        intraday_ret = (close_price / open_price - 1).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        cash_weight = max(0.0, 1.0 - float(prev_weights.sum()))
        open_positions_value = prev_weights * (1 + overnight_ret)
        equity_open = float(open_positions_value.sum() + cash_weight)
        if equity_open <= 0:
            current_open_weights = pd.Series(0.0, index=all_codes)
            equity_open = 1.0
        else:
            current_open_weights = open_positions_value / equity_open

        desired_delta = target_exec - current_open_weights
        can_buy_today = can_buy.loc[date].reindex(all_codes, fill_value=False)
        can_sell_today = can_sell.loc[date].reindex(all_codes, fill_value=False)
        executable = ((desired_delta > 0) & can_buy_today) | ((desired_delta < 0) & can_sell_today) | (desired_delta == 0)
        delta = desired_delta.where(executable, 0.0)

        executed_weights = current_open_weights + delta
        buy_amount = float(delta.clip(lower=0).sum())
        sell_amount = float(-delta.clip(upper=0).sum())
        trade_cost = buy_amount * cost_pct + sell_amount * sell_cost_pct

        post_trade_cash = 1.0 - float(executed_weights.sum()) - trade_cost
        if post_trade_cash < 0:
            scale = max(0.0, 1.0 - trade_cost) / max(float(executed_weights.sum()), 1e-12)
            executed_weights = executed_weights * min(1.0, scale)
            post_trade_cash = max(0.0, 1.0 - float(executed_weights.sum()) - trade_cost)

        close_positions_value = executed_weights * (1 + intraday_ret)
        equity_close_rel = float(close_positions_value.sum() + post_trade_cash)
        daily_ret.loc[date] = equity_open * equity_close_rel - 1.0

        if equity_close_rel > 0:
            close_weights = close_positions_value / equity_close_rel
        else:
            close_weights = pd.Series(0.0, index=all_codes)
        actual.loc[date] = close_weights.values
        prev_weights = close_weights

    equity = (1 + daily_ret).cumprod()

    # 基准
    bench = None
    if cfg.benchmark:
        bench = _load_benchmark(cfg.benchmark, cfg.start, cfg.end)

    summary = metric_summary(daily_ret, weights=actual, benchmark=bench)

    return BacktestResult(
        returns=daily_ret,
        equity=equity,
        weights=actual,
        target_weights=target_weights,
        summary=summary,
        benchmark=bench,
    )


def _load_benchmark(code: str, start: str, end: str) -> pd.Series:
    """加载基准指数日收益率。优先 daily 表，其次后续可换 AKShare。"""
    df = dq.sql(f"""
        SELECT trade_date, close
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE ts_code = '{code}'
          AND trade_date >= '{start}' AND trade_date <= '{end}'
        ORDER BY trade_date
    """)
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("trade_date")["close"]
    return s.pct_change().fillna(0.0)
