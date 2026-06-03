"""交易成本模型"""
from __future__ import annotations

from dataclasses import dataclass

from common.config import COMMISSION_RATE, STAMP_TAX_RATE, DEFAULT_SLIPPAGE


@dataclass
class CostModel:
    commission: float = COMMISSION_RATE   # 双边佣金率
    stamp_tax: float = STAMP_TAX_RATE     # 卖出印花税
    slippage: float = DEFAULT_SLIPPAGE    # 滑点（双边）

    def buy_cost(self, amount: float) -> float:
        """买入产生的总成本（佣金 + 滑点造成的成交价上浮）。"""
        return amount * (self.commission + self.slippage)

    def sell_cost(self, amount: float) -> float:
        """卖出产生的总成本（佣金 + 印花税 + 滑点）。"""
        return amount * (self.commission + self.stamp_tax + self.slippage)

    def round_trip_cost_pct(self) -> float:
        """单次买入卖出（往返）的总成本率。"""
        return (self.commission + self.slippage) * 2 + self.stamp_tax
