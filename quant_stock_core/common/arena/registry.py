from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .framework import ArenaChallengeManager, ArenaRunContext, ensure_arena_definitions_table, upsert_arena_definition


@dataclass(frozen=True)
class ArenaStrategyDefinition:
    strategy_id: str
    display_name: str
    artifact_dir_name: str
    default_arena_name: str
    run_table: str = ""
    evaluation_table: str = ""
    prediction_table: str = ""
    feature_table: str = ""

    def context(
        self,
        *,
        run_id: str,
        data_path: str | Path,
        arena_name: str | None = None,
        min_improvement: float = 0.0,
    ) -> ArenaRunContext:
        root = Path(data_path)
        return ArenaRunContext(
            strategy_id=self.strategy_id,
            run_id=str(run_id),
            data_path=root,
            artifact_dir=root / self.artifact_dir_name,
            arena_name=str(arena_name or self.default_arena_name),
            min_improvement=float(min_improvement or 0.0),
            display_name=self.display_name,
            artifact_dir_name=self.artifact_dir_name,
            tables=self.table_map(),
        )

    def manager(
        self,
        *,
        run_id: str,
        data_path: str | Path,
        arena_name: str | None = None,
        min_improvement: float = 0.0,
        progress_log: Callable[..., None] | None = None,
        now_fn: Callable[[], str] | None = None,
    ) -> ArenaChallengeManager:
        return ArenaChallengeManager(
            self.context(
                run_id=run_id,
                data_path=data_path,
                arena_name=arena_name,
                min_improvement=min_improvement,
            ),
            progress_log=progress_log,
            now_fn=now_fn,
        )

    def table_map(self) -> dict[str, str]:
        return {
            "run": self.run_table,
            "evaluation": self.evaluation_table,
            "prediction": self.prediction_table,
            "feature": self.feature_table,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "display_name": self.display_name,
            "artifact_dir_name": self.artifact_dir_name,
            "default_arena_name": self.default_arena_name,
            "tables": self.table_map(),
        }

    def observability_payload(
        self,
        *,
        run_id: str = "",
        arena_name: str | None = None,
        task_label: str | None = None,
    ) -> dict[str, Any]:
        active_arena = str(arena_name or self.default_arena_name)
        return {
            **self.metadata(),
            "run_id": str(run_id or ""),
            "arena_name": active_arena,
            "task_key": f"arena:{self.strategy_id}:{active_arena}",
            "task_label": str(task_label or f"{self.display_name} · 打擂训练"),
        }


class ArenaStrategyRegistry:
    def __init__(self, definitions: Iterable[ArenaStrategyDefinition] = ()) -> None:
        self._definitions = {item.strategy_id: item for item in definitions}

    def register(self, definition: ArenaStrategyDefinition) -> None:
        self._definitions[definition.strategy_id] = definition

    def get(self, strategy_id: str) -> ArenaStrategyDefinition:
        try:
            return self._definitions[str(strategy_id)]
        except KeyError as exc:
            known = ", ".join(sorted(self._definitions))
            raise KeyError(f"unknown arena strategy_id={strategy_id!r}; known={known}") from exc

    def all(self) -> list[ArenaStrategyDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions)]

    def ensure_registered(self, conn: Any, *, updated_at: str | None = None) -> None:
        ensure_arena_definitions_table(conn)
        now = updated_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        for definition in self.all():
            metadata = definition.observability_payload(arena_name=definition.default_arena_name)
            upsert_arena_definition(conn, metadata, now)


DEFAULT_ARENA_STRATEGIES = ArenaStrategyRegistry([
    ArenaStrategyDefinition(
        strategy_id="profit_arena_model",
        display_name="收益擂台",
        artifact_dir_name="profit_arena",
        default_arena_name="profit_nolev_rankic_sharpe_dd20_ann45",
        run_table="profit_arena_runs",
        evaluation_table="profit_arena_evaluations",
        prediction_table="profit_arena_predictions",
        feature_table="profit_arena_features",
    ),
])
