from __future__ import annotations

import json
import math
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from common.infra.db import add_column, replace_sql, table_columns


ProgressLogger = Callable[[str], None]


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _safe_arena_name(value: str) -> str:
    text = str(value or "default")
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)


@dataclass(frozen=True)
class ArenaRunContext:
    strategy_id: str
    run_id: str
    data_path: Path
    artifact_dir: Path
    arena_name: str = "default"
    min_improvement: float = 0.0
    display_name: str = ""
    artifact_dir_name: str = ""
    tables: dict[str, str] | None = None


class StrategyPlugin(Protocol):
    """Contract for strategies that plug into the shared arena runner."""

    strategy_id: str

    def build_universe(self, context: ArenaRunContext) -> Any:
        ...

    def build_features(self, context: ArenaRunContext, universe: Any) -> Any:
        ...

    def train(self, context: ArenaRunContext, features: Any) -> Any:
        ...

    def predict(self, context: ArenaRunContext, model: Any, features: Any) -> Any:
        ...

    def evaluate(self, context: ArenaRunContext, predictions: Any) -> Sequence[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class ArenaChallengeRules:
    """Strategy-specific scoring and payload rules used by the shared arena runner."""

    score_components_fn: Callable[[dict[str, Any]], dict[str, Any]]
    score_key_fn: Callable[[dict[str, Any]], tuple[float, ...]]
    payload_fn: Callable[[dict[str, Any]], dict[str, Any]]
    comparable_payload_fn: Callable[[dict[str, Any]], dict[str, Any]]

    def score_components(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.score_components_fn(item)

    def score_key(self, item: dict[str, Any]) -> tuple[float, ...]:
        return self.score_key_fn(item)

    def payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.payload_fn(item)

    def comparable_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return self.comparable_payload_fn(item)


def arena_context_metadata(context: ArenaRunContext) -> dict[str, Any]:
    return {
        "strategy_id": context.strategy_id,
        "display_name": context.display_name or context.strategy_id,
        "run_id": context.run_id,
        "arena_name": context.arena_name,
        "artifact_dir_name": context.artifact_dir_name or context.artifact_dir.name,
        "artifact_dir": str(context.artifact_dir),
        "task_key": f"arena:{context.strategy_id}:{context.arena_name}",
        "task_label": f"{context.display_name or context.strategy_id} · 打擂训练",
        "tables": dict(context.tables or {}),
    }


def ensure_arena_definitions_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_arena_definitions (
            strategy_id VARCHAR(64) PRIMARY KEY,
            display_name VARCHAR(128) NOT NULL DEFAULT '',
            default_arena_name VARCHAR(128) NOT NULL DEFAULT '',
            artifact_dir_name VARCHAR(128) NOT NULL DEFAULT '',
            task_label VARCHAR(128) NOT NULL DEFAULT '',
            tables_json LONGTEXT,
            metadata_json LONGTEXT,
            updated_at VARCHAR(64) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def upsert_arena_definition(conn: Any, metadata: dict[str, Any], updated_at: str) -> None:
    columns = [
        "strategy_id", "display_name", "default_arena_name", "artifact_dir_name",
        "task_label", "tables_json", "metadata_json", "updated_at",
    ]
    conn.execute(
        replace_sql("strategy_arena_definitions", columns, ["strategy_id"]),
        (
            str(metadata.get("strategy_id") or ""),
            str(metadata.get("display_name") or ""),
            str(metadata.get("default_arena_name") or metadata.get("arena_name") or ""),
            str(metadata.get("artifact_dir_name") or ""),
            str(metadata.get("task_label") or ""),
            json.dumps(metadata.get("tables") or {}, ensure_ascii=False, sort_keys=True, default=str),
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
            updated_at,
        ),
    )


def simple_model_score_components(item: dict[str, Any]) -> dict[str, Any]:
    top_excess_return = _safe_float(item.get("top_excess_return"))
    top_return = _safe_float(item.get("top_return"))
    top_limit_up_rate = _safe_float(item.get("top_limit_up_rate"))
    top_hit_rate = _safe_float(item.get("top_hit_rate"))
    top_drawdown = _safe_float(item.get("top_drawdown"))
    rank_ic = _safe_float(item.get("rank_ic"))
    latest_count = int(item.get("latest_count", 0) or 0)
    candidate_rows = int(item.get("candidate_rows", item.get("rows", 0)) or 0)
    score = (
        top_excess_return * 10000.0
        + top_return * 5000.0
        + top_limit_up_rate * 200.0
        + top_hit_rate * 80.0
        + rank_ic * 120.0
        + min(latest_count, 200) * 0.02
        - abs(min(top_drawdown, 0.0)) * 250.0
    )
    failures: list[str] = []
    if candidate_rows < 5000:
        failures.append("min_candidate_rows")
    if latest_count <= 0:
        failures.append("latest_predictions")
    if top_excess_return <= 0:
        failures.append("positive_top_excess_return")
    if top_drawdown < -0.35:
        failures.append("max_top_drawdown")
    if rank_ic <= -0.02:
        failures.append("min_rank_ic")
    if not failures:
        arena_tier = 3
        arena_tier_name = "admissible_model"
    elif failures == ["positive_top_excess_return"]:
        arena_tier = 1
        arena_tier_name = "watchlist_model"
    else:
        arena_tier = 0
        arena_tier_name = "rejected"
    return {
        "score": _safe_float(score),
        "arena_tier": arena_tier,
        "arena_tier_name": arena_tier_name,
        "raw": {
            "top_excess_return": top_excess_return,
            "top_return": top_return,
            "top_limit_up_rate": top_limit_up_rate,
            "top_hit_rate": top_hit_rate,
            "top_drawdown": top_drawdown,
            "rank_ic": rank_ic,
            "latest_count": latest_count,
            "candidate_rows": candidate_rows,
        },
        "score_formula": {
            "name": "simple_top_return_excess_rankic_drawdown",
            "score": "10000*top_excess + 5000*top_return + 200*limit_up_rate + 80*hit_rate + 120*rank_ic + latest_count_bonus - 250*drawdown_abs",
        },
        "hard_gate_ok": not failures,
        "hard_gate_failures": failures,
        "penalties": {name: 0.0 for name in failures},
        "passed_gates": [
            name
            for name in (
                "min_candidate_rows",
                "latest_predictions",
                "positive_top_excess_return",
                "max_top_drawdown",
                "min_rank_ic",
            )
            if name not in failures
        ],
    }


def simple_model_score_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    components = simple_model_score_components(item)
    raw = components.get("raw") or {}
    return (
        _safe_float(components.get("score")),
        _safe_float(raw.get("top_excess_return")),
        _safe_float(raw.get("top_return")),
        _safe_float(raw.get("top_limit_up_rate")),
        _safe_float(raw.get("rank_ic")),
        _safe_float(raw.get("top_drawdown")),
    )


def simple_model_payload(item: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "scope",
        "horizon",
        "segment",
        "top_n",
        "top_k",
        "rows",
        "candidate_rows",
        "latest_date",
        "latest_count",
        "top_return",
        "top_excess_return",
        "top_hit_rate",
        "top_limit_up_rate",
        "top_drawdown",
        "rank_ic",
        "test_start",
        "test_end",
    ]
    return {key: item.get(key) for key in keys if key in item}


def simple_model_comparable_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = simple_model_payload(item)
    normalized: dict[str, Any] = {}
    numeric_keys = {
        "horizon",
        "top_n",
        "top_k",
        "rows",
        "candidate_rows",
        "latest_count",
        "top_return",
        "top_excess_return",
        "top_hit_rate",
        "top_limit_up_rate",
        "top_drawdown",
        "rank_ic",
    }
    for key, value in payload.items():
        if key in numeric_keys:
            normalized[key] = round(_safe_float(value), 12)
        else:
            normalized[key] = value
    return normalized


class ArenaChallengeManager:
    """Shared champion/history manager for arena-style strategy training."""

    def __init__(
        self,
        context: ArenaRunContext,
        *,
        progress_log: Callable[..., None] | None = None,
        now_fn: Callable[[], str] | None = None,
    ) -> None:
        self.context = context
        self.progress_log = progress_log or (lambda *_args, **_kwargs: None)
        self.now_fn = now_fn or (lambda: datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

    @property
    def champion_path(self) -> Path:
        safe_name = _safe_arena_name(self.context.arena_name)
        return self.context.artifact_dir / f"arena_champion_{safe_name}.json"

    @property
    def history_path(self) -> Path:
        safe_name = _safe_arena_name(self.context.arena_name)
        return self.context.artifact_dir / f"arena_history_{safe_name}.jsonl"

    def load_champion(self) -> dict[str, Any] | None:
        path = self.champion_path
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.progress_log(
                "arena_champion_load_error",
                run_id=self.context.run_id,
                strategy_id=self.context.strategy_id,
                path=str(path),
                error=str(exc),
            )
            return None

    def next_challenge_version(self) -> int:
        path = self.history_path
        if not path.exists():
            return 1
        last_version = 0
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    last_version = max(last_version, int(payload.get("challenge_version", 0) or 0))
        except Exception as exc:
            self.progress_log(
                "arena_history_read_error",
                run_id=self.context.run_id,
                strategy_id=self.context.strategy_id,
                path=str(path),
                error=str(exc),
            )
        return last_version + 1

    def append_history(self, record: dict[str, Any]) -> None:
        path = self.history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def ensure_tables(self, conn: Any) -> None:
        ensure_arena_definitions_table(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_arena_runs (
                strategy_id VARCHAR(64) NOT NULL,
                arena_name VARCHAR(128) NOT NULL,
                run_id VARCHAR(255) NOT NULL,
                start_date VARCHAR(16) NOT NULL DEFAULT '',
                end_date VARCHAR(16) NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT '',
                objective VARCHAR(128) NOT NULL DEFAULT '',
                model_type VARCHAR(128) NOT NULL DEFAULT '',
                best_scope VARCHAR(32) NOT NULL DEFAULT '',
                best_horizon BIGINT NOT NULL DEFAULT 0,
                best_top_n BIGINT NOT NULL DEFAULT 0,
                arena_score DOUBLE NOT NULL DEFAULT 0,
                champion_updated BIGINT NOT NULL DEFAULT 0,
                display_name VARCHAR(128) NOT NULL DEFAULT '',
                task_label VARCHAR(128) NOT NULL DEFAULT '',
                artifact_dir_name VARCHAR(128) NOT NULL DEFAULT '',
                metadata_json LONGTEXT,
                summary_json LONGTEXT,
                model_path VARCHAR(1024) NOT NULL DEFAULT '',
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(strategy_id, arena_name, run_id),
                KEY idx_strategy_arena_runs_latest (strategy_id, arena_name, updated_at),
                KEY idx_strategy_arena_runs_score (strategy_id, arena_name, arena_score)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        run_columns = table_columns(conn, "strategy_arena_runs")
        if "metadata_json" not in run_columns:
            add_column(conn, "strategy_arena_runs", "metadata_json", "LONGTEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_arena_evaluations (
                strategy_id VARCHAR(64) NOT NULL,
                arena_name VARCHAR(128) NOT NULL,
                run_id VARCHAR(255) NOT NULL,
                eval_id VARCHAR(64) NOT NULL,
                scope VARCHAR(32) NOT NULL DEFAULT '',
                horizon BIGINT NOT NULL DEFAULT 0,
                segment VARCHAR(32) NOT NULL DEFAULT '',
                top_n BIGINT NOT NULL DEFAULT 0,
                arena_score DOUBLE NOT NULL DEFAULT 0,
                annual_return DOUBLE NOT NULL DEFAULT 0,
                compound_return DOUBLE NOT NULL DEFAULT 0,
                max_drawdown DOUBLE NOT NULL DEFAULT 0,
                sharpe DOUBLE NOT NULL DEFAULT 0,
                capital_annual_return DOUBLE NOT NULL DEFAULT 0,
                capital_compound_return DOUBLE NOT NULL DEFAULT 0,
                capital_max_drawdown DOUBLE NOT NULL DEFAULT 0,
                capital_sharpe DOUBLE NOT NULL DEFAULT 0,
                rank_ic DOUBLE NOT NULL DEFAULT 0,
                rank_ic_days BIGINT NOT NULL DEFAULT 0,
                trade_count BIGINT NOT NULL DEFAULT 0,
                trade_years BIGINT NOT NULL DEFAULT 0,
                display_name VARCHAR(128) NOT NULL DEFAULT '',
                task_label VARCHAR(128) NOT NULL DEFAULT '',
                artifact_dir_name VARCHAR(128) NOT NULL DEFAULT '',
                metadata_json LONGTEXT,
                metrics_json LONGTEXT,
                config_json LONGTEXT,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(strategy_id, arena_name, run_id, eval_id),
                KEY idx_strategy_arena_eval_score (strategy_id, arena_name, arena_score),
                KEY idx_strategy_arena_eval_run (strategy_id, arena_name, run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        eval_table_columns = table_columns(conn, "strategy_arena_evaluations")
        if "metadata_json" not in eval_table_columns:
            add_column(conn, "strategy_arena_evaluations", "metadata_json", "LONGTEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_arena_champions (
                strategy_id VARCHAR(64) NOT NULL,
                arena_name VARCHAR(128) NOT NULL,
                champion_run_id VARCHAR(255) NOT NULL DEFAULT '',
                champion_version BIGINT NOT NULL DEFAULT 0,
                arena_score DOUBLE NOT NULL DEFAULT 0,
                qualification_status VARCHAR(32) NOT NULL DEFAULT '',
                champion_type VARCHAR(32) NOT NULL DEFAULT '',
                validation_status VARCHAR(32) NOT NULL DEFAULT '',
                display_name VARCHAR(128) NOT NULL DEFAULT '',
                task_label VARCHAR(128) NOT NULL DEFAULT '',
                artifact_dir_name VARCHAR(128) NOT NULL DEFAULT '',
                metadata_json LONGTEXT,
                champion_json LONGTEXT,
                updated_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(strategy_id, arena_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_arena_history (
                strategy_id VARCHAR(64) NOT NULL,
                arena_name VARCHAR(128) NOT NULL,
                challenge_version BIGINT NOT NULL DEFAULT 0,
                run_id VARCHAR(255) NOT NULL DEFAULT '',
                challenger_score DOUBLE NOT NULL DEFAULT 0,
                incumbent_score DOUBLE,
                updated BIGINT NOT NULL DEFAULT 0,
                challenger_tier BIGINT NOT NULL DEFAULT 0,
                challenger_tier_name VARCHAR(64) NOT NULL DEFAULT '',
                display_name VARCHAR(128) NOT NULL DEFAULT '',
                task_label VARCHAR(128) NOT NULL DEFAULT '',
                artifact_dir_name VARCHAR(128) NOT NULL DEFAULT '',
                metadata_json LONGTEXT,
                history_json LONGTEXT,
                challenged_at VARCHAR(64) NOT NULL,
                PRIMARY KEY(strategy_id, arena_name, challenge_version),
                KEY idx_strategy_arena_history_run (strategy_id, arena_name, run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        champion_columns = table_columns(conn, "strategy_arena_champions")
        if "metadata_json" not in champion_columns:
            add_column(conn, "strategy_arena_champions", "metadata_json", "LONGTEXT")
        history_columns = table_columns(conn, "strategy_arena_history")
        if "metadata_json" not in history_columns:
            add_column(conn, "strategy_arena_history", "metadata_json", "LONGTEXT")
        for table_name in (
            "strategy_arena_runs",
            "strategy_arena_evaluations",
            "strategy_arena_champions",
            "strategy_arena_history",
        ):
            existing_columns = table_columns(conn, table_name)
            for column_name in ("display_name", "task_label", "artifact_dir_name"):
                if column_name not in existing_columns:
                    add_column(conn, table_name, column_name, "VARCHAR(128) NOT NULL DEFAULT ''")
        for table_name, index_name in (
            ("strategy_arena_runs", "idx_strategy_arena_runs_label"),
            ("strategy_arena_evaluations", "idx_strategy_arena_eval_label"),
            ("strategy_arena_champions", "idx_strategy_arena_champion_label"),
            ("strategy_arena_history", "idx_strategy_arena_history_label"),
        ):
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON {table_name} (display_name, task_label, arena_name)"
            )
        upsert_arena_definition(conn, arena_context_metadata(self.context), self.now_fn())

    def write_result_tables(
        self,
        conn: Any,
        *,
        summary: dict[str, Any],
        model_path: str,
        now: str,
        score_components_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        rules: ArenaChallengeRules | None = None,
    ) -> None:
        if rules is not None:
            score_components_fn = rules.score_components
        if score_components_fn is None:
            raise ValueError("score_components_fn or rules is required")
        self.ensure_tables(conn)
        summary_for_db = dict(summary)
        existing_strategy = summary_for_db.get("arena_strategy")
        context_metadata = arena_context_metadata(self.context)
        if isinstance(existing_strategy, dict):
            summary_for_db["arena_strategy"] = {**context_metadata, **existing_strategy}
        else:
            summary_for_db["arena_strategy"] = context_metadata
        metadata = summary_for_db["arena_strategy"]
        display_name = str(metadata.get("display_name") or self.context.display_name or self.context.strategy_id)
        task_label = str(metadata.get("task_label") or f"{display_name} · 打擂训练")
        artifact_dir_name = str(metadata.get("artifact_dir_name") or self.context.artifact_dir_name or self.context.artifact_dir.name)
        metadata_json = json.dumps(summary_for_db["arena_strategy"], ensure_ascii=False, sort_keys=True, default=str)
        best = summary.get("best") or {}
        challenge = summary.get("challenge_result") or {}
        champion = summary.get("arena_champion") or {}
        run_columns = [
            "strategy_id", "arena_name", "run_id", "start_date", "end_date", "status", "objective",
            "model_type", "best_scope", "best_horizon", "best_top_n", "arena_score", "champion_updated",
            "display_name", "task_label", "artifact_dir_name", "metadata_json", "summary_json", "model_path",
            "created_at", "updated_at",
        ]
        conn.execute(
            replace_sql("strategy_arena_runs", run_columns, ["strategy_id", "arena_name", "run_id"]),
            (
                self.context.strategy_id,
                self.context.arena_name,
                self.context.run_id,
                str(summary.get("start") or ""),
                str(summary.get("end") or ""),
                "success",
                str(summary.get("objective") or ""),
                str(summary.get("model_kind") or ""),
                str(best.get("scope") or ""),
                int(best.get("horizon", 0) or 0),
                int(best.get("top_n", 0) or 0),
                _safe_float(summary.get("best_challenger_score")),
                1 if bool(challenge.get("updated")) else 0,
                display_name,
                task_label,
                artifact_dir_name,
                metadata_json,
                json.dumps(summary_for_db, ensure_ascii=False, default=str),
                str(model_path or ""),
                now,
                now,
            ),
        )
        conn.execute(
            "DELETE FROM strategy_arena_evaluations WHERE strategy_id = ? AND arena_name = ? AND run_id = ?",
            (self.context.strategy_id, self.context.arena_name, self.context.run_id),
        )
        eval_columns = [
            "strategy_id", "arena_name", "run_id", "eval_id", "scope", "horizon", "segment", "top_n",
            "arena_score", "annual_return", "compound_return", "max_drawdown", "sharpe",
            "capital_annual_return", "capital_compound_return", "capital_max_drawdown", "capital_sharpe",
            "rank_ic", "rank_ic_days", "trade_count", "trade_years", "display_name", "task_label",
            "artifact_dir_name", "metadata_json", "metrics_json", "config_json",
            "created_at", "updated_at",
        ]
        eval_rows: list[tuple[Any, ...]] = []
        for run in summary.get("runs", []) or []:
            if not isinstance(run, dict):
                continue
            scope = str(run.get("scope") or "")
            horizon = int(run.get("horizon", 0) or 0)
            for idx, item in enumerate(run.get("evaluations", []) or []):
                if not isinstance(item, dict):
                    continue
                row = {**item, "scope": scope, "horizon": horizon}
                row_json = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                eval_id = hashlib.sha1(f"{idx}:{row_json}".encode("utf-8")).hexdigest()
                components = score_components_fn(row)
                config = {
                    key: row.get(key)
                    for key in (
                        "min_pred_return", "min_market_up_ratio", "min_market_ret5", "min_market_ret20",
                        "min_market_amount_chg5", "max_market_drawdown20", "max_market_volatility20",
                        "min_industry_up_ratio", "max_crash_prob", "execution_stop_loss",
                        "execution_take_profit", "position_weighting", "capital_scale_mode",
                        "capital_tranche_fraction",
                    )
                    if key in row
                }
                eval_rows.append((
                    self.context.strategy_id,
                    self.context.arena_name,
                    self.context.run_id,
                    eval_id,
                    scope,
                    horizon,
                    str(row.get("segment") or ""),
                    int(row.get("top_n", 0) or 0),
                    _safe_float(components.get("score")),
                    _safe_float(row.get("annual_return")),
                    _safe_float(row.get("compound_return")),
                    _safe_float(row.get("max_drawdown")),
                    _safe_float(row.get("sharpe")),
                    _safe_float(row.get("capital_annual_return")),
                    _safe_float(row.get("capital_compound_return")),
                    _safe_float(row.get("capital_max_drawdown")),
                    _safe_float(row.get("capital_sharpe")),
                    _safe_float(row.get("rank_ic")),
                    int(row.get("rank_ic_days", 0) or 0),
                    int(row.get("trade_count", 0) or 0),
                    int(row.get("trade_years", 0) or 0),
                    display_name,
                    task_label,
                    artifact_dir_name,
                    metadata_json,
                    row_json,
                    json.dumps(config, ensure_ascii=False, default=str),
                    now,
                    now,
                ))
        if eval_rows:
            conn.executemany(
                replace_sql(
                    "strategy_arena_evaluations",
                    eval_columns,
                    ["strategy_id", "arena_name", "run_id", "eval_id"],
                ),
                eval_rows,
            )
        if champion:
            champion_columns = [
                "strategy_id", "arena_name", "champion_run_id", "champion_version", "arena_score",
                "qualification_status", "champion_type", "validation_status", "display_name", "task_label",
                "artifact_dir_name", "metadata_json", "champion_json", "updated_at",
            ]
            conn.execute(
                replace_sql("strategy_arena_champions", champion_columns, ["strategy_id", "arena_name"]),
                (
                    self.context.strategy_id,
                    self.context.arena_name,
                    str(champion.get("run_id") or ""),
                    int(champion.get("champion_version", 0) or 0),
                    _safe_float(champion.get("arena_score")),
                    str(champion.get("qualification_status") or ""),
                    str(champion.get("champion_type") or ""),
                    str(champion.get("validation_status") or ""),
                    display_name,
                    task_label,
                    artifact_dir_name,
                    metadata_json,
                    json.dumps(champion, ensure_ascii=False, default=str),
                    now,
                ),
            )
        if challenge:
            history_columns = [
                "strategy_id", "arena_name", "challenge_version", "run_id", "challenger_score",
                "incumbent_score", "updated", "challenger_tier", "challenger_tier_name",
                "display_name", "task_label", "artifact_dir_name", "metadata_json", "history_json", "challenged_at",
            ]
            conn.execute(
                replace_sql("strategy_arena_history", history_columns, ["strategy_id", "arena_name", "challenge_version"]),
                (
                    self.context.strategy_id,
                    self.context.arena_name,
                    int(challenge.get("challenge_version", 0) or 0),
                    self.context.run_id,
                    _safe_float(challenge.get("challenger_score")),
                    None if challenge.get("incumbent_score") is None else _safe_float(challenge.get("incumbent_score")),
                    1 if bool(challenge.get("updated")) else 0,
                    int(challenge.get("challenger_tier", 0) or 0),
                    str(challenge.get("challenger_tier_name") or ""),
                    display_name,
                    task_label,
                    artifact_dir_name,
                    metadata_json,
                    json.dumps(challenge, ensure_ascii=False, default=str),
                    now,
                ),
            )

    def challenge_champion(
        self,
        *,
        challenger: dict[str, Any],
        summary_path: Path,
        rules: ArenaChallengeRules | None = None,
        score_components_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        score_key_fn: Callable[[dict[str, Any]], tuple[float, ...]] | None = None,
        payload_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        comparable_payload_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        validation_report: dict[str, Any] | None = None,
        notify_validation_fn: Callable[[str, dict[str, Any], float, int, Path], bool] | None = None,
    ) -> dict[str, Any]:
        if rules is None:
            if (
                score_components_fn is None
                or score_key_fn is None
                or payload_fn is None
                or comparable_payload_fn is None
            ):
                raise ValueError("rules or all scoring/payload functions are required")
            rules = ArenaChallengeRules(
                score_components_fn=score_components_fn,
                score_key_fn=score_key_fn,
                payload_fn=payload_fn,
                comparable_payload_fn=comparable_payload_fn,
            )
        path = self.champion_path
        incumbent = self.load_champion()
        challenge_version = self.next_challenge_version()
        challenger_payload = rules.payload(challenger)
        challenger_components = rules.score_components(challenger)
        challenger_score = _safe_float(challenger_components.get("score"))
        challenger_key = rules.score_key(challenger)
        incumbent_components = (incumbent or {}).get("arena_score_components") or {}
        if incumbent and not incumbent_components.get("arena_tier_name") and isinstance(incumbent.get("best"), dict):
            incumbent_components = rules.score_components(incumbent["best"])
        incumbent_score = _safe_float((incumbent or {}).get("arena_score"), default=-1e18)
        incumbent_key = rules.score_key((incumbent or {}).get("best") or {}) if incumbent else (-1e18, -1e18, -1e18, -1e18, -1e18, -1e18)
        incumbent_tier = int(incumbent_components.get("arena_tier", 0) or 0) if incumbent else -1
        challenger_tier = int(challenger_components.get("arena_tier", 0) or 0)
        min_improvement = float(self.context.min_improvement or 0.0)
        challenger_qualification_status = "qualified" if challenger_tier >= 3 else "provisional"
        challenger_champion_type = "qualified_champion" if challenger_tier >= 3 else "current_best"
        incumbent_qualification_status = (incumbent or {}).get("qualification_status")
        incumbent_champion_type = (incumbent or {}).get("champion_type")
        improved = (
            incumbent is None
            or challenger_score > incumbent_score + min_improvement
            or (abs(challenger_score - incumbent_score) <= max(1e-9, abs(incumbent_score) * 1e-12) and challenger_key > incumbent_key)
        )
        result = {
            "arena_name": self.context.arena_name,
            "strategy_id": self.context.strategy_id,
            "challenge_version": challenge_version,
            "champion_path": str(path),
            "history_path": str(self.history_path),
            "updated": improved,
            "challenger_score": challenger_score,
            "challenger_score_key": challenger_key,
            "challenger_tier": challenger_tier,
            "challenger_tier_name": challenger_components.get("arena_tier_name"),
            "challenger_qualification_status": challenger_qualification_status,
            "challenger_champion_type": challenger_champion_type,
            "incumbent_score": None if incumbent is None else incumbent_score,
            "incumbent_score_key": None if incumbent is None else incumbent_key,
            "incumbent_tier": None if incumbent is None else incumbent_tier,
            "incumbent_tier_name": None if incumbent is None else incumbent_components.get("arena_tier_name"),
            "incumbent_qualification_status": incumbent_qualification_status,
            "incumbent_champion_type": incumbent_champion_type,
            "challenger": challenger_payload,
            "challenger_score_components": challenger_components,
            "incumbent": incumbent,
        }
        if improved:
            now = self.now_fn()
            new_champion = {
                "arena_name": result["arena_name"],
                "strategy_id": self.context.strategy_id,
                "champion_version": challenge_version,
                "run_id": self.context.run_id,
                "summary_path": str(summary_path),
                "arena_score": challenger_score,
                "arena_score_components": challenger_components,
                "best": challenger_payload,
                "qualification_status": challenger_qualification_status,
                "champion_type": challenger_champion_type,
                "champion_validation": validation_report,
                "validation_status": "pending_rerun",
                "validation_note": "新擂主仅代表首次挑战胜出，需要同配置重跑后才能标记为 confirmed。",
                "created_at": (incumbent or {}).get("created_at", now),
                "updated_at": now,
                "previous_champion": incumbent,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(new_champion, ensure_ascii=False, indent=2), encoding="utf-8")
            result["champion"] = new_champion
            self.progress_log(
                "arena_champion_updated",
                run_id=self.context.run_id,
                strategy_id=self.context.strategy_id,
                arena_name=result["arena_name"],
                champion_path=str(path),
                challenger_score=challenger_score,
                incumbent_score=result["incumbent_score"],
                challenger_tier=challenger_tier,
                challenger_tier_name=challenger_components.get("arena_tier_name"),
                challenger_qualification_status=challenger_qualification_status,
                challenger_champion_type=challenger_champion_type,
                incumbent_tier=result["incumbent_tier"],
                incumbent_tier_name=result["incumbent_tier_name"],
                incumbent_qualification_status=result["incumbent_qualification_status"],
                incumbent_champion_type=result["incumbent_champion_type"],
                challenger=challenger_payload,
            )
        else:
            validation_confirmed = False
            if incumbent:
                incumbent_payload = rules.payload((incumbent or {}).get("best") or {})
                same_champion = rules.comparable_payload(challenger_payload) == rules.comparable_payload(incumbent_payload)
                same_score = abs(challenger_score - incumbent_score) <= max(1e-9, abs(incumbent_score) * 1e-12)
                pending_validation = (incumbent or {}).get("validation_status") == "pending_rerun"
                historical_recalc_validation = (incumbent or {}).get("validation_status") == "historical_score_recalc"
                refresh_validation_report = validation_report is not None and same_champion and same_score
                should_notify_validation = pending_validation or historical_recalc_validation
                if same_champion and same_score and (pending_validation or historical_recalc_validation or refresh_validation_report):
                    now = self.now_fn()
                    incumbent = dict(incumbent)
                    incumbent["validation_status"] = "confirmed"
                    incumbent["validation_note"] = "同配置重跑复验通过；验证轮未改变擂主版本，并刷新擂主复验报告。"
                    incumbent["validated_at"] = now
                    incumbent["validation_run_id"] = self.context.run_id
                    incumbent["validation_summary_path"] = str(summary_path)
                    incumbent["validation_score"] = challenger_score
                    incumbent["champion_validation"] = validation_report
                    incumbent["updated_at"] = now
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(incumbent, ensure_ascii=False, indent=2), encoding="utf-8")
                    validation_confirmed = True
                    result["validation_confirmed"] = True
                    self.progress_log(
                        "arena_champion_validated",
                        run_id=self.context.run_id,
                        strategy_id=self.context.strategy_id,
                        arena_name=result["arena_name"],
                        champion_path=str(path),
                        champion_run_id=incumbent.get("run_id"),
                        champion_version=incumbent.get("champion_version"),
                        challenger_score=challenger_score,
                    )
                    if should_notify_validation and notify_validation_fn is not None:
                        notify_validation_fn("validated", challenger, challenger_score, int(incumbent.get("champion_version") or challenge_version), summary_path)
                    else:
                        self.progress_log(
                            "arena_wechat_notify_skipped",
                            run_id=self.context.run_id,
                            strategy_id=self.context.strategy_id,
                            notify_event="validated",
                            reason="validation_report_refresh_only",
                        )
            result["champion"] = incumbent
            self.progress_log(
                "arena_challenge_failed",
                run_id=self.context.run_id,
                strategy_id=self.context.strategy_id,
                arena_name=result["arena_name"],
                champion_path=str(path),
                challenger_score=challenger_score,
                incumbent_score=incumbent_score,
                challenger_tier=challenger_tier,
                challenger_tier_name=challenger_components.get("arena_tier_name"),
                challenger_qualification_status=challenger_qualification_status,
                challenger_champion_type=challenger_champion_type,
                incumbent_tier=incumbent_tier,
                incumbent_tier_name=incumbent_components.get("arena_tier_name"),
                incumbent_qualification_status=incumbent_qualification_status,
                incumbent_champion_type=incumbent_champion_type,
                challenger=challenger_payload,
                champion=(incumbent or {}).get("best"),
                validation_confirmed=validation_confirmed,
            )
        history_record = {
            "arena_name": result["arena_name"],
            "strategy_id": self.context.strategy_id,
            "challenge_version": challenge_version,
            "run_id": self.context.run_id,
            "summary_path": str(summary_path),
            "challenged_at": self.now_fn(),
            "updated": improved,
            "challenger_score": challenger_score,
            "challenger_tier": challenger_tier,
            "challenger_tier_name": challenger_components.get("arena_tier_name"),
            "challenger_qualification_status": challenger_qualification_status,
            "challenger_champion_type": challenger_champion_type,
            "incumbent_score": result["incumbent_score"],
            "incumbent_tier": result["incumbent_tier"],
            "incumbent_tier_name": result["incumbent_tier_name"],
            "incumbent_qualification_status": result["incumbent_qualification_status"],
            "incumbent_champion_type": result["incumbent_champion_type"],
            "challenger": challenger_payload,
            "challenger_score_components": challenger_components,
            "incumbent_run_id": (incumbent or {}).get("run_id"),
            "incumbent_champion_version": (incumbent or {}).get("champion_version"),
            "incumbent": (incumbent or {}).get("best"),
            "champion_after": (result.get("champion") or {}).get("best"),
            "champion_after_run_id": (result.get("champion") or {}).get("run_id"),
            "champion_after_version": (result.get("champion") or {}).get("champion_version"),
            "champion_after_qualification_status": (result.get("champion") or {}).get("qualification_status"),
            "champion_after_type": (result.get("champion") or {}).get("champion_type"),
            "validation_confirmed": bool(result.get("validation_confirmed", False)),
        }
        self.append_history(history_record)
        self.progress_log(
            "arena_history_appended",
            run_id=self.context.run_id,
            strategy_id=self.context.strategy_id,
            arena_name=result["arena_name"],
            challenge_version=challenge_version,
            history_path=str(self.history_path),
            updated=improved,
        )
        return result
