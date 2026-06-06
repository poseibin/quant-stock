"""Desktop SQLite settings reader.

The desktop app stores runtime settings in cfg_app_settings(key='settings').
Python workers read the same row so strategy configuration has one source.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from common.infra.db import connect_db, db_backend, table_exists, upsert_sql, write_transaction

from .settings import DATA_ROOT


def _default_settings() -> dict[str, Any]:
    return {
        "strategies": {
            "market_regime_timing": {
                "label": "市场状态择时", "enabled": True, "weight": 0.10, "rebalance": "weekly",
                "filters": {"market_regime": {"trend_window": 60, "breadth_window": 20, "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.50, "bear_exposure": 0.25}},
                "position": {"n_holdings": 25, "max_single_weight": 0.05},
            },
            "ml_factor_ranker": {
                "label": "机器学习因子", "enabled": False, "weight": 0.10, "rebalance": "monthly",
                "universe": {"exclude_bj": True, "min_total_mv": 2_000_000_000, "max_total_mv": 120_000_000_000, "min_amount": 30_000_000},
                "filters": {
                    "exclude_st": True, "max_day_return": 0.095,
                    "market_regime": {
                        "continuous": False, "trend_window": 60, "breadth_window": 20,
                        "drawdown_window": 120, "volatility_window": 20,
                        "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.45, "bear_exposure": 0.25,
                    },
                },
                "selection": {"run_id": "fr_full_105_2010_2025_20260606", "min_pred_rank": 0.96},
                "position": {"n_holdings": 30, "max_single_weight": 0.04, "max_industry_weight": 0.15},
            },
            "multi_factor_composite": {
                "label": "多因子综合", "enabled": True, "weight": 0.18, "rebalance": "monthly",
                "selection": {"component_weights": {"small_cap_quality": 0.30, "trend_pullback": 0.25, "dividend_quality": 0.20, "earnings_revision": 0.15, "industry_prosperity": 0.10}},
                "position": {"n_holdings": 30, "max_single_weight": 0.05},
            },
            "momentum_quality_guard": {
                "label": "动量质量护栏", "enabled": True, "weight": 0.14, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 30_000_000, "min_total_mv": 2_000_000_000, "max_total_mv": 120_000_000_000, "max_20d_return": 0.30, "max_amount_spike": 4.0},
                "filters": {
                    "min_momentum_score": 0.75, "min_quality_score": 0.55, "max_short_return": 0.30,
                    "max_debt_ratio": 0.75, "min_value_guard_score": 0.35,
                    "market_regime": {"trend_window": 60, "breadth_window": 20, "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.55, "bear_exposure": 0.25},
                },
                "position": {"n_holdings": 24, "max_single_weight": 0.05, "max_industry_weight": 0.30},
            },
            "quality_growth_cooldown": {
                "label": "质量成长冷却", "enabled": True, "weight": 0.10, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 30_000_000, "min_total_mv": 2_000_000_000, "max_total_mv": 120_000_000_000, "max_20d_return": 0.25, "max_amount_spike": 4.0},
                "filters": {
                    "min_quality_score": 0.70, "min_growth_score": 0.65, "max_short_return": 0.25,
                    "max_vol_20": 0.70, "max_debt_ratio": 0.75, "min_value_guard_score": 0.30,
                    "market_regime": {"trend_window": 60, "breadth_window": 20, "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.55, "bear_exposure": 0.25},
                },
                "position": {"n_holdings": 24, "max_single_weight": 0.05, "max_industry_weight": 0.30},
            },
            "small_cap_quality": {
                "label": "小盘质量", "enabled": True, "weight": 0.30, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_circ_mv": 2_000_000_000, "max_circ_mv": 5_000_000_000, "max_total_mv": 50_000_000_000, "min_listed_days": 250, "min_avg_amount": 20_000_000, "max_20d_return": 0.35, "max_amount_spike": 5.0},
                "filters": {
                    "exclude_st": True, "exclude_delist_warn": True, "min_roe_ttm": 0.05, "max_debt_ratio": 0.70,
                    "max_goodwill_to_equity": 0.50, "min_consecutive_profit_years": 2, "drop_pb_top_pct": 0.10,
                    "score_weights": {"small_size": 0.45, "low_pb": 0.25, "momentum_20d": 0.20, "low_vol_20d": 0.10},
                },
                "position": {"n_holdings": 25, "max_single_weight": 0.05},
            },
            "trend_pullback": {
                "label": "趋势回撤", "enabled": True, "weight": 0.12, "rebalance": "weekly",
                "universe": {"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 50_000_000, "avg_amount_window": 20, "max_total_mv": 80_000_000_000, "max_20d_return": 0.30, "max_amount_spike": 4.0},
                "filters": {"exclude_st": True, "long_window": 120, "mid_window": 60, "short_window": 20, "min_mid_return": 0.06, "max_short_return": 0.18, "min_roe": 0.06, "max_debt_ratio": 0.75, "score_weights": {"trend": 0.38, "breakout": 0.17, "liquidity": 0.15, "low_vol": 0.15, "quality": 0.15}},
                "position": {"n_holdings": 18, "max_single_weight": 0.05, "max_industry_weight": 0.30},
            },
            "turtle_breakout": {
                "label": "海龟突破", "enabled": True, "weight": 0.08, "rebalance": "daily",
                "universe": {"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 50_000_000, "min_total_mv": 2_000_000_000, "max_total_mv": 120_000_000_000, "max_20d_return": 0.45, "max_amount_spike": 5.0},
                "filters": {"entry_window": 55, "exit_window": 20, "atr_window": 20, "trend_window": 120},
                "position": {"n_holdings": 20, "max_units": 4, "risk_per_unit": 0.006, "max_unit_weight": 0.02, "max_single_weight": 0.06, "max_total_exposure": 1.0, "add_atr_step": 0.5, "stop_atr": 2.0},
            },
            "dividend_quality": {
                "label": "红利质量", "enabled": True, "weight": 0.10, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_listed_days": 730, "min_avg_amount": 30_000_000, "avg_amount_window": 20, "min_total_mv": 5_000_000_000, "max_total_mv": 120_000_000_000, "max_20d_return": 0.25, "max_amount_spike": 4.0},
                "filters": {"exclude_st": True, "min_total_mv": 8_000_000_000, "min_dv_ttm": 2.0, "max_pb": 3.0, "vol_window": 60, "min_roe": 0.07, "max_debt_ratio": 0.70, "score_weights": {"dividend": 0.35, "low_vol": 0.25, "low_pb": 0.15, "quality": 0.20, "liquidity": 0.05}},
                "position": {"n_holdings": 20, "max_single_weight": 0.05, "max_industry_weight": 0.25},
            },
            "earnings_revision": {
                "label": "盈利预期修正", "enabled": True, "weight": 0.10, "rebalance": "event",
                "filters": {"min_profit_growth": 25.0, "min_turnaround_profit": 20_000_000, "max_post_ann_return": 0.15, "max_pe_ttm": 70.0, "max_pb": 7.0, "min_total_mv": 2_000_000_000, "max_total_mv": 80_000_000_000, "min_avg_amount": 20_000_000, "lookback_days": 20, "holding_days": 35},
                "position": {"max_single_weight": 0.04, "max_active_events": 20},
            },
            "industry_prosperity": {
                "label": "行业景气", "enabled": True, "weight": 0.10, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_listed_days": 250, "min_avg_amount": 30_000_000, "max_total_mv": 120_000_000_000, "max_20d_return": 0.30, "max_amount_spike": 4.0},
                "selection": {"top_n_industries": 4, "momentum_window": 20, "rank_within_industry": [3, 10], "stocks_per_industry": 3, "min_industry_size": 5},
                "position": {"n_holdings": 12, "max_single_weight": 0.05},
            },
            "low_crowding_reversal": {
                "label": "低拥挤反转", "enabled": True, "weight": 0.10, "rebalance": "quarterly",
                "filters": {"exclude_st": True, "universe_profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 20_000_000, "max_total_mv": 80_000_000_000, "max_20d_return": 0.25, "min_yoy_revenue": 0.0, "min_quarter_profit_yoy": 0.20, "last_year_negative_or_decline": 0.50, "min_cfo_to_ni_ratio": 0.50, "industry_60d_return_min": -0.05},
                "position": {"n_holdings": 15, "max_single_weight": 0.06, "max_industry_weight": 0.30},
            },
            "event_enhanced": {
                "label": "事件增强", "enabled": False, "weight": 0.06, "rebalance": "event",
                "filters": {"min_profit_growth": 25.0, "min_turnaround_profit": 20_000_000, "min_net_amount": 30_000_000, "min_amount_rate": 1.0, "min_inst_net_buy": 50_000_000, "min_increase_amount": 10_000_000, "min_avg_to_current_price_ratio": 0.95, "max_post_ann_return": 0.15, "max_event_day_return": 6.0, "max_event_day_return_cap": 6.0, "min_total_mv": 2_000_000_000, "max_total_mv": 80_000_000_000, "min_avg_amount": 20_000_000, "entry_wait_days": 5, "max_pullback_from_event_close": -0.03, "min_60d_return": 0.10, "holding_days": 10},
                "position": {"max_single_weight": 0.03, "max_active_events": 20},
            },
            "beijing_satellite": {
                "label": "北交所卫星", "enabled": False, "weight": 0.04, "rebalance": "monthly",
                "universe": {"market": "BJ", "min_avg_amount": 5_000_000},
                "filters": {"min_yoy_profit": 0.0, "max_60d_return": 0.25},
                "position": {"n_holdings": 10, "max_single_weight": 0.06},
            },
            "insider_buy": {
                "label": "高管增持", "enabled": True, "weight": 0.20, "rebalance": "event",
                "filters": {"min_increase_amount": 10_000_000, "min_avg_to_current_price_ratio": 0.95, "max_post_ann_return": 0.20, "min_total_mv": 2_000_000_000, "max_total_mv": 80_000_000_000, "min_avg_amount": 20_000_000, "max_20d_return": 0.35, "holding_days_min": 30, "holding_days_max": 60},
                "position": {"max_single_weight": 0.05, "stop_loss": -0.15},
            },
            "lhb_follow": {
                "label": "龙虎榜", "enabled": True, "weight": 0.10, "rebalance": "event",
                "filters": {"min_inst_net_buy": 50_000_000, "exclude_limit_up": True, "max_5d_return": 0.15, "holding_days": 7},
                "position": {"max_single_weight": 0.04, "stop_loss_break_5d_low": True},
            },
            "trend_quality": {
                "label": "趋势质量", "enabled": False, "weight": 0.12, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 50_000_000, "avg_amount_window": 20, "max_total_mv": 80_000_000_000, "max_20d_return": 0.35, "max_amount_spike": 5.0},
                "filters": {
                    "exclude_st": True, "long_window": 120, "mid_window": 60, "short_window": 20,
                    "min_mid_return": 0.08, "max_short_return": 0.25, "min_roe": 0.06, "max_debt_ratio": 0.75,
                    "score_weights": {"trend": 0.45, "breakout": 0.20, "liquidity": 0.15, "low_vol": 0.10, "quality": 0.10},
                },
                "position": {"n_holdings": 18, "max_single_weight": 0.05, "max_industry_weight": 0.30},
            },
            "garp_quality": {
                "label": "质量成长", "enabled": False, "weight": 0.12, "rebalance": "monthly",
                "universe": {"profile": "retail_edge", "min_listed_days": 730, "min_avg_amount": 40_000_000, "max_total_mv": 80_000_000_000, "max_20d_return": 0.35, "max_amount_spike": 5.0},
                "filters": {
                    "exclude_st": True, "max_pe_ttm": 60.0, "max_pb": 8.0, "max_ps_ttm": 12.0,
                    "min_roe": 0.08, "min_gross_margin": 0.15, "min_revenue_yoy": 0.08, "min_profit_yoy": 0.08,
                },
                "position": {"n_holdings": 20, "max_single_weight": 0.05, "max_industry_weight": 0.30},
            },
            "moneyflow_pullback": {
                "label": "资金低吸", "enabled": False, "weight": 0.08, "rebalance": "event",
                "filters": {
                    "min_net_amount": 30_000_000, "min_amount_rate": 1.0,
                    "max_event_day_return": 9.5, "max_event_day_return_cap": 6.0,
                    "max_amount_rate": 200.0, "min_turnover_rate": 0.0, "max_turnover_rate": 100.0,
                    "min_inst_net_buy": -1_000_000_000_000, "max_inst_net_buy": 1_000_000_000_000,
                    "min_total_mv": 2_000_000_000, "max_total_mv": 80_000_000_000,
                    "entry_wait_days": 5, "min_pullback_from_event_close": -1.00,
                    "max_pullback_from_event_close": -0.03,
                    "max_dist_to_20d_high": 0.06, "max_dist_to_20d_high_cap": 0.06,
                    "min_close_to_ma20": 0.0, "min_close_to_ma60": 0.0,
                    "min_60d_return": 0.10, "min_60d_return_floor": 0.10, "holding_days": 10,
                },
                "position": {"max_single_weight": 0.04, "max_active_events": 15},
            },
        },
        "portfolio_risk": {
            "max_industry_weight": 0.30, "max_single_weight": 0.05, "max_holdings": 50, "cash_buffer": 0.0, "blacklist": [],
            "market_regime": {"enabled": False, "trend_window": 60, "breadth_window": 20, "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.50, "bear_exposure": 0.30},
        },
        "exit_rules": {"enabled": True, "stop_loss": -0.12, "trailing_stop": -0.08, "trailing_exec": "next_open", "slippage": 0.003},
    }


def config_db_path() -> Path:
    env = os.getenv("DESKTOP_CONFIG_DB_PATH", "").strip() or os.getenv("DESKTOP_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (DATA_ROOT / "meta.db").resolve()


def load_settings() -> dict[str, Any]:
    settings = _default_settings()
    db_path = config_db_path()
    if db_backend() == "sqlite" and not db_path.exists():
        return settings
    try:
        with connect_db(db_path) as conn:
            row = conn.execute("SELECT value FROM cfg_app_settings WHERE key = ?", ("settings",)).fetchone()
    except Exception:
        return settings
    if not row:
        return settings
    try:
        loaded = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return settings
    return _deep_merge(settings, loaded)


def save_settings(settings: dict[str, Any]) -> None:
    payload = json.dumps(_deep_merge(_default_settings(), settings), ensure_ascii=False)
    db_path = config_db_path()
    if db_backend() == "sqlite":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    with write_transaction(db_path) as conn:
        if conn.backend == "mysql":
            conn.execute(
                """CREATE TABLE IF NOT EXISTS cfg_app_settings (
                    `key` VARCHAR(255) PRIMARY KEY,
                    value LONGTEXT NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cfg_app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        columns = ["key", "value", "updated_at"]
        conn.execute(
            upsert_sql("cfg_app_settings", columns, ["key"], ["value", "updated_at"]),
            ("settings", payload, datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        )


def load_strategy_settings() -> dict[str, dict[str, Any]]:
    settings = _load_versioned_strategy_settings(deepcopy(load_settings().get("strategies", {}) or {}))
    for name, override in _strategy_overrides().items():
        if isinstance(override, dict) and isinstance(settings.get(name), dict):
            settings[name] = _deep_merge(settings[name], override)
    return settings


def load_strategy(name: str) -> dict[str, Any]:
    strategies = load_strategy_settings()
    if name not in strategies:
        raise KeyError(f"SQLite cfg_app_settings.settings.strategies 中未找到 {name}")
    return deepcopy(strategies[name])


def load_portfolio_risk() -> dict[str, Any]:
    return deepcopy(load_settings().get("portfolio_risk", {}) or {})


def load_exit_rules() -> dict[str, Any]:
    return deepcopy(load_settings().get("exit_rules", {}) or {})


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _strategy_overrides() -> dict[str, Any]:
    raw = os.getenv("QUANT_STRATEGY_OVERRIDES_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _load_versioned_strategy_settings(base: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    db_path = config_db_path()
    if db_backend() == "sqlite" and not db_path.exists():
        return base
    mode = os.getenv("QUANT_STRATEGY_VERSION_MODE", "active").strip().lower() or "active"
    version_spec = _strategy_version_spec()
    try:
        with connect_db(db_path) as conn:
            if not table_exists(conn, "strategy_config_versions"):
                return base
            out = deepcopy(base)
            for name, default_cfg in base.items():
                row = None
                version = version_spec.get(name)
                if version is not None:
                    row = conn.execute(
                        "SELECT version, config_json FROM strategy_config_versions WHERE strategy = ? AND version = ?",
                        (name, int(version)),
                    ).fetchone()
                elif mode == "latest":
                    row = conn.execute(
                        "SELECT version, config_json FROM strategy_config_versions WHERE strategy = ? ORDER BY version DESC LIMIT 1",
                        (name,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT version, config_json FROM strategy_config_versions WHERE strategy = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
                        (name,),
                    ).fetchone()
                if not row:
                    continue
                try:
                    loaded = json.loads(row[1])
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(loaded, dict):
                    cfg = _deep_merge(default_cfg, loaded)
                    cfg["_version"] = int(row[0])
                    cfg["_version_mode"] = "specified" if name in version_spec else mode
                    out[name] = cfg
            return out
    except Exception:
        return base


def _strategy_version_spec() -> dict[str, int]:
    raw = os.getenv("QUANT_STRATEGY_VERSION_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, int] = {}
    for name, version in parsed.items():
        try:
            out[str(name)] = int(version)
        except (TypeError, ValueError):
            continue
    return out
