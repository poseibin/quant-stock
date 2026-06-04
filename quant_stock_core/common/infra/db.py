"""共享 SQLite 数据访问

桌面 app 与 quant_stock_core 共用同一份 SQLite（默认 DATA_ROOT/meta.db）。
desktop Go 端负责建表（参见 quant_stock_desktop/internal/database/db.go）；
本模块只做读写。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from common.config.settings import DATA_ROOT


def desktop_db_path() -> Path:
    env = os.getenv("DESKTOP_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (DATA_ROOT / "meta.db").resolve()


def open_db() -> sqlite3.Connection:
    path = desktop_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    configure_connection(conn)
    return conn


def configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_db(path: str | Path | None = None, *, isolation_level: str | None = None) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve() if path else desktop_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=isolation_level)
    return configure_connection(conn)


@contextmanager
def write_transaction(
    path: str | Path | None = None,
    *,
    retries: int = 5,
    retry_delay: float = 0.25,
) -> Iterator[sqlite3.Connection]:
    conn: sqlite3.Connection | None = None
    for attempt in range(retries + 1):
        candidate = connect_db(path, isolation_level=None)
        try:
            candidate.execute("BEGIN IMMEDIATE")
            conn = candidate
            break
        except sqlite3.OperationalError as exc:
            candidate.close()
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if attempt >= retries:
                raise
            time.sleep(retry_delay * (attempt + 1))
    if conn is None:
        raise sqlite3.OperationalError("failed to begin sqlite write transaction")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def get_recommendation(date: str) -> dict[str, Any] | None:
    with open_db() as conn:
        row = conn.execute(
            "SELECT payload_json FROM daily_recommendation WHERE date = ?",
            (date,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def upsert_recommendation(date: str, payload: dict[str, Any], generated_at: str | None = None) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False)
    generated_at = generated_at or payload.get("generated_at") or _now()
    now = _now()
    with open_db() as conn:
        conn.execute(
            """
            INSERT INTO daily_recommendation(date, generated_at, payload_json, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                generated_at = excluded.generated_at,
                payload_json = excluded.payload_json,
                updated_at   = excluded.updated_at
            """,
            (date, generated_at, payload_json, now, now),
        )


def get_evaluation(run_id: str, strategy: str) -> dict[str, Any] | None:
    with open_db() as conn:
        row = conn.execute(
            "SELECT payload_json FROM strategy_evaluation WHERE run_id = ? AND strategy = ?",
            (run_id, strategy),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def upsert_evaluation(run_id: str, strategy: str, payload: dict[str, Any], generated_at: str | None = None) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False)
    generated_at = generated_at or payload.get("generated_at") or _now()
    now = _now()
    with open_db() as conn:
        conn.execute(
            """
            INSERT INTO strategy_evaluation(
                run_id, strategy, label, enabled, status, admission, reason,
                start_date, end_date, benchmark, baseline, generated_at,
                payload_json, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, strategy) DO UPDATE SET
                generated_at = excluded.generated_at,
                payload_json = excluded.payload_json,
                updated_at   = excluded.updated_at
            """,
            (
                run_id,
                strategy,
                str(payload.get("label") or ""),
                1 if payload.get("enabled") else 0,
                str(payload.get("status") or ""),
                str(payload.get("admission") or ""),
                str(payload.get("reason") or ""),
                str(payload.get("start") or payload.get("start_date") or ""),
                str(payload.get("end") or payload.get("end_date") or ""),
                str(payload.get("benchmark") or ""),
                str(payload.get("baseline") or ""),
                generated_at,
                payload_json,
                now,
                now,
            ),
        )
