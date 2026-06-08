"""策略基类"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from common.config.desktop_settings import load_strategy


@dataclass
class StrategyConfig:
    name: str
    enabled: bool = True
    weight: float = 1.0
    rebalance: str = "monthly"          # daily / weekly / monthly / quarterly / event
    universe: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    selection: dict = field(default_factory=dict)
    position: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, name: str, path: str | None = None) -> "StrategyConfig":
        """Load strategy settings from desktop SQLite.

        The method name is kept for compatibility with existing strategy
        factories; ``path`` is ignored because SQLite is now the source.
        """
        d = load_strategy(name)
        return cls(
            name=name,
            enabled=d.get("enabled", True),
            weight=d.get("weight", 1.0),
            rebalance=d.get("rebalance", "monthly"),
            universe=d.get("universe", {}) or {},
            filters=d.get("filters", {}) or {},
            selection=d.get("selection", {}) or {},
            position=d.get("position", {}) or {},
        )


class BaseStrategy(ABC):
    """策略基类。

    每个策略需实现：
    - generate_target_weights(start, end) -> DataFrame[trade_date x ts_code]
        index 为调仓日，行内权重之和 ≤ 1
    """

    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg

    @abstractmethod
    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 调仓日工具
# ---------------------------------------------------------------------------
def get_rebalance_dates(start: str, end: str, freq: str) -> list[str]:
    """生成调仓日序列。"""
    from research.data.storage.duckdb_query import get_trade_dates

    all_days = get_trade_dates(start, end)
    if not all_days:
        return []
    if freq == "daily":
        return all_days
    df = pd.DataFrame({"d": all_days})
    df["dt"] = pd.to_datetime(df["d"])
    if freq == "weekly":
        iso = df["dt"].dt.isocalendar()
        df["k"] = iso.year.astype(str) + "-" + iso.week.astype(str).str.zfill(2)
    elif freq == "monthly":
        df["k"] = df["dt"].dt.to_period("M").astype(str)
    elif freq == "quarterly":
        df["k"] = df["dt"].dt.to_period("Q").astype(str)
    else:
        return all_days
    # 取每个分组的最后一个交易日
    return df.groupby("k", sort=False)["d"].last().tolist()
