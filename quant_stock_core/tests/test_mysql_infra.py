from __future__ import annotations

from uuid import uuid4

import pytest

from common.infra import db


def _mysql_available() -> bool:
    try:
        with db.open_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mysql_available(), reason="local MySQL quant_stock database is not available")


def test_mysql_dsn_parser_supports_project_go_dsn() -> None:
    kwargs = db._mysql_dsn_to_kwargs(db.DEFAULT_MYSQL_DSN)

    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 3306
    assert kwargs["user"] == "quant_stock"
    assert kwargs["password"] == "quant_stock"
    assert kwargs["database"] == "quant_stock"
    assert kwargs["charset"] == "utf8mb4"


def test_mysql_identifier_helpers_quote_reserved_rank() -> None:
    sql = db.upsert_sql("zz_test_rank_table", ["id", "rank", "payload_json"], ["id"], ["rank", "payload_json"])

    assert "`rank`" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "payload_json" in sql


def test_mysql_create_index_if_not_exists_is_idempotent() -> None:
    table = f"zz_test_idx_{uuid4().hex[:10]}"
    index = f"idx_{table}_value"
    with db.write_transaction() as conn:
        conn.execute(f"DROP TABLE IF EXISTS `{table}`")
        conn.execute(f"CREATE TABLE `{table}` (id VARCHAR(64) PRIMARY KEY, value VARCHAR(64) NOT NULL)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS `{index}` ON `{table}`(value)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS `{index}` ON `{table}`(value)")
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = DATABASE() AND table_name = ? AND index_name = ?
            """,
            (table, index),
        ).fetchone()
        conn.execute(f"DROP TABLE `{table}`")

    assert int(row[0]) == 1
