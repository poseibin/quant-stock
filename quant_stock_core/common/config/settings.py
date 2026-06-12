"""全局配置入口。

固定运行配置统一读取 quant_stock_core/config.toml。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "config.toml"
_CONFIG: Final[dict[str, Any]] = {}

if CONFIG_PATH.exists():
    try:
        import tomllib

        _CONFIG.update(tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except Exception:
        _CONFIG.clear()


def _section(name: str) -> dict[str, Any]:
    value = _CONFIG.get(name, {})
    return value if isinstance(value, dict) else {}


def _config_str(section: str, key: str, default: str = "") -> str:
    value = _section(section).get(key, default)
    return value.strip() if isinstance(value, str) else default


def _config_list(section: str, key: str) -> list[str]:
    value = _section(section).get(key, [])
    if isinstance(value, list):
        return [str(item).strip().lstrip("@") for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().lstrip("@") for item in value.replace("，", ",").replace("\n", ",").split(",") if item.strip()]
    return []


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
TUSHARE_TOKEN: Final[str] = _config_str("data", "tushare_token")
DEEPSEEK_TOKEN: Final[str] = _config_str("deepseek", "token")
DEEPSEEK_MODEL: Final[str] = _config_str("deepseek", "model", "deepseek-v4-pro")

# ---------------------------------------------------------------------------
# 存储路径
# ---------------------------------------------------------------------------
DATA_ROOT: Final[Path] = Path(_config_str("storage", "data_root", str(PROJECT_ROOT.parent / "data_store"))).resolve()
RAW_DIR: Final[Path] = DATA_ROOT / "raw"
FACTOR_CACHE_DIR: Final[Path] = DATA_ROOT / "factor_cache"
BACKTEST_DIR: Final[Path] = DATA_ROOT / "backtest_results"
LOG_DIR: Final[Path] = DATA_ROOT / "logs"

for _p in (RAW_DIR, FACTOR_CACHE_DIR, BACKTEST_DIR, LOG_DIR):
    _p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 数据表与分区策略
# ---------------------------------------------------------------------------
# raw 数据按 dataset 分目录，按年（或单文件）落地为 parquet
DATASETS = {
    "stock_basic":   {"partition": "single"},   # 全量小表，单文件覆盖
    "trade_cal":     {"partition": "single"},
    "daily":         {"partition": "year"},     # 行情，按 trade_date 年分区
    "daily_basic":   {"partition": "year"},
    "adj_factor":    {"partition": "year"},
    "income":        {"partition": "year"},     # 财务，按 ann_date 年分区
    "balancesheet":  {"partition": "year"},
    "cashflow":      {"partition": "year"},
    "fina_indicator": {"partition": "year"},
    "forecast":      {"partition": "year"},
    "top10_holders": {"partition": "year"},
    "stk_holdertrade": {"partition": "year"},
    "top_list":      {"partition": "year"},
    "top_inst":      {"partition": "year"},
}


# ---------------------------------------------------------------------------
# 数据起始日期
# ---------------------------------------------------------------------------
DATA_START_DATE: Final[str] = "20100101"


# ---------------------------------------------------------------------------
# 交易成本（回测用）
# ---------------------------------------------------------------------------
COMMISSION_RATE: Final[float] = 0.00025          # 双边万 2.5
STAMP_TAX_RATE: Final[float]  = 0.0005           # 卖出印花税万 5
DEFAULT_SLIPPAGE: Final[float] = 0.002           # 默认滑点 0.2%
SMALL_CAP_SLIPPAGE: Final[float] = 0.003         # 小市值滑点 0.3%


# ---------------------------------------------------------------------------
# 通用常量
# ---------------------------------------------------------------------------
TRADING_DAYS_PER_YEAR: Final[int] = 244
PRICE_LIMIT_PCT: Final[float] = 0.10              # 主板涨跌停 10%
ST_PRICE_LIMIT_PCT: Final[float] = 0.05           # ST 涨跌停 5%
KCB_GEM_LIMIT_PCT: Final[float] = 0.20            # 科创板/创业板 20%
BJ_LIMIT_PCT: Final[float] = 0.30                 # 北交所 30%


# ---------------------------------------------------------------------------
# 推送
# ---------------------------------------------------------------------------
DINGTALK_WEBHOOK: Final[str] = _config_str("dingtalk", "webhook")
WECHAT_WEBHOOK:   Final[str] = _config_str("wechat", "webhook")
WECHAT_USERS:     Final[list[str]] = _config_list("wechat", "users")


def ensure_token() -> str:
    """确保 Tushare Token 已配置，否则给出明确报错。"""
    if not TUSHARE_TOKEN:
        raise RuntimeError(
            "Tushare token 未配置：请复制 config.example.toml 为 config.toml，并在 [data].tushare_token 填入 token"
        )
    return TUSHARE_TOKEN
