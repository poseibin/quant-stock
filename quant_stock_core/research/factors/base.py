"""因子基类与计算引擎

设计要点：
- BaseFactor 是所有因子的抽象基类
- compute(date) 返回某日的横截面 Series：index=ts_code, value=因子值
- compute_panel(start, end) 返回时间序列面板：DataFrame[trade_date, ts_code, value]
- 自动 parquet 缓存，避免重复计算
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pandas as pd

from common.config import FACTOR_CACHE_DIR
from common.utils import get_logger

log = get_logger("factor.base")


@dataclass
class FactorMeta:
    name: str
    category: str            # value / quality / momentum / size / liquidity / event
    direction: int = 1       # 1=值越大越好, -1=值越小越好
    description: str = ""
    deps: list[str] = field(default_factory=list)


class BaseFactor(ABC):
    """因子基类。

    子类必须：
    - 设置 meta（FactorMeta）
    - 实现 _compute_panel(start, end) 返回 long-format DataFrame
      列：[trade_date, ts_code, value]
    """
    meta: ClassVar[FactorMeta]

    # ---------- 缓存 ----------
    def cache_path(self) -> Path:
        d = FACTOR_CACHE_DIR / self.meta.name
        d.mkdir(parents=True, exist_ok=True)
        return d / "panel.parquet"

    def load_cache(self) -> pd.DataFrame | None:
        p = self.cache_path()
        if p.exists():
            try:
                return pd.read_parquet(p)
            except Exception as e:
                log.warning(f"读取因子缓存失败 {p}: {e}")
        return None

    def save_cache(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        p = self.cache_path()
        tmp = p.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, compression="zstd", index=False)
        tmp.replace(p)

    def invalidate_cache(self) -> None:
        p = self.cache_path()
        if p.exists():
            p.unlink()

    # ---------- 计算 ----------
    @abstractmethod
    def _compute_panel(self, start: str, end: str) -> pd.DataFrame:
        """子类实现：返回 [trade_date, ts_code, value]"""
        raise NotImplementedError

    def compute_panel(self, start: str, end: str, *, use_cache: bool = True) -> pd.DataFrame:
        """计算时间序列面板，自动复用缓存。

        若请求区间不完全命中缓存，则重算请求区间，并与旧缓存按
        ``trade_date, ts_code`` 合并去重，避免新请求覆盖历史缓存。
        """
        cached = self.load_cache() if use_cache else None
        if cached is not None and not cached.empty:
            cached["trade_date"] = cached["trade_date"].astype(str)
            cmin, cmax = cached["trade_date"].min(), cached["trade_date"].max()
            if cmin <= start and cmax >= end:
                return cached[
                    (cached["trade_date"] >= start) & (cached["trade_date"] <= end)
                ].reset_index(drop=True)
            log.info(f"{self.meta.name} 缓存范围不全，补算并合并 [{start}, {end}]")

        df = self._compute_panel(start, end)
        if df is None:
            df = pd.DataFrame(columns=["trade_date", "ts_code", "value"])
        if "value" not in df.columns:
            raise ValueError(f"{self.meta.name} 必须返回 value 列")
        df = df.dropna(subset=["value"])
        if not df.empty:
            df["trade_date"] = df["trade_date"].astype(str)

        if use_cache:
            merged = self._merge_cache(cached, df)
            self.save_cache(merged)
            if not merged.empty:
                return merged[
                    (merged["trade_date"] >= start) & (merged["trade_date"] <= end)
                ].reset_index(drop=True)
        return df

    @staticmethod
    def _merge_cache(cached: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
        if cached is None or cached.empty:
            return new
        if new is None or new.empty:
            return cached
        merged = pd.concat([cached, new], ignore_index=True)
        merged["trade_date"] = merged["trade_date"].astype(str)
        merged = merged.drop_duplicates(subset=["trade_date", "ts_code"], keep="last")
        return merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    def compute(self, date: str) -> pd.Series:
        """单日横截面。"""
        df = self.compute_panel(date, date)
        if df.empty:
            return pd.Series(dtype=float, name=self.meta.name)
        s = df.set_index("ts_code")["value"]
        s.name = self.meta.name
        return s


def _next(date: str) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")


def _prev(date: str) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def to_panel_wide(long_df: pd.DataFrame) -> pd.DataFrame:
    """long [trade_date, ts_code, value] -> wide [trade_date x ts_code]"""
    if long_df.empty:
        return pd.DataFrame()
    return long_df.pivot(index="trade_date", columns="ts_code", values="value")
