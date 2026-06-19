from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    category: str = "general"
    description: str = ""
    lookback_days: int = 0
    enabled: bool = True


class FactorRegistry:
    def __init__(self, factors: Iterable[FactorDefinition] = ()) -> None:
        self._factors = {factor.name: factor for factor in factors}

    def register(self, factor: FactorDefinition) -> None:
        self._factors[factor.name] = factor

    def get(self, name: str) -> FactorDefinition:
        return self._factors[name]

    def names(self, *, enabled_only: bool = True) -> list[str]:
        items = self._factors.values()
        if enabled_only:
            items = [item for item in items if item.enabled]
        return sorted(item.name for item in items)

    def metadata(self) -> list[dict[str, object]]:
        return [
            {
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "lookback_days": item.lookback_days,
                "enabled": item.enabled,
            }
            for item in sorted(self._factors.values(), key=lambda factor: factor.name)
        ]


@dataclass(frozen=True)
class FeatureSetDefinition:
    feature_set_id: str
    strategy_id: str
    factor_names: tuple[str, ...]
    description: str = ""
    preprocess: str = "none"


class FeatureSetRegistry:
    def __init__(self, feature_sets: Iterable[FeatureSetDefinition] = ()) -> None:
        self._feature_sets = {item.feature_set_id: item for item in feature_sets}

    def register(self, feature_set: FeatureSetDefinition) -> None:
        self._feature_sets[feature_set.feature_set_id] = feature_set

    def get(self, feature_set_id: str) -> FeatureSetDefinition:
        return self._feature_sets[feature_set_id]

    def all(self) -> list[FeatureSetDefinition]:
        return [self._feature_sets[key] for key in sorted(self._feature_sets)]
