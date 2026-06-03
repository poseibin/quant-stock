"""股票池构建器

将多个过滤器组合，对外提供单一入口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from research.data.storage import duckdb_query as dq
from . import filters as F


@dataclass
class UniverseConfig:
    profile: str = "default"                                      # default / retail_edge
    exclude_st: bool = True
    exclude_delisted: bool = True
    min_listed_days: int = 250
    min_avg_amount: float = 20_000_000
    avg_amount_window: int = 20
    min_total_mv: float | None = None                             # 元
    max_total_mv: float | None = None                             # 元
    min_circ_mv: float | None = None                              # 元
    max_circ_mv: float | None = None                              # 元
    max_20d_return: float | None = None
    max_60d_return: float | None = None
    max_amount_spike: float | None = None
    exclude_markets: list[str] = field(default_factory=list)   # 例如 ["BJ"]
    keep_markets: list[str] | None = None                      # 例如 ["BJ"] 仅北交所
    require_tradable: bool = False                             # 是否要求当日可成交


def build(date: str, cfg: UniverseConfig | None = None) -> list[str]:
    """构建某日股票池。"""
    cfg = cfg or UniverseConfig()
    cfg = _apply_profile_defaults(cfg)
    basic = dq.get_stock_basic()
    codes = basic["ts_code"].tolist()

    if cfg.exclude_delisted:
        codes = F.exclude_delisted(codes, date)
    if cfg.min_listed_days > 0:
        codes = F.exclude_new_listing(codes, date, cfg.min_listed_days)
    if cfg.exclude_st:
        codes = F.exclude_st(codes)
    if cfg.keep_markets:
        codes = F.keep_market(codes, cfg.keep_markets)
    if cfg.exclude_markets:
        codes = F.exclude_market(codes, cfg.exclude_markets)
    if cfg.min_avg_amount > 0:
        codes = F.filter_min_avg_amount(codes, date, cfg.min_avg_amount,
                                        cfg.avg_amount_window)
    if any(v is not None for v in (cfg.min_total_mv, cfg.max_total_mv, cfg.min_circ_mv, cfg.max_circ_mv)):
        codes = F.filter_market_cap(
            codes,
            date,
            min_total_mv=cfg.min_total_mv,
            max_total_mv=cfg.max_total_mv,
            min_circ_mv=cfg.min_circ_mv,
            max_circ_mv=cfg.max_circ_mv,
        )
    if cfg.max_20d_return is not None:
        codes = F.filter_recent_return(codes, date, window=20, max_return=cfg.max_20d_return)
    if cfg.max_60d_return is not None:
        codes = F.filter_recent_return(codes, date, window=60, max_return=cfg.max_60d_return)
    if cfg.max_amount_spike is not None:
        codes = F.filter_amount_spike(codes, date, window=cfg.avg_amount_window, max_spike=cfg.max_amount_spike)
    if cfg.require_tradable:
        codes = F.filter_tradable(date, codes)
    return codes


def retail_edge_config(**overrides) -> UniverseConfig:
    """机构避让股票池：小资金可交易、低覆盖概率更高、容量不过度拥挤。"""
    return UniverseConfig(profile="retail_edge", **overrides)


def _apply_profile_defaults(cfg: UniverseConfig) -> UniverseConfig:
    if cfg.profile != "retail_edge":
        return cfg
    if cfg.min_total_mv is None:
        cfg.min_total_mv = 2_000_000_000
    if cfg.max_total_mv is None:
        cfg.max_total_mv = 80_000_000_000
    if cfg.min_avg_amount <= 0:
        cfg.min_avg_amount = 20_000_000
    if cfg.max_20d_return is None:
        cfg.max_20d_return = 0.35
    if cfg.max_60d_return is None:
        cfg.max_60d_return = 0.80
    if cfg.max_amount_spike is None:
        cfg.max_amount_spike = 5.0
    if "BJ" not in cfg.exclude_markets and not cfg.keep_markets:
        cfg.exclude_markets.append("BJ")
    cfg.require_tradable = True
    return cfg
