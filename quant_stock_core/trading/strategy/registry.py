"""策略插件注册中心。

桌面生产链路已经收口到收益擂台；这里仅保留历史研究/回测工具需要的
归档策略构造能力。新增策略不会自动进入桌面生产链路。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

# name -> {"label": str, "factory": Callable[[], BaseStrategy]}
_REGISTRY: dict[str, dict] = {}
_DISCOVERED = False

ACTIVE_UNIVERSE = [
    "ml_factor_ranker",
]


def register(name: str, label: str | None = None):
    """装饰器：把策略工厂函数登记到注册中心。

    用法：
        @register("ml_factor_ranker", "机器学习因子")
        def build_strategy():
            ...
    """
    def _deco(factory: Callable):
        _REGISTRY[name] = {"label": label or name, "factory": factory}
        return factory
    return _deco


def _discover() -> None:
    """惰性导入 trading/strategy/ 下所有策略模块，触发 @register 注册。

    跳过基础设施模块（base / combiner / registry / __init__）。
    采用惰性导入避免与策略模块产生循环依赖。
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    import importlib

    skip = {"base", "combiner", "registry", "research_universe", "__init__"}
    pkg_dir = Path(__file__).parent
    for f in sorted(pkg_dir.glob("*.py")):
        mod = f.stem
        if mod in skip or mod.startswith("_"):
            continue
        importlib.import_module(f"{__package__}.{mod}")
    importlib.import_module(f"{__package__}.research_universe")
    _DISCOVERED = True


def all_names() -> list[str]:
    """返回当前账户可交易、可参与训练/评估的策略名。"""
    _discover()
    return [name for name in ACTIVE_UNIVERSE if name in _REGISTRY]


def get_factory(name: str) -> Callable:
    """返回指定策略的工厂函数。"""
    _discover()
    if name not in _REGISTRY:
        raise KeyError(f"未注册的策略：{name}（已注册：{list(_REGISTRY)}）")
    return _REGISTRY[name]["factory"]


def build(name: str):
    """构造并返回指定策略实例。"""
    return get_factory(name)()


def get_label(name: str) -> str:
    """返回指定策略的中文标签；未注册则回退为名字本身。"""
    _discover()
    entry = _REGISTRY.get(name)
    return entry["label"] if entry else name


def labels() -> dict[str, str]:
    """返回当前可交易策略名到中文标签的映射。"""
    _discover()
    return {name: _REGISTRY[name]["label"] for name in all_names()}
