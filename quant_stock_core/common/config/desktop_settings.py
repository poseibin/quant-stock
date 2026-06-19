"""Desktop settings reader.

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

from common.infra.db import connect_db, table_exists, upsert_sql, write_transaction

from .settings import DATA_ROOT


def _default_settings() -> dict[str, Any]:
    return {
        "strategies": {
            "profit_arena_model": {
                "label": "收益擂台",
                "enabled": True,
                "weight": 1.0,
                "rebalance": "daily",
                "filters": {},
                "universe": {},
                "position": {"n_holdings": 10, "max_single_weight": 0.10},
            },
        },
        "portfolio_risk": {
            "max_industry_weight": 0.30, "max_single_weight": 0.05, "max_holdings": 50, "cash_buffer": 0.0, "blacklist": [],
            "market_regime": {"enabled": False, "trend_window": 60, "breadth_window": 20, "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.50, "bear_exposure": 0.30},
        },
        "exit_rules": {"enabled": True, "stop_loss": -0.12, "trailing_stop": -0.08, "trailing_exec": "next_open", "slippage": 0.003},
    }


def config_db_path() -> Path:
    # 保留兼容字段名；MySQL 模式下不使用文件数据库路径。
    return DATA_ROOT


def load_settings() -> dict[str, Any]:
    settings = _default_settings()
    db_path = config_db_path()
    try:
        with connect_db(db_path) as conn:
            row = conn.execute("SELECT value FROM cfg_app_settings WHERE `key` = ?", ("settings",)).fetchone()
    except Exception:
        return settings
    if not row:
        return settings
    try:
        loaded = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return settings
    return _normalize_desktop_settings(_deep_merge(settings, loaded))


def save_settings(settings: dict[str, Any]) -> None:
    payload = json.dumps(_normalize_desktop_settings(_deep_merge(_default_settings(), settings)), ensure_ascii=False)
    db_path = config_db_path()
    with write_transaction(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cfg_app_settings (
                `key` VARCHAR(255) PRIMARY KEY,
                value LONGTEXT NOT NULL,
                updated_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
        )
        columns = ["key", "value", "updated_at"]
        conn.execute(
            upsert_sql("cfg_app_settings", columns, ["key"], ["value", "updated_at"]),
            ("settings", payload, datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        )


def _normalize_desktop_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(settings or {})
    strategies = normalized.get("strategies")
    if isinstance(strategies, dict):
        arena = strategies.get("profit_arena_model") or strategies.get("profit_arena") or _default_settings()["strategies"]["profit_arena_model"]
        if not isinstance(arena, dict):
            arena = _default_settings()["strategies"]["profit_arena_model"]
        normalized["strategies"] = {
            "profit_arena_model": _deep_merge(_default_settings()["strategies"]["profit_arena_model"], arena)
        }
        normalized["strategies"]["profit_arena_model"]["enabled"] = True
        normalized["strategies"]["profit_arena_model"]["weight"] = 1.0
    return normalized


def load_strategy_settings() -> dict[str, dict[str, Any]]:
    settings = _load_versioned_strategy_settings(deepcopy(load_settings().get("strategies", {}) or {}))
    for name, override in _strategy_overrides().items():
        normalized_name = "profit_arena_model" if name == "profit_arena" else name
        if normalized_name != "profit_arena_model":
            continue
        if isinstance(override, dict) and isinstance(settings.get("profit_arena_model"), dict):
            settings["profit_arena_model"] = _deep_merge(settings["profit_arena_model"], override)
    return _normalize_desktop_settings({"strategies": settings})["strategies"]


def load_strategy(name: str) -> dict[str, Any]:
    strategies = load_strategy_settings()
    if name not in strategies:
        raise KeyError(f"cfg_app_settings.settings.strategies 中未找到 {name}")
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
