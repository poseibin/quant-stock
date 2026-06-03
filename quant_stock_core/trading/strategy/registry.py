"""策略插件注册中心

通过 @register 装饰器自动登记策略，消除散落各处的硬编码策略清单。

新增一个策略只需：
1. 在 trading/strategy/ 下新建一个 .py 文件；
2. 实现 build_strategy() 工厂函数，并加 @register("策略名", "中文标签") 装饰器；
3. 在 desktop 配置页中加一段同名配置。

注册即生效，无需再改 combiner / run_backtest / 测试。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

# name -> {"label": str, "factory": Callable[[], BaseStrategy]}
_REGISTRY: dict[str, dict] = {}
_DISCOVERED = False


def register(name: str, label: str | None = None):
    """装饰器：把策略工厂函数登记到注册中心。

    用法：
        @register("small_cap_quality", "小盘质量")
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

    skip = {"base", "combiner", "registry", "__init__"}
    pkg_dir = Path(__file__).parent
    for f in sorted(pkg_dir.glob("*.py")):
        mod = f.stem
        if mod in skip or mod.startswith("_"):
            continue
        importlib.import_module(f"{__package__}.{mod}")
    _DISCOVERED = True


def all_names() -> list[str]:
    """返回所有已注册的策略名。"""
    _discover()
    return list(_REGISTRY.keys())


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
    """返回 策略名到中文标签 的映射。"""
    _discover()
    return {n: v["label"] for n, v in _REGISTRY.items()}
