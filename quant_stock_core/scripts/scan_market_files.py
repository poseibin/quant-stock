"""Scan local parquet market-data files and refresh the desktop file index."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.infra.db import add_column, connect_db, table_columns, upsert_sql


TASK_NAME = "data_file_scan"
TASK_TYPE = "data_update"
SYNC_DATASETS = ("stock_basic", "daily", "daily_basic", "fina_indicator")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def file_id(path: Path) -> str:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:16]
    return f"mdf_{digest}"


def etl_file_id(dataset: str, path: Path) -> str:
    digest = hashlib.sha1(f"{dataset}:{path}".encode("utf-8")).hexdigest()[:24]
    return f"etl_{digest}"


def ensure_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_market_files (
            id VARCHAR(255) PRIMARY KEY,
            data_type VARCHAR(255) NOT NULL,
            partition_name VARCHAR(255) NOT NULL,
            file_path VARCHAR(768) NOT NULL,
            row_count BIGINT NOT NULL DEFAULT 0,
            file_size BIGINT NOT NULL DEFAULT 0,
            created_at VARCHAR(64) NOT NULL,
            updated_at VARCHAR(64) NOT NULL,
            UNIQUE KEY idx_data_market_files_path (file_path),
            KEY idx_data_market_files_type (data_type)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_run_status (
            task VARCHAR(255) PRIMARY KEY,
            task_type VARCHAR(255) NOT NULL DEFAULT '',
            state VARCHAR(64) NOT NULL,
            idx BIGINT NOT NULL DEFAULT 0,
            total BIGINT NOT NULL DEFAULT 0,
            stage VARCHAR(255),
            name VARCHAR(255),
            message TEXT,
            worker_pid BIGINT,
            started_at VARCHAR(64),
            updated_at VARCHAR(64) NOT NULL,
            finished_at VARCHAR(64)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_etl_versions (
            dataset VARCHAR(255) PRIMARY KEY,
            source_version VARCHAR(128) NOT NULL,
            file_count BIGINT NOT NULL DEFAULT 0,
            row_count BIGINT NOT NULL DEFAULT 0,
            status VARCHAR(64) NOT NULL DEFAULT '',
            message TEXT,
            updated_at VARCHAR(64) NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_etl_files (
            id VARCHAR(64) PRIMARY KEY,
            dataset VARCHAR(255) NOT NULL,
            file_path VARCHAR(768) NOT NULL,
            source_version VARCHAR(128) NOT NULL,
            row_count BIGINT NOT NULL DEFAULT 0,
            status VARCHAR(64) NOT NULL DEFAULT '',
            message TEXT,
            updated_at VARCHAR(64) NOT NULL,
            KEY idx_data_etl_files_dataset (dataset)
        )
        """
    )
    ensure_mysql_data_tables(conn)
    columns = table_columns(conn, "task_run_status")
    if "task_type" not in columns:
        add_column(conn, "task_run_status", "task_type", "TEXT NOT NULL DEFAULT ''")
    if "worker_pid" not in columns:
        add_column(conn, "task_run_status", "worker_pid", "INTEGER")


def ensure_mysql_data_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_stock_basic (
            ts_code VARCHAR(32) PRIMARY KEY,
            symbol VARCHAR(32) NOT NULL DEFAULT '',
            name VARCHAR(128) NOT NULL DEFAULT '',
            area VARCHAR(128) NOT NULL DEFAULT '',
            industry VARCHAR(128) NOT NULL DEFAULT '',
            market VARCHAR(64) NOT NULL DEFAULT '',
            list_date VARCHAR(16) NOT NULL DEFAULT '',
            list_status VARCHAR(16) NOT NULL DEFAULT '',
            updated_at VARCHAR(64) NOT NULL,
            KEY idx_data_stock_basic_keyword (ts_code, symbol, name, industry)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_daily_bars (
            ts_code VARCHAR(32) NOT NULL,
            trade_date VARCHAR(16) NOT NULL,
            open DOUBLE NOT NULL DEFAULT 0,
            high DOUBLE NOT NULL DEFAULT 0,
            low DOUBLE NOT NULL DEFAULT 0,
            close DOUBLE NOT NULL DEFAULT 0,
            pre_close DOUBLE NOT NULL DEFAULT 0,
            change_amount DOUBLE NOT NULL DEFAULT 0,
            pct_chg DOUBLE NOT NULL DEFAULT 0,
            vol DOUBLE NOT NULL DEFAULT 0,
            amount DOUBLE NOT NULL DEFAULT 0,
            updated_at VARCHAR(64) NOT NULL,
            PRIMARY KEY(ts_code, trade_date),
            KEY idx_data_daily_bars_date (trade_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_daily_basic (
            ts_code VARCHAR(32) NOT NULL,
            trade_date VARCHAR(16) NOT NULL,
            close DOUBLE NOT NULL DEFAULT 0,
            pe DOUBLE NOT NULL DEFAULT 0,
            pe_ttm DOUBLE NOT NULL DEFAULT 0,
            pb DOUBLE NOT NULL DEFAULT 0,
            ps DOUBLE NOT NULL DEFAULT 0,
            ps_ttm DOUBLE NOT NULL DEFAULT 0,
            total_mv DOUBLE NOT NULL DEFAULT 0,
            circ_mv DOUBLE NOT NULL DEFAULT 0,
            updated_at VARCHAR(64) NOT NULL,
            PRIMARY KEY(ts_code, trade_date),
            KEY idx_data_daily_basic_date (trade_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_fina_indicator (
            ts_code VARCHAR(32) NOT NULL,
            ann_date VARCHAR(16) NOT NULL DEFAULT '',
            end_date VARCHAR(16) NOT NULL,
            eps DOUBLE NOT NULL DEFAULT 0,
            roe DOUBLE NOT NULL DEFAULT 0,
            grossprofit_margin DOUBLE NOT NULL DEFAULT 0,
            netprofit_margin DOUBLE NOT NULL DEFAULT 0,
            debt_to_assets DOUBLE NOT NULL DEFAULT 0,
            updated_at VARCHAR(64) NOT NULL,
            PRIMARY KEY(ts_code, end_date),
            KEY idx_data_fina_indicator_ts_end (ts_code, end_date)
        )
        """
    )


def set_status(conn, state: str, idx: int, total: int, stage: str, name: str, message: str = "") -> None:
    current = now_text()
    finished_at = current if state in {"success", "error"} else None
    columns = [
        "task",
        "task_type",
        "state",
        "idx",
        "total",
        "stage",
        "name",
        "message",
        "worker_pid",
        "started_at",
        "updated_at",
        "finished_at",
    ]
    conn.execute(
        upsert_sql(
            "task_run_status",
            columns,
            ["task"],
            ["task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "updated_at", "finished_at"],
        ),
        (
            TASK_NAME,
            TASK_TYPE,
            state,
            int(idx),
            int(total),
            stage,
            name,
            message,
            os.getpid() if state == "running" else None,
            current,
            current,
            finished_at,
        ),
    )


def parquet_row_count(path: Path) -> int:
    try:
        from pyarrow import parquet as pq
    except ImportError:
        return 0
    metadata = pq.ParquetFile(path).metadata
    return int(metadata.num_rows if metadata else 0)


def iter_parquet_files(data_root: Path) -> list[Path]:
    raw = data_root / "raw"
    if not raw.exists():
        return []
    return sorted(path.resolve() for path in raw.glob("*/*.parquet") if path.is_file())


def dataset_files(data_root: Path, dataset: str) -> list[Path]:
    return sorted(path.resolve() for path in (data_root / "raw" / dataset).glob("*.parquet") if path.is_file())


def dataset_version(files: list[Path]) -> str:
    h = hashlib.sha256()
    for path in files:
        stat = path.stat()
        h.update(str(path).encode("utf-8"))
        h.update(str(stat.st_size).encode("ascii"))
        h.update(str(stat.st_mtime_ns).encode("ascii"))
    return h.hexdigest()


def file_version(path: Path) -> str:
    stat = path.stat()
    h = hashlib.sha256()
    h.update(str(path).encode("utf-8"))
    h.update(str(stat.st_size).encode("ascii"))
    h.update(str(stat.st_mtime_ns).encode("ascii"))
    return h.hexdigest()


def current_etl_version(conn, dataset: str) -> str:
    row = conn.execute(
        "SELECT source_version FROM data_etl_versions WHERE dataset=? AND status='success'",
        (dataset,),
    ).fetchone()
    return str(row[0]) if row else ""


def mark_etl_version(conn, dataset: str, version: str, file_count: int, row_count: int, status: str, message: str) -> None:
    current = now_text()
    conn.execute(
        upsert_sql(
            "data_etl_versions",
            ["dataset", "source_version", "file_count", "row_count", "status", "message", "updated_at"],
            ["dataset"],
            ["source_version", "file_count", "row_count", "status", "message", "updated_at"],
        ),
        (dataset, version, file_count, row_count, status, message, current),
    )


def current_file_version(conn, dataset: str, path: Path) -> str:
    row = conn.execute(
        "SELECT source_version FROM data_etl_files WHERE dataset=? AND file_path=? AND status='success'",
        (dataset, str(path)),
    ).fetchone()
    return str(row[0]) if row else ""


def mark_etl_file(conn, dataset: str, path: Path, version: str, row_count: int, status: str, message: str) -> None:
    current = now_text()
    conn.execute(
        upsert_sql(
            "data_etl_files",
            ["id", "dataset", "file_path", "source_version", "row_count", "status", "message", "updated_at"],
            ["id"],
            ["source_version", "row_count", "status", "message", "updated_at"],
        ),
        (etl_file_id(dataset, path), dataset, str(path), version, row_count, status, message, current),
    )


def changed_dataset_files(conn, dataset: str, files: list[Path]) -> list[tuple[Path, str]]:
    changed: list[tuple[Path, str]] = []
    for path in files:
        version = file_version(path)
        if current_file_version(conn, dataset, path) != version:
            changed.append((path, version))
    return changed


def all_file_versions_current(conn, dataset: str, files: list[Path]) -> bool:
    return all(current_file_version(conn, dataset, path) == file_version(path) for path in files)


def seed_file_versions(conn, dataset: str, files: list[Path]) -> None:
    for path in files:
        mark_etl_file(conn, dataset, path, file_version(path), parquet_row_count(path), "success", "seeded")


def clean_value(value: Any) -> Any:
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def frame_rows(frame, columns: list[str], updated_at: str) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    for row in frame.itertuples(index=False):
        values = list(row)
        out.append(tuple(clean_value(v) for v in values) + (updated_at,))
    return out


def read_dataset_frame(files: list[Path], columns: list[str]):
    import pandas as pd

    frames = []
    for path in files:
        frame = pd.read_parquet(path)
        for column in columns:
            if column not in frame.columns:
                frame[column] = None
        frames.append(frame[columns])
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def rename_output_columns(frame, mapping: dict[str, str]):
    if mapping:
        frame = frame.rename(columns=mapping)
    return frame


def fill_required_columns(frame, numeric_columns: set[str]):
    for column in frame.columns:
        if column in numeric_columns:
            frame[column] = frame[column].fillna(0)
        else:
            frame[column] = frame[column].fillna("")
    return frame


def upsert_dataset_rows(conn, table: str, key_columns: list[str], columns: list[str], rows: list[tuple[Any, ...]], batch_size: int = 5000) -> None:
    if not rows:
        return
    all_columns = columns + ["updated_at"]
    sql = upsert_sql(table, all_columns, key_columns, [col for col in all_columns if col not in key_columns])
    for start in range(0, len(rows), batch_size):
        conn.executemany(sql, rows[start : start + batch_size])


def max_text_value(conn, table: str, column: str) -> str:
    try:
        row = conn.execute(f"SELECT COALESCE(MAX({column}), '') FROM {table}").fetchone()
    except Exception:
        return ""
    return str(row[0] or "") if row else ""


def existing_key_set(conn, table: str, key_columns: list[str], keys: list[tuple[Any, ...]], batch_size: int = 1000) -> set[tuple[str, ...]]:
    if not keys:
        return set()
    existing: set[tuple[str, ...]] = set()
    where = " AND ".join(f"{column}=?" for column in key_columns)
    sql = f"SELECT {', '.join(key_columns)} FROM {table} WHERE {where}"
    for start in range(0, len(keys), batch_size):
        for key in keys[start : start + batch_size]:
            row = conn.execute(sql, key).fetchone()
            if row:
                existing.add(tuple(str(v) for v in row))
    return existing


def filter_incremental_frame(conn, dataset: str, table: str, frame, key_columns: list[str]):
    if dataset in {"daily", "daily_basic"}:
        max_date = max_text_value(conn, table, "trade_date")
        if max_date:
            return frame[frame["trade_date"].astype(str) > max_date]
        return frame
    if dataset == "fina_indicator":
        keys = [
            tuple(str(getattr(row, column)) for column in key_columns)
            for row in frame[key_columns].itertuples(index=False)
        ]
        existing = existing_key_set(conn, table, key_columns, keys)
        if not existing:
            return frame
        keep_mask = [key not in existing for key in keys]
        return frame[keep_mask]
    return frame


def sync_dataset(conn, data_root: Path, dataset: str) -> int:
    files = dataset_files(data_root, dataset)
    version = dataset_version(files)
    if version and current_etl_version(conn, dataset) == version:
        if not all_file_versions_current(conn, dataset, files):
            seed_file_versions(conn, dataset, files)
        return 0
    if not files:
        mark_etl_version(conn, dataset, version, 0, 0, "success", "no files")
        return 0
    try:
        import pandas  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError as exc:
        mark_etl_version(conn, dataset, version, len(files), 0, "skipped", f"missing parquet dependency: {exc}")
        return 0

    specs = {
        "stock_basic": (
            "data_stock_basic",
            ["ts_code"],
            ["ts_code", "symbol", "name", "area", "industry", "market", "list_date", "list_status"],
            {},
        ),
        "daily": (
            "data_daily_bars",
            ["ts_code", "trade_date"],
            ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
            {"change": "change_amount"},
        ),
        "daily_basic": (
            "data_daily_basic",
            ["ts_code", "trade_date"],
            ["ts_code", "trade_date", "close", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "total_mv", "circ_mv"],
            {},
        ),
        "fina_indicator": (
            "data_fina_indicator",
            ["ts_code", "end_date"],
            ["ts_code", "ann_date", "end_date", "eps", "roe", "grossprofit_margin", "netprofit_margin", "debt_to_assets"],
            {},
        ),
    }
    changed_files = changed_dataset_files(conn, dataset, files)
    if not changed_files:
        mark_etl_version(conn, dataset, version, len(files), 0, "success", "unchanged")
        return 0

    table, key_columns, source_columns, rename_map = specs[dataset]
    columns = [rename_map.get(column, column) for column in source_columns]
    numeric_columns = {
        "open", "high", "low", "close", "pre_close", "change_amount", "pct_chg", "vol", "amount",
        "pe", "pe_ttm", "pb", "ps", "ps_ttm", "total_mv", "circ_mv",
        "eps", "roe", "grossprofit_margin", "netprofit_margin", "debt_to_assets",
    }
    total_rows = 0
    for path, path_version in changed_files:
        frame = rename_output_columns(read_dataset_frame([path], source_columns), rename_map)
        frame = fill_required_columns(frame, numeric_columns)
        if key_columns:
            frame = frame.dropna(subset=key_columns)
            frame = frame.drop_duplicates(subset=key_columns, keep="last")
        frame = filter_incremental_frame(conn, dataset, table, frame, key_columns)
        rows = frame_rows(frame, columns, now_text())
        upsert_dataset_rows(conn, table, key_columns, columns, rows)
        mark_etl_file(conn, dataset, path, path_version, len(rows), "success", "incremental upsert")
        total_rows += len(rows)
    mark_etl_version(conn, dataset, version, len(files), total_rows, "success", f"upserted {len(changed_files)} files")
    return total_rows


def sync_mysql_tables(conn, data_root: Path) -> int:
    total = 0
    for dataset in SYNC_DATASETS:
        total += sync_dataset(conn, data_root, dataset)
    return total


def prune_missing(conn, scanned_paths: list[str]) -> None:
    if not scanned_paths:
        conn.execute("DELETE FROM data_market_files")
        return
    placeholders = ",".join("?" for _ in scanned_paths)
    conn.execute(f"DELETE FROM data_market_files WHERE file_path NOT IN ({placeholders})", tuple(scanned_paths))


def scan(data_root: Path, db_path: Path) -> int:
    files = iter_parquet_files(data_root)
    with connect_db(db_path) as conn:
        ensure_tables(conn)
        set_status(conn, "running", 0, len(files), "scan", "扫描本地 parquet 文件")
        scanned_paths: list[str] = []
        for idx, path in enumerate(files, start=1):
            data_type = path.parent.name
            partition = path.stem
            current = now_text()
            row_count = parquet_row_count(path)
            file_size = path.stat().st_size
            scanned_paths.append(str(path))
            conn.execute(
                upsert_sql(
                    "data_market_files",
                    ["id", "data_type", "partition_name", "file_path", "row_count", "file_size", "created_at", "updated_at"],
                    ["file_path"],
                    ["data_type", "partition_name", "row_count", "file_size", "updated_at"],
                ),
                (file_id(path), data_type, partition, str(path), row_count, file_size, current, current),
            )
            if idx == len(files) or idx % 5 == 0:
                set_status(conn, "running", idx, len(files), "scan", f"{data_type}/{path.name}")
        prune_missing(conn, scanned_paths)
        synced_rows = sync_mysql_tables(conn, data_root)
        set_status(conn, "success", len(files), len(files), "done", "本地数据文件索引已刷新", f"扫描 {len(files)} 个 parquet 文件，同步 {synced_rows} 行")
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--db-path", default="")
    args = parser.parse_args()
    data_root = Path(args.data_root).expanduser().resolve()
    db_path = Path(args.db_path).expanduser().resolve() if args.db_path else None
    try:
        count = scan(data_root, db_path)
        print(f"scanned {count} parquet files")
    except Exception as exc:
        with connect_db(db_path) as conn:
            ensure_tables(conn)
            set_status(conn, "error", 0, 0, "error", "本地数据文件扫描失败", str(exc))
        raise


if __name__ == "__main__":
    main()
