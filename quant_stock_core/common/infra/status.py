"""任务实时状态写入 SQLite，供 desktop 轮询"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .db import add_column, open_db, table_columns, upsert_sql


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _task_type(task: str) -> str:
    if task in {"data_update", "data_file_scan"}:
        return "data_update"
    if task == "daily_signal":
        return "signal"
    if task == "limit_signal_evaluation":
        return "evaluation"
    if task in {"limit_breakout", "limit_up_momentum", "t0_daily_research", "t0_daily_timemachine"}:
        return "market_scan"
    if task in {"limit_up_model", "limit_breakout_model"}:
        return "model_training"
    if task == "policy_support_analysis":
        return "analysis"
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
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        )
        """
    )
    columns = table_columns(conn, "task_run_status")
    if "task_type" not in columns:
        add_column(conn, "task_run_status", "task_type", "TEXT NOT NULL DEFAULT ''")


def begin(task: str) -> None:
    now = _now()
    with open_db() as conn:
        _ensure_columns(conn)
        columns = ["task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"]
        conn.execute(
            upsert_sql("task_run_status", columns, ["task"], ["task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"]),
            (task, _task_type(task), "running", 0, 0, None, None, None, now, now, None),
        )


def progress(task: str, idx: int, total: int, stage: str | None = None, name: str | None = None) -> None:
    now = _now()
    with open_db() as conn:
        _ensure_columns(conn)
        conn.execute(
            """
            UPDATE task_run_status
            SET task_type = ?, idx = ?, total = ?, stage = ?, name = ?, updated_at = ?
            WHERE task = ?
            """,
            (_task_type(task), int(idx), int(total), stage or "", name or "", now, task),
        )


def done(task: str, message: str | None = None) -> None:
    now = _now()
    with open_db() as conn:
        _ensure_columns(conn)
        conn.execute(
            "UPDATE task_run_status SET task_type=?, state='done', message=?, updated_at=?, finished_at=? WHERE task=?",
            (_task_type(task), message or "", now, now, task),
        )


def error(task: str, message: str) -> None:
    now = _now()
    with open_db() as conn:
        _ensure_columns(conn)
        columns = ["task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"]
        conn.execute(
            upsert_sql("task_run_status", columns, ["task"], ["task_type", "state", "message", "updated_at", "finished_at"]),
            (task, _task_type(task), "error", 0, 0, None, None, message, now, now, now),
        )


def get(task: str) -> dict[str, Any] | None:
    with open_db() as conn:
        _ensure_columns(conn)
        row = conn.execute(
            "SELECT task, task_type, state, idx, total, stage, name, message, started_at, updated_at, finished_at "
            "FROM task_run_status WHERE task = ?",
            (task,),
        ).fetchone()
    if not row:
        return None
    keys = ["task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"]
    out = dict(zip(keys, row))
    if not out.get("task_type"):
        out["task_type"] = _task_type(task)
    return out
