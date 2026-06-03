"""任务实时状态写入 SQLite，供 desktop 轮询"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .db import open_db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def begin(task: str) -> None:
    now = _now()
    with open_db() as conn:
        conn.execute(
            """
            INSERT INTO py_run_status(task, state, idx, total, stage, name, message, started_at, updated_at, finished_at)
            VALUES(?, 'running', 0, 0, NULL, NULL, NULL, ?, ?, NULL)
            ON CONFLICT(task) DO UPDATE SET
                state='running', idx=0, total=0, stage=NULL, name=NULL, message=NULL,
                started_at=excluded.started_at, updated_at=excluded.updated_at, finished_at=NULL
            """,
            (task, now, now),
        )


def progress(task: str, idx: int, total: int, stage: str | None = None, name: str | None = None) -> None:
    now = _now()
    with open_db() as conn:
        conn.execute(
            """
            UPDATE py_run_status
            SET idx = ?, total = ?, stage = ?, name = ?, updated_at = ?
            WHERE task = ?
            """,
            (int(idx), int(total), stage or "", name or "", now, task),
        )


def done(task: str, message: str | None = None) -> None:
    now = _now()
    with open_db() as conn:
        conn.execute(
            "UPDATE py_run_status SET state='done', message=?, updated_at=?, finished_at=? WHERE task=?",
            (message or "", now, now, task),
        )


def error(task: str, message: str) -> None:
    now = _now()
    with open_db() as conn:
        conn.execute(
            """
            INSERT INTO py_run_status(task, state, idx, total, stage, name, message, started_at, updated_at, finished_at)
            VALUES(?, 'error', 0, 0, NULL, NULL, ?, ?, ?, ?)
            ON CONFLICT(task) DO UPDATE SET
                state='error', message=excluded.message, updated_at=excluded.updated_at, finished_at=excluded.finished_at
            """,
            (task, message, now, now, now),
        )


def get(task: str) -> dict[str, Any] | None:
    with open_db() as conn:
        row = conn.execute(
            "SELECT task, state, idx, total, stage, name, message, started_at, updated_at, finished_at "
            "FROM py_run_status WHERE task = ?",
            (task,),
        ).fetchone()
    if not row:
        return None
    keys = ["task", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"]
    return dict(zip(keys, row))
