"""Shared desktop database access with SQLite/MySQL backend selection."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from common.config.settings import DATA_ROOT


DEFAULT_MYSQL_DSN = "quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local"


def db_backend() -> str:
    backend = os.getenv("DESKTOP_DB_BACKEND", "").strip().lower()
    return backend or "sqlite"


def is_mysql() -> bool:
    return db_backend() == "mysql"


def desktop_db_path() -> Path:
    env = os.getenv("DESKTOP_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (DATA_ROOT / "meta.db").resolve()


def desktop_db_dsn() -> str:
    return os.getenv("DESKTOP_DB_DSN", "").strip() or os.getenv("DESKTOP_MYSQL_DSN", "").strip() or DEFAULT_MYSQL_DSN


class CursorAdapter:
    def __init__(self, cursor: Any, backend: str) -> None:
        self._cursor = cursor
        self._backend = backend

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return list(self._cursor.fetchall())


class ConnectionAdapter:
    def __init__(self, conn: Any, backend: str) -> None:
        self.raw = conn
        self.backend = backend

    def execute(self, sql: str, params: Any = ()) -> CursorAdapter:
        if self.backend == "mysql":
            handled = maybe_create_mysql_index(self.raw, sql)
            if handled is not None:
                return handled
            sql = normalize_mysql_sql(sql)
            sql = translate_placeholders(sql)
            cursor = self.raw.cursor()
            cursor.execute(sql, params or ())
            return CursorAdapter(cursor, self.backend)
        return CursorAdapter(self.raw.execute(sql, params or ()), self.backend)

    def executemany(self, sql: str, params: list[Any] | tuple[Any, ...]) -> CursorAdapter:
        if self.backend == "mysql":
            sql = normalize_mysql_sql(sql)
            sql = translate_placeholders(sql)
            cursor = self.raw.cursor()
            cursor.executemany(sql, params or ())
            return CursorAdapter(cursor, self.backend)
        return CursorAdapter(self.raw.executemany(sql, params or ()), self.backend)

    def executescript(self, sql: str) -> None:
        if self.backend == "mysql":
            for statement in sql.split(";"):
                if statement.strip():
                    self.execute(statement)
            return
        self.raw.executescript(sql)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()

    def __enter__(self) -> "ConnectionAdapter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def translate_placeholders(sql: str) -> str:
    out: list[str] = []
    in_single = False
    in_double = False
    for ch in sql:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


def normalize_mysql_sql(sql: str) -> str:
    out = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
    out = re.sub(r"\bTEXT\s+NOT\s+NULL\s+DEFAULT\s+'[^']*'", "LONGTEXT NOT NULL", out, flags=re.IGNORECASE)
    out = re.sub(r"\bTEXT\s+DEFAULT\s+'[^']*'", "LONGTEXT", out, flags=re.IGNORECASE)
    return out


def maybe_create_mysql_index(raw_conn: Any, sql: str) -> CursorAdapter | None:
    match = re.match(
        r"^\s*CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+"
        r"(?P<index>[`\w]+)\s+ON\s+(?P<table>[`\w]+)\s*\((?P<columns>.+)\)\s*;?\s*$",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    index_name = match.group("index").strip("`")
    table_name = match.group("table").strip("`")
    cursor = raw_conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table_name, index_name),
    )
    row = cursor.fetchone()
    if row and int(row[0]) > 0:
        return CursorAdapter(cursor, "mysql")
    unique = "UNIQUE " if match.group("unique") else ""
    columns = match.group("columns").strip()
    cursor.execute(f"CREATE {unique}INDEX `{index_name}` ON `{table_name}` ({columns})")
    return CursorAdapter(cursor, "mysql")


def open_db() -> ConnectionAdapter:
    return connect_db()


def configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect_db(path: str | Path | None = None, *, isolation_level: str | None = None) -> ConnectionAdapter:
    if is_mysql():
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("MySQL backend requires pymysql; install quant_stock_core requirements") from exc
        kwargs = _mysql_dsn_to_kwargs(desktop_db_dsn())
        kwargs.setdefault("charset", "utf8mb4")
        conn = pymysql.connect(
            **kwargs,
            autocommit=isolation_level is None,
            cursorclass=pymysql.cursors.Cursor,
        )
        return ConnectionAdapter(conn, "mysql")
    db_path = Path(path).expanduser().resolve() if path else desktop_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=isolation_level)
    return ConnectionAdapter(configure_connection(conn), "sqlite")


def _mysql_dsn_to_kwargs(dsn: str) -> dict[str, Any]:
    from urllib.parse import parse_qs, urlparse
    if dsn.startswith("mysql://"):
        parsed = urlparse(dsn)
        return {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/"),
        }
    # PyMySQL accepts SQLAlchemy-style URLs, not Go DSNs.
    import re
    match = re.match(r"(?P<user>[^:@/]+)(:(?P<password>[^@]*))?@tcp\((?P<host>[^)]+)\)/(?P<db>[^?]+)(\?(?P<query>.*))?", dsn)
    if not match:
        raise ValueError(f"unsupported mysql dsn: {dsn}")
    user = match.group("user")
    password = match.group("password") or ""
    host_port = match.group("host")
    host, _, port_text = host_port.partition(":")
    db = match.group("db")
    query = parse_qs(match.group("query") or "")
    return {
        "host": host or "127.0.0.1",
        "port": int(port_text or 3306),
        "user": user,
        "password": password,
        "database": db,
        "charset": (query.get("charset") or ["utf8mb4"])[0],
    }


@contextmanager
def write_transaction(
    path: str | Path | None = None,
    *,
    retries: int = 5,
    retry_delay: float = 0.25,
) -> Iterator[ConnectionAdapter]:
    if is_mysql():
        conn = connect_db(path, isolation_level="")
        try:
            conn.execute("START TRANSACTION")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    conn: ConnectionAdapter | None = None
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


def table_exists(conn: ConnectionAdapter, table: str) -> bool:
    if conn.backend == "mysql":
        row = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = ?",
            (table,),
        ).fetchone()
        return bool(row and int(row[0]) > 0)
    return conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def table_columns(conn: ConnectionAdapter, table: str) -> set[str]:
    if conn.backend == "mysql":
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_column(conn: ConnectionAdapter, table: str, name: str, ddl: str) -> None:
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {to_backend_ddl(ddl, conn.backend)}")


def to_backend_ddl(ddl: str, backend: str | None = None) -> str:
    backend = backend or db_backend()
    if backend != "mysql":
        return ddl
    out = ddl.replace("INTEGER", "BIGINT").replace("REAL", "DOUBLE").replace("TEXT", "VARCHAR(255)")
    if "payload_json" in ddl or "config_json" in ddl or "summary_json" in ddl:
        out = out.replace("VARCHAR(255)", "LONGTEXT")
    return out


def upsert_sql(table: str, columns: list[str], conflict_columns: list[str], update_columns: list[str]) -> str:
    placeholders = ", ".join("?" for _ in columns)
    table_sql = quote_ident(table)
    column_sql = ", ".join(quote_ident(col) for col in columns)
    if is_mysql():
        assignments = ", ".join(f"{quote_ident(col)}=VALUES({quote_ident(col)})" for col in update_columns)
        return f"INSERT INTO {table_sql} ({column_sql}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {assignments}"
    assignments = ", ".join(f"{quote_ident(col)}=excluded.{quote_ident(col)}" for col in update_columns)
    conflict_sql = ", ".join(quote_ident(col) for col in conflict_columns)
    return f"INSERT INTO {table_sql} ({column_sql}) VALUES ({placeholders}) ON CONFLICT({conflict_sql}) DO UPDATE SET {assignments}"


def replace_sql(table: str, columns: list[str], conflict_columns: list[str]) -> str:
    if is_mysql():
        update_columns = [col for col in columns if col not in conflict_columns]
        return upsert_sql(table, columns, conflict_columns, update_columns)
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT OR REPLACE INTO {quote_ident(table)} ({', '.join(quote_ident(col) for col in columns)}) VALUES ({placeholders})"


def insert_ignore_sql(table: str, columns: list[str]) -> str:
    placeholders = ", ".join("?" for _ in columns)
    table_sql = quote_ident(table)
    column_sql = ", ".join(quote_ident(col) for col in columns)
    prefix = "INSERT IGNORE INTO" if is_mysql() else "INSERT OR IGNORE INTO"
    return f"{prefix} {table_sql} ({column_sql}) VALUES ({placeholders})"


def current_timestamp_sql() -> str:
    return "CURRENT_TIMESTAMP" if is_mysql() else "datetime('now')"


def quote_ident(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def get_recommendation(date: str) -> dict[str, Any] | None:
    with open_db() as conn:
        row = conn.execute(
            "SELECT payload_json FROM rec_daily_recommendations WHERE date = ?",
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
    columns = ["date", "generated_at", "payload_json", "created_at", "updated_at"]
    with open_db() as conn:
        conn.execute(
            upsert_sql("rec_daily_recommendations", columns, ["date"], ["generated_at", "payload_json", "updated_at"]),
            (date, generated_at, payload_json, now, now),
        )


def get_evaluation(run_id: str, strategy: str) -> dict[str, Any] | None:
    with open_db() as conn:
        row = conn.execute(
            "SELECT payload_json FROM eval_strategy_admission WHERE run_id = ? AND strategy = ?",
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
    columns = [
        "run_id", "strategy", "label", "enabled", "status", "admission", "reason",
        "start_date", "end_date", "benchmark", "baseline", "generated_at",
        "payload_json", "created_at", "updated_at",
    ]
    values = (
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
    )
    with open_db() as conn:
        conn.execute(
            upsert_sql("eval_strategy_admission", columns, ["run_id", "strategy"], ["generated_at", "payload_json", "updated_at"]),
            values,
        )
