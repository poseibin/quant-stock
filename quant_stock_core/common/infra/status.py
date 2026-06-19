"""任务实时状态写入 MySQL，供 desktop 轮询"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .db import add_column, open_db, table_columns, upsert_sql


PROGRESS_PROTECTED_STATES = ("done", "success", "error", "failed", "cancelled", "interrupted")
DONE_PROTECTED_STATES = ("error", "failed", "cancelled", "interrupted")
ERROR_PROTECTED_STATES = ("done", "success", "cancelled", "interrupted")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _task_type(task: str) -> str:
    if task in {"data_update", "data_file_scan"}:
        return "data_update"
    if task == "profit_arena_model":
        return "model_training"
    if task == "factor_snapshot":
        return "factor_snapshot"
    return "python"


def _ensure_columns(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_run_status (
            task TEXT PRIMARY KEY,
            task_type TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL,
            idx INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            stage TEXT,
            name TEXT,
            message TEXT,
            run_id TEXT,
            strategy_id TEXT,
            arena_name TEXT,
            task_key TEXT,
            task_label TEXT,
            metadata_json LONGTEXT,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
        """
    )
    columns = table_columns(conn, "task_run_status")
    if "task_type" not in columns:
        add_column(conn, "task_run_status", "task_type", "TEXT NOT NULL DEFAULT ''")
    if "worker_pid" not in columns:
        add_column(conn, "task_run_status", "worker_pid", "INTEGER")
    for column in ("run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json"):
        if column not in columns:
            add_column(conn, "task_run_status", column, "LONGTEXT" if column == "metadata_json" else "TEXT")
    if "metadata_json" in columns:
        try:
            conn.execute("ALTER TABLE task_run_status MODIFY metadata_json LONGTEXT")
        except Exception:
            pass


def _metadata_values(metadata: dict[str, Any] | None) -> tuple[str, str, str, str, str]:
    meta = metadata or {}
    return (
        str(meta.get("run_id") or ""),
        str(meta.get("strategy_id") or ""),
        str(meta.get("arena_name") or ""),
        str(meta.get("task_key") or ""),
        str(meta.get("task_label") or ""),
    )


def _metadata_json(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return ""
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)


def _state_in(states: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{item}'" for item in states) + ")"


def _protected_assignments(columns: tuple[str, ...], states: tuple[str, ...]) -> str:
    protected = _state_in(states)
    return ",\n                ".join(
        f"{column} = IF(state IN {protected}, {column}, VALUES({column}))"
        for column in columns
    )


def begin(task: str, metadata: dict[str, Any] | None = None) -> None:
    now = _now()
    run_id, strategy_id, arena_name, task_key, task_label = _metadata_values(metadata)
    metadata_json = _metadata_json(metadata)
    with open_db() as conn:
        _ensure_columns(conn)
        columns = [
            "task", "task_type", "state", "idx", "total", "stage", "name", "message",
            "run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json",
            "started_at", "updated_at", "finished_at",
        ]
        conn.execute(
            upsert_sql(
                "task_run_status",
                columns,
                ["task"],
                [
                    "task_type", "state", "idx", "total", "stage", "name", "message",
                    "run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json",
                    "started_at", "updated_at", "finished_at",
                ],
            ),
            (
                task, _task_type(task), "running", 0, 0, None, None, None,
                run_id, strategy_id, arena_name, task_key, task_label, metadata_json,
                now, now, None,
            ),
        )


def progress(
    task: str,
    idx: int,
    total: int,
    stage: str | None = None,
    name: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = _now()
    run_id, strategy_id, arena_name, task_key, task_label = _metadata_values(metadata)
    metadata_json = _metadata_json(metadata)
    with open_db() as conn:
        _ensure_columns(conn)
        update_columns = (
            "task_type", "state", "idx", "total", "stage", "name", "message",
            "run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json", "updated_at",
        )
        conn.execute(
            f"""
            INSERT INTO task_run_status (
                task, task_type, state, idx, total, stage, name, message,
                run_id, strategy_id, arena_name, task_key, task_label, metadata_json,
                started_at, updated_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                {_protected_assignments(update_columns, PROGRESS_PROTECTED_STATES)}
            """,
            (
                task,
                _task_type(task),
                "running",
                int(idx),
                int(total),
                stage or "",
                name or "",
                message or "",
                run_id,
                strategy_id,
                arena_name,
                task_key,
                task_label,
                metadata_json,
                now,
                now,
                None,
            ),
        )


def done(task: str, message: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    now = _now()
    run_id, strategy_id, arena_name, task_key, task_label = _metadata_values(metadata)
    metadata_json = _metadata_json(metadata)
    with open_db() as conn:
        _ensure_columns(conn)
        update_columns = (
            "task_type", "state", "idx", "total", "stage", "name", "message",
            "run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json", "updated_at", "finished_at",
        )
        conn.execute(
            f"""
            INSERT INTO task_run_status (
                task, task_type, state, idx, total, stage, name, message,
                run_id, strategy_id, arena_name, task_key, task_label, metadata_json,
                started_at, updated_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                {_protected_assignments(update_columns, DONE_PROTECTED_STATES)}
            """,
            (
                task,
                _task_type(task),
                "done",
                100,
                100,
                "done",
                "完成",
                message or "",
                run_id,
                strategy_id,
                arena_name,
                task_key,
                task_label,
                metadata_json,
                now,
                now,
                now,
            ),
        )
        conn.execute("UPDATE task_run_status SET worker_pid=NULL WHERE task=?", (task,))


def error(task: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    now = _now()
    run_id, strategy_id, arena_name, task_key, task_label = _metadata_values(metadata)
    metadata_json = _metadata_json(metadata)
    with open_db() as conn:
        _ensure_columns(conn)
        update_columns = (
            "task_type", "state", "message",
            "run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json", "updated_at", "finished_at",
        )
        conn.execute(
            f"""
            INSERT INTO task_run_status (
                task, task_type, state, idx, total, stage, name, message,
                run_id, strategy_id, arena_name, task_key, task_label, metadata_json,
                started_at, updated_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                {_protected_assignments(update_columns, ERROR_PROTECTED_STATES)}
            """,
            (
                task, _task_type(task), "error", 0, 0, None, None, message,
                run_id, strategy_id, arena_name, task_key, task_label,
                metadata_json,
                now, now, now,
            ),
        )
        conn.execute("UPDATE task_run_status SET worker_pid=NULL WHERE task=?", (task,))


def get(task: str) -> dict[str, Any] | None:
    with open_db() as conn:
        _ensure_columns(conn)
        row = conn.execute(
            "SELECT task, task_type, state, idx, total, stage, name, message, "
            "run_id, strategy_id, arena_name, task_key, task_label, metadata_json, started_at, updated_at, finished_at "
            "FROM task_run_status WHERE task = ?",
            (task,),
        ).fetchone()
    if not row:
        return None
    keys = [
        "task", "task_type", "state", "idx", "total", "stage", "name", "message",
        "run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json",
        "started_at", "updated_at", "finished_at",
    ]
    out = dict(zip(keys, row))
    if not out.get("task_type"):
        out["task_type"] = _task_type(task)
    return out
