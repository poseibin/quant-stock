"""Research strategy universe.

These strategy names are the desktop-facing research taxonomy.  Several of
them intentionally reuse mature first-generation selectors underneath, then
combine or gate them so the evaluation layer can optimize a cleaner strategy
universe instead of exposing every raw plugin directly.
"""
from __future__ import annotations

import pandas as pd

from .base import BaseStrategy, StrategyConfig
from .beijing_se import BeijingSE
from .dividend_low_vol import DividendLowVol
from .forecast_revision import ForecastRevision
from .garp_quality import GarpQuality
from .industry_rotation import IndustryRotation
from .insider_buy import InsiderBuy
from .lhb_follow import LhbFollow
from .moneyflow_pullback import MoneyflowPullback
from .registry import register
from .reversal import Reversal
from .small_cap_quality import SmallCapQuality
from .trend_quality import TrendQuality
from . import combiner


def _normalize(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return panel
    row_sum = panel.abs().sum(axis=1).replace(0, pd.NA)
    return panel.div(row_sum, axis=0).fillna(0.0)


def _combine_weight_panels(panels: list[tuple[pd.DataFrame, float]]) -> pd.DataFrame:
    usable = [(panel, float(weight)) for panel, weight in panels if not panel.empty and float(weight) > 0]
    if not usable:
        return pd.DataFrame()
    all_dates = sorted(set().union(*[set(panel.index) for panel, _ in usable]))
    all_codes = sorted(set().union(*[set(panel.columns) for panel, _ in usable]))
    out = pd.DataFrame(0.0, index=all_dates, columns=all_codes)
    total = sum(weight for _, weight in usable)
    for panel, weight in usable:
        out = out + _normalize(panel).reindex(index=all_dates, columns=all_codes).ffill().fillna(0.0) * (weight / total)
    return out


class MarketRegimeTiming(BaseStrategy):
    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        base = SmallCapQuality(StrategyConfig.from_yaml("small_cap_quality")).generate_target_weights(start, end)
        if base.empty:
            return base
        regime = self.cfg.filters.get("market_regime") or {}
        if not regime:
            return base
        risk = {"market_regime": {"enabled": True, **regime}}
        return combiner._apply_market_regime(base, risk)  # noqa: SLF001


class MultiFactorComposite(BaseStrategy):
    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        weights = self.cfg.selection.get("component_weights") or {
            "small_cap_quality": 0.30,
            "trend_pullback": 0.25,
            "dividend_quality": 0.20,
            "earnings_revision": 0.15,
            "industry_prosperity": 0.10,
        }
        components: dict[str, BaseStrategy] = {
            "small_cap_quality": SmallCapQuality(StrategyConfig.from_yaml("small_cap_quality")),
            "trend_pullback": TrendPullback(StrategyConfig.from_yaml("trend_pullback")),
            "dividend_quality": DividendQuality(StrategyConfig.from_yaml("dividend_quality")),
            "earnings_revision": EarningsRevision(StrategyConfig.from_yaml("earnings_revision")),
            "industry_prosperity": IndustryProsperity(StrategyConfig.from_yaml("industry_prosperity")),
        }
        panels = []
        for name, weight in weights.items():
            strategy = components.get(str(name))
            if strategy is None:
                continue
            panels.append((strategy.generate_target_weights(start, end), float(weight)))
        return _combine_weight_panels(panels)


class TrendPullback(TrendQuality):
    pass


class DividendQuality(DividendLowVol):
    pass


class EarningsRevision(ForecastRevision):
    pass


class IndustryProsperity(IndustryRotation):
    pass


class LowCrowdingReversal(Reversal):
    pass


class EventEnhanced(BaseStrategy):
    def generate_target_weights(self, start: str, end: str) -> pd.DataFrame:
        panels = [
            (ForecastRevision(self.cfg).generate_target_weights(start, end), 0.35),
            (MoneyflowPullback(self.cfg).generate_target_weights(start, end), 0.30),
            (InsiderBuy(self.cfg).generate_target_weights(start, end), 0.20),
            (LhbFollow(self.cfg).generate_target_weights(start, end), 0.15),
        ]
        return _combine_weight_panels(panels)


class BeijingSatellite(BeijingSE):
    pass


@register("market_regime_timing", "市场状态择时")
def build_market_regime_timing():
    return MarketRegimeTiming(StrategyConfig.from_yaml("market_regime_timing"))


@register("multi_factor_composite", "多因子综合")
def build_multi_factor_composite():
    return MultiFactorComposite(StrategyConfig.from_yaml("multi_factor_composite"))


@register("trend_pullback", "趋势回撤")
def build_trend_pullback():
    return TrendPullback(StrategyConfig.from_yaml("trend_pullback"))


@register("dividend_quality", "红利质量")
def build_dividend_quality():
    return DividendQuality(StrategyConfig.from_yaml("dividend_quality"))


@register("earnings_revision", "盈利预期修正")
def build_earnings_revision():
    return EarningsRevision(StrategyConfig.from_yaml("earnings_revision"))


@register("industry_prosperity", "行业景气")
def build_industry_prosperity():
    return IndustryProsperity(StrategyConfig.from_yaml("industry_prosperity"))


@register("low_crowding_reversal", "低拥挤反转")
def build_low_crowding_reversal():
    return LowCrowdingReversal(StrategyConfig.from_yaml("low_crowding_reversal"))


@register("event_enhanced", "事件增强")
def build_event_enhanced():
    return EventEnhanced(StrategyConfig.from_yaml("event_enhanced"))


@register("beijing_satellite", "北交所卫星")
def build_beijing_satellite():
    return BeijingSatellite(StrategyConfig.from_yaml("beijing_satellite"))
