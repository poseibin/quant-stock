"""多策略组合器

按 desktop SQLite 配置中的权重，把各子策略的目标持仓加权合成。
"""
from __future__ import annotations

import pandas as pd

from common.config.desktop_settings import load_strategy_settings
from research.data.storage import duckdb_query as dq
from .base import BaseStrategy
from . import registry


def load_all(path: str | None = None,
             enabled_only_for: list[str] | None = None,
             force_names: list[str] | None = None) -> list[BaseStrategy]:
    """读取 desktop SQLite 中已启用的策略实例。

    策略经由 strategy/registry.py 的 @register 装饰器自动注册，
    无需在此维护硬编码清单。

    enabled_only_for: 若给定，则只加载列表中的策略（其余即便 enabled 也跳过），
                      用于「单策略隔离回测」。
    force_names:      显式指定要参与的策略名（来自「新增评估」勾选的插件）。
                      命中的策略即便 SQLite 配置中 enabled=false 也会被强制加载，
                      让用户可以自由选择任意已注册插件参与本次评估。
    """
    cfg = load_strategy_settings()

    registered = set(registry.all_names())
    filter_set = set(enabled_only_for) if enabled_only_for else None
    force_set = set(force_names) if force_names else set()
    out = []
    for name, conf in cfg.items():
        if not isinstance(conf, dict):
            continue
        if name not in registered:
            continue
        forced = name in force_set
        if not forced and not conf.get("enabled", False):
            continue
        if filter_set is not None and name not in filter_set:
            continue
        out.append(registry.build(name))
    return out


def combine(
    strategies: list[BaseStrategy],
    start: str,
    end: str,
    *,
    portfolio_risk: dict | None = None,
    progress_cb=None,
    return_attribution: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """合并多个策略的目标权重。

    每个子策略在自身体系内权重 ≤ 1，最终按 cfg.weight 缩放后相加。
    再做组合层风控。

    progress_cb: 可选回调 fn(idx, total, name, stage)，stage in {"start","done"}
    return_attribution: 若 True，额外返回 {strategy_name: w_panel(已缩放)} 字典
    """
    if not strategies:
        if return_attribution:
            return pd.DataFrame(), {}
        return pd.DataFrame()

    panels = []
    attribution: dict[str, pd.DataFrame] = {}
    total = len(strategies)
    for i, s in enumerate(strategies):
        if progress_cb:
            progress_cb(i, total, s.cfg.name, "start")
        w_panel = s.generate_target_weights(start, end)
        if progress_cb:
            progress_cb(i, total, s.cfg.name, "done")
        if w_panel.empty:
            continue
        w_panel = w_panel * s.cfg.weight
        panels.append(w_panel)
        attribution[s.cfg.name] = w_panel

    if not panels:
        if return_attribution:
            return pd.DataFrame(), {}
        return pd.DataFrame()

    # 对齐索引
    all_dates = sorted(set().union(*[p.index for p in panels]))
    all_codes = sorted(set().union(*[p.columns for p in panels]))

    combined = pd.DataFrame(0.0, index=all_dates, columns=all_codes)
    for p in panels:
        p = p.reindex(index=all_dates, columns=all_codes).fillna(0.0)
        # 对策略层做前向填充，事件型策略每日权重已经填好；周期型只在调仓日
        p = p.ffill().fillna(0.0)
        combined = combined + p

    if portfolio_risk:
        combined = _apply_market_regime(combined, portfolio_risk)
        combined = _apply_portfolio_risk(combined, portfolio_risk)

    if return_attribution:
        return combined, attribution
    return combined


def _apply_portfolio_risk(weights: pd.DataFrame, risk: dict) -> pd.DataFrame:
    max_single = risk.get("max_single_weight", 0.05)
    max_holdings = int(risk.get("max_holdings") or 0)
    cash_buffer = risk.get("cash_buffer", 0.0)
    blacklist = set(risk.get("blacklist", []))

    if blacklist:
        keep_cols = [c for c in weights.columns if c not in blacklist]
        weights = weights[keep_cols]

    if max_holdings > 0 and len(weights.columns) > max_holdings:
        ranked = weights.rank(axis=1, method="first", ascending=False)
        weights = weights.where(ranked <= max_holdings, 0.0)

    # 单票上限
    weights = weights.clip(upper=max_single)

    # 目标总仓位（默认 1.0 即满仓）
    target_total = 1 - cash_buffer
    row_sum = weights.sum(axis=1)

    # 双向缩放：超出则压缩，不足则放大补到 target_total
    # 注意：放大时受 max_single 限制，可能放大后又被 clip，再循环一次确保贴近 target_total
    for _ in range(3):
        row_sum = weights.sum(axis=1)
        scale = pd.Series(1.0, index=weights.index)
        # 超出
        over = row_sum > target_total
        scale[over] = target_total / row_sum[over]
        # 不足（且本行有持仓才放大，全 0 行不动）
        under = (row_sum < target_total) & (row_sum > 0)
        scale[under] = target_total / row_sum[under]
        weights = weights.mul(scale, axis=0)
        # 放大后可能突破单票上限，再 clip
        weights = weights.clip(upper=max_single)
        # 收敛判定
        new_row_sum = weights.sum(axis=1)
        if (new_row_sum - target_total).abs().max() < 0.01:
            break

    return weights


def _apply_market_regime(weights: pd.DataFrame, risk: dict) -> pd.DataFrame:
    cfg = risk.get("market_regime")
    if not isinstance(cfg, dict) or not cfg.get("enabled", False) or weights.empty:
        return weights

    regimes = _market_regime_series(
        str(weights.index.min()),
        str(weights.index.max()),
        trend_window=int(cfg.get("trend_window", 60)),
        breadth_window=int(cfg.get("breadth_window", 20)),
        min_breadth=float(cfg.get("min_breadth", 0.45)),
    )
    if regimes.empty:
        return weights

    normal = float(cfg.get("normal_exposure", 1.0))
    weak = float(cfg.get("weak_exposure", 0.50))
    bear = float(cfg.get("bear_exposure", 0.30))
    scale = regimes.map({"normal": normal, "weak": weak, "bear": bear}).astype(float)
    scale = scale.reindex(weights.index).ffill().fillna(normal)
    return weights.mul(scale, axis=0)


def _market_regime_series(
    start: str,
    end: str,
    *,
    trend_window: int,
    breadth_window: int,
    min_breadth: float,
) -> pd.Series:
    pad_days = max(trend_window, breadth_window) * 3
    pad = (pd.to_datetime(start) - pd.Timedelta(days=pad_days)).strftime("%Y%m%d")
    df = dq.sql(f"""
        SELECT trade_date, ts_code, close
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date >= '{pad}' AND trade_date <= '{end}'
    """)
    if df.empty:
        return pd.Series(dtype=str)
    close = df.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
    if len(close) < max(trend_window, breadth_window) + 1:
        return pd.Series(dtype=str)
    market = close.pct_change().mean(axis=1).add(1).cumprod()
    trend = market / market.rolling(trend_window).mean() - 1
    breadth = (close > close.rolling(breadth_window).mean()).sum(axis=1) / close.notna().sum(axis=1)

    regime = pd.Series("normal", index=close.index)
    regime[(trend < 0) | (breadth < min_breadth)] = "weak"
    regime[(trend < -0.06) & (breadth < min_breadth * 0.8)] = "bear"
    return regime[regime.index >= start]
