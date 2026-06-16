"""Tushare data update worker for the desktop app.

Go starts this script and keeps rendering MySQL status. Python owns the data
pulling and parquet writes because pandas/pyarrow handles the wide financial
tables more predictably than the Go parquet writer.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra.db import add_column, connect_db, table_columns, upsert_sql

TASK = "data_update"
DATA_START_DATE = "20100101"
ENDPOINT = "https://api.tushare.pro"
PAGE_LIMIT = 2000
INDEX_BASIC_MARKETS = ("SSE", "SZSE", "CSI", "CNI")
INDEX_ANCHOR_CODES = (
    "000300.SH",  # 沪深300
    "000905.SH",  # 中证500
    "000852.SH",  # 中证1000
    "932000.CSI",  # 中证2000
    "399303.SZ",  # 国证2000
)


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    category: str
    partition: str
    pk: tuple[str, ...]
    date_field: str = ""


DATASETS: dict[str, DatasetSpec] = {
    "stock_basic": DatasetSpec("stock_basic", "basic", "single", ("ts_code",)),
    "index_basic": DatasetSpec("index_basic", "basic", "single", ("ts_code",)),
    "trade_cal": DatasetSpec("trade_cal", "basic", "single", ("cal_date",)),
    "index_daily": DatasetSpec("index_daily", "price", "year", ("ts_code", "trade_date"), "trade_date"),
    "daily": DatasetSpec("daily", "price", "year", ("ts_code", "trade_date"), "trade_date"),
    "daily_basic": DatasetSpec("daily_basic", "price", "year", ("ts_code", "trade_date"), "trade_date"),
    "adj_factor": DatasetSpec("adj_factor", "price", "year", ("ts_code", "trade_date"), "trade_date"),
    "income": DatasetSpec("income", "finance", "year", ("ts_code", "end_date", "report_type"), "end_date"),
    "balancesheet": DatasetSpec("balancesheet", "finance", "year", ("ts_code", "end_date", "report_type"), "end_date"),
    "cashflow": DatasetSpec("cashflow", "finance", "year", ("ts_code", "end_date", "report_type"), "end_date"),
    "fina_indicator": DatasetSpec("fina_indicator", "finance", "year", ("ts_code", "end_date"), "end_date"),
    "forecast": DatasetSpec("forecast", "finance", "year", ("ts_code", "ann_date", "end_date"), "ann_date"),
    "stk_holdertrade": DatasetSpec("stk_holdertrade", "event", "year", ("ts_code", "ann_date", "holder_name", "in_de"), "ann_date"),
    "top10_holders": DatasetSpec("top10_holders", "event", "year", ("ts_code", "end_date", "holder_name"), "end_date"),
    "top_list": DatasetSpec("top_list", "event", "year", ("ts_code", "trade_date", "reason"), "trade_date"),
    "top_inst": DatasetSpec("top_inst", "event", "year", ("ts_code", "trade_date", "exalter", "reason"), "trade_date"),
}

PHASES: dict[str, list[str]] = {
    "basic": ["stock_basic", "index_basic", "trade_cal"],
    "price": ["index_daily", "daily", "daily_basic", "adj_factor"],
    "finance": ["income", "balancesheet", "cashflow", "fina_indicator", "forecast"],
    "event": ["stk_holdertrade", "top_list", "top_inst", "top10_holders"],
}

API_INTERVAL = {
    "stock_basic": 1.0,
    "index_basic": 1.0,
    "index_daily": 1.2,
    "trade_cal": 1.0,
    "daily": 1.2,
    "daily_basic": 1.5,
    "adj_factor": 1.2,
    "income": 2.0,
    "income_vip": 2.0,
    "balancesheet": 2.0,
    "balancesheet_vip": 2.0,
    "cashflow": 2.0,
    "cashflow_vip": 2.0,
    "fina_indicator": 2.0,
    "fina_indicator_vip": 2.0,
    "forecast": 2.0,
    "forecast_vip": 2.0,
    "stk_holdertrade": 2.5,
    "top10_holders": 2.5,
    "top_list": 2.0,
    "top_inst": 2.0,
}


class TushareError(RuntimeError):
    pass


class TushareClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self._last_call = 0.0

    def call(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> pd.DataFrame:
        interval = API_INTERVAL.get(api_name, 1.2)
        wait = self._last_call + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": fields,
        }
        resp = requests.post(ENDPOINT, json=payload, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        if int(body.get("code") or 0) != 0:
            raise TushareError(str(body.get("msg") or body))
        data = body.get("data") or {}
        cols = data.get("fields") or []
        items = data.get("items") or []
        return pd.DataFrame(items, columns=cols)

    def call_paged(self, api_name: str, params: dict[str, Any] | None = None, fields: str = "") -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        offset = 0
        while True:
            page_params = dict(params or {})
            page_params["limit"] = PAGE_LIMIT
            if offset:
                page_params["offset"] = offset
            df = self.call(api_name, page_params, fields)
            if not df.empty:
                frames.append(df)
            if len(df) < PAGE_LIMIT:
                break
            offset += len(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def call_with_fallback(self, apis: list[str], params: dict[str, Any], fields: str = "") -> tuple[pd.DataFrame, str]:
        last_error: Exception | None = None
        for api in apis:
            try:
                return self.call_paged(api, params, fields), api
            except Exception as exc:
                last_error = exc
                if not is_hard_limit(exc):
                    raise
                print(f"[data_update] {api} limited, trying fallback: {exc}", flush=True)
        raise last_error or TushareError("/".join(apis) + " failed")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def today() -> str:
    return datetime.now().strftime("%Y%m%d")


def shift_date(value: str, days: int) -> str:
    return (datetime.strptime(value, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def normalize_date(value: str) -> str:
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s[:8] if len(s) >= 8 else ""


def is_hard_limit(exc: Exception) -> bool:
    text = str(exc)
    keys = ["权限", "权限不够", "访问接口", "每分钟最多", "调用次数", "积分", "limit", "permission"]
    return any(k.lower() in text.lower() for k in keys)


def periods_between(start: str, end: str) -> list[str]:
    if len(start) < 4 or len(end) < 4:
        return []
    out: list[str] = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        for suffix in ("0331", "0630", "0930", "1231"):
            p = f"{year}{suffix}"
            if start <= p <= end:
                out.append(p)
    return out


def year_ranges_between(start: str, end: str) -> list[tuple[str, str]]:
    if len(start) < 4 or len(end) < 4:
        return []
    out: list[tuple[str, str]] = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        begin = max(start, f"{year}0101")
        finish = min(end, f"{year}1231")
        if begin <= finish:
            out.append((begin, finish))
    return out


class StatusStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.conn = connect_db(db_path, isolation_level=None)
        self.ensure_tables()

    def ensure_tables(self) -> None:
        if self.conn.backend == "mysql":
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS task_run_status (
                    task VARCHAR(255) PRIMARY KEY, task_type VARCHAR(255) NOT NULL DEFAULT '',
                    state VARCHAR(255) NOT NULL, idx BIGINT NOT NULL DEFAULT 0,
                    total BIGINT NOT NULL DEFAULT 0, stage VARCHAR(255), name VARCHAR(255), message LONGTEXT,
                    worker_pid BIGINT, started_at VARCHAR(64), updated_at VARCHAR(64) NOT NULL, finished_at VARCHAR(64)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS task_jobs (
                    id VARCHAR(255) PRIMARY KEY, name VARCHAR(255) NOT NULL, task_type VARCHAR(255) NOT NULL,
                    status VARCHAR(255) NOT NULL, progress DOUBLE NOT NULL DEFAULT 0,
                    params_json LONGTEXT NOT NULL, summary_json LONGTEXT, result_path VARCHAR(1024), log_path VARCHAR(1024),
                    worker_type VARCHAR(255) NOT NULL DEFAULT '', worker_pid BIGINT, external_run_id VARCHAR(255),
                    error_message LONGTEXT, parent_id VARCHAR(255), group_run_id VARCHAR(255), subtask_key VARCHAR(255),
                    subtask_name VARCHAR(255), sequence BIGINT NOT NULL DEFAULT 0, total BIGINT NOT NULL DEFAULT 0,
                    attempt BIGINT NOT NULL DEFAULT 0, max_attempts BIGINT NOT NULL DEFAULT 1,
                    created_at VARCHAR(64) NOT NULL, queued_at VARCHAR(64), started_at VARCHAR(64),
                    finished_at VARCHAR(64), updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
            )
        else:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS task_run_status (
                    task TEXT PRIMARY KEY, task_type TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL, idx INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0, stage TEXT, name TEXT, message TEXT,
                    worker_pid INTEGER, started_at TEXT, updated_at TEXT NOT NULL, finished_at TEXT
                )"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS task_jobs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, task_type TEXT NOT NULL, status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0, params_json TEXT NOT NULL, summary_json TEXT,
                    result_path TEXT, log_path TEXT, worker_type TEXT NOT NULL DEFAULT '', worker_pid INTEGER,
                    external_run_id TEXT, error_message TEXT, parent_id TEXT, group_run_id TEXT, subtask_key TEXT,
                    subtask_name TEXT, sequence INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, queued_at TEXT, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL
                )"""
            )
        columns = table_columns(self.conn, "task_run_status")
        if "task_type" not in columns:
            add_column(self.conn, "task_run_status", "task_type", "TEXT NOT NULL DEFAULT ''")
        if "worker_pid" not in columns:
            add_column(self.conn, "task_run_status", "worker_pid", "INTEGER")

    def begin(self, total: int) -> None:
        ts = now()
        columns = ["task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"]
        self.conn.execute(
            upsert_sql("task_run_status", columns, ["task"], ["task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"]),
            (TASK, "data_update", "running", 0, total, "", "", "", os.getpid(), ts, ts, ""),
        )

    def progress(self, idx: int, total: int, stage: str, name: str, message: str) -> None:
        self.conn.execute(
            "UPDATE task_run_status SET task_type='data_update', idx=?, total=?, stage=?, name=?, message=?, worker_pid=?, updated_at=? WHERE task=?",
            (idx, total, stage, name, message, os.getpid(), now(), TASK),
        )

    def done(self, message: str) -> None:
        ts = now()
        self.conn.execute(
            "UPDATE task_run_status SET state='success', message=?, worker_pid=NULL, updated_at=?, finished_at=? WHERE task=?",
            (message, ts, ts, TASK),
        )

    def error(self, message: str) -> None:
        ts = now()
        columns = ["task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"]
        self.conn.execute(
            upsert_sql("task_run_status", columns, ["task"], ["task_type", "state", "message", "worker_pid", "updated_at", "finished_at"]),
            (TASK, "data_update", "error", 0, 0, "", "", message, None, ts, ts, ts),
        )
        self.conn.execute(
            """UPDATE task_jobs SET status='failed', error_message=?, finished_at=?, updated_at=?
               WHERE task_type='data_update' AND status IN ('created','queued','running')""",
            (message, ts, ts),
        )

    def mark_pending(self, names: list[str]) -> None:
        ts = now()
        total = len(names)
        for idx, name in enumerate(names, start=1):
            self._upsert_dataset_task(name, "queued", 0, 0, "", 0, "", "", "", ts, idx, total)

    def dataset_begin(self, name: str) -> None:
        ts = now()
        self._upsert_dataset_task(name, "running", 0, 0, "", 0, "", ts, "", ts, 0, 0)

    def dataset_progress(self, name: str, done: int, total: int, message: str) -> None:
        self.conn.execute(
            "UPDATE task_jobs SET progress=?, summary_json=?, worker_pid=?, updated_at=? WHERE task_type='data_update' AND subtask_key=?",
            (self._progress_ratio(done, total), self._summary_json(name, done, total, message, 0, ""), os.getpid(), now(), name),
        )

    def dataset_success(self, name: str, rows: int, message: str) -> None:
        ts = now()
        self.conn.execute(
            """UPDATE task_jobs SET status='success', progress=1, summary_json=?, error_message='',
               worker_pid=NULL, finished_at=?, updated_at=? WHERE task_type='data_update' AND subtask_key=?""",
            (self._summary_json(name, 1, 1, message, rows, ""), ts, ts, name),
        )

    def dataset_failed(self, name: str, rows: int, message: str) -> None:
        ts = now()
        self.conn.execute(
            """UPDATE task_jobs SET status='failed', summary_json=?, error_message=?,
               worker_pid=NULL, finished_at=?, updated_at=? WHERE task_type='data_update' AND subtask_key=?""",
            (self._summary_json(name, 0, 0, message, rows, message), message, ts, ts, name),
        )

    def _upsert_dataset_task(
        self,
        name: str,
        status: str,
        done: int,
        total: int,
        message: str,
        rows: int,
        error: str,
        started_at: str,
        finished_at: str,
        updated_at: str,
        sequence: int,
        sequence_total: int,
    ) -> None:
        spec = DATASETS[name]
        columns = [
            "id", "name", "task_type", "status", "progress", "params_json", "summary_json",
            "result_path", "log_path", "worker_type", "worker_pid", "external_run_id", "error_message",
            "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total",
            "attempt", "max_attempts", "created_at", "queued_at", "started_at", "finished_at", "updated_at",
        ]
        self.conn.execute(
            upsert_sql(
                "task_jobs",
                columns,
                ["id"],
                ["name", "status", "progress", "params_json", "summary_json", "worker_type", "worker_pid", "error_message", "subtask_key", "subtask_name", "sequence", "total", "queued_at", "started_at", "finished_at", "updated_at"],
            ),
            (
                f"data_update:{name}", name, "data_update", status, self._progress_ratio(done, total),
                json.dumps({"dataset": name, "category": spec.category}, ensure_ascii=False),
                self._summary_json(name, done, total, message, rows, error),
                "", "", "python", os.getpid(), "", error, TASK, TASK, name, name, sequence, sequence_total,
                0, 1, updated_at, updated_at if status == "queued" else "", started_at, finished_at, updated_at,
            ),
        )

    @staticmethod
    def _progress_ratio(done: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, done / total))

    def _summary_json(self, name: str, done: int, total: int, message: str, rows: int, error: str) -> str:
        spec = DATASETS[name]
        return json.dumps(
            {
                "dataset": name,
                "category": spec.category,
                "progress_done": done,
                "progress_total": total,
                "message": message,
                "rows_written": rows,
                "error_message": error,
            },
            ensure_ascii=False,
        )


class DataStore:
    def __init__(self, data_root: Path) -> None:
        self.raw = data_root / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)

    def dataset_dir(self, dataset: str) -> Path:
        p = self.raw / dataset
        p.mkdir(parents=True, exist_ok=True)
        return p

    def file_path(self, dataset: str, year: str | int | None = None) -> Path:
        spec = DATASETS[dataset]
        if spec.partition == "single":
            return self.dataset_dir(dataset) / "data.parquet"
        return self.dataset_dir(dataset) / f"year={year}.parquet"

    def read_file(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def read_dataset(self, dataset: str) -> pd.DataFrame:
        files = sorted(self.dataset_dir(dataset).glob("*.parquet"))
        frames = [pd.read_parquet(p) for p in files if p.exists()]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def existing_values(self, dataset: str, field: str) -> set[str]:
        values: set[str] = set()
        for path in sorted(self.dataset_dir(dataset).glob("*.parquet")):
            try:
                df = pd.read_parquet(path, columns=[field])
            except Exception:
                continue
            if field in df.columns:
                values.update(normalize_date(v) for v in df[field].dropna().unique())
        return {v for v in values if v}

    def latest_date(self, dataset: str, field: str) -> str:
        values = self.existing_values(dataset, field)
        return max(values) if values else ""

    def write_upsert(self, dataset: str, df: pd.DataFrame, overwrite: bool = False) -> int:
        if df.empty:
            return 0
        spec = DATASETS[dataset]
        if spec.partition == "single":
            return self._write_file(self.file_path(dataset), dataset, df, overwrite)
        if not spec.date_field or spec.date_field not in df.columns:
            raise RuntimeError(f"{dataset}: missing date field {spec.date_field}")
        total = 0
        work = df.copy()
        work[spec.date_field] = work[spec.date_field].astype(str)
        for year, part in work.groupby(work[spec.date_field].str.slice(0, 4)):
            if not str(year).isdigit():
                continue
            total += self._write_file(self.file_path(dataset, year), dataset, part, overwrite=False)
        return total

    def _write_file(self, path: Path, dataset: str, incoming: pd.DataFrame, overwrite: bool) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        spec = DATASETS[dataset]
        if overwrite or not path.exists():
            out = incoming.copy()
        else:
            old = self.read_file(path)
            out = pd.concat([old, incoming], ignore_index=True, sort=False)
        pk = [c for c in spec.pk if c in out.columns]
        if pk:
            for col in pk:
                out[col] = out[col].astype(str)
            out = out.drop_duplicates(subset=pk, keep="last")
        out = out.reindex(sorted(out.columns), axis=1)
        tmp = path.with_suffix(".tmp.parquet")
        out.to_parquet(tmp, compression="zstd", index=False)
        tmp.replace(path)
        return len(out)


class Worker:
    def __init__(self, token: str, data_root: Path, db_path: Path | None, phase: str, start_date: str, dataset: str = "", exclude_datasets: str = "") -> None:
        self.client = TushareClient(token)
        self.store = DataStore(data_root)
        self.status = StatusStore(db_path)
        self.phase = phase if phase in PHASES else "all"
        self.start_date = normalize_date(start_date)
        self.dataset = str(dataset or "").strip()
        self.exclude_datasets = {item.strip() for item in str(exclude_datasets or "").split(",") if item.strip()}

    def jobs(self) -> list[str]:
        if self.dataset:
            if self.dataset not in DATASETS:
                raise RuntimeError(f"未知数据集: {self.dataset}")
            return [self.dataset]
        if self.phase == "all":
            out: list[str] = []
            for names in PHASES.values():
                out.extend(names)
            return [name for name in out if name not in self.exclude_datasets]
        return [name for name in PHASES[self.phase] if name not in self.exclude_datasets]

    def run(self) -> None:
        jobs = self.jobs()
        self.status.begin(len(jobs))
        self.status.mark_pending(jobs)
        failed: list[str] = []
        for idx, name in enumerate(jobs, start=1):
            self.status.progress(idx, len(jobs), DATASETS[name].category, name, "running")
            self.status.dataset_begin(name)
            rows = 0
            try:
                rows = self.run_one(name)
                self.status.dataset_success(name, rows, f"写入/保留 {rows} 行")
            except Exception as exc:
                msg = self.reason(name, exc)
                failed.append(name)
                self.status.dataset_failed(name, rows, msg)
                print(f"[data_update] {name} failed: {msg}", flush=True)
        if failed:
            self.status.error("失败: " + ", ".join(failed))
        else:
            self.status.done("数据更新完成")

    def reason(self, name: str, exc: Exception) -> str:
        text = str(exc)
        if is_hard_limit(exc):
            return f"{name} API 受限: {text}"
        return f"{name} 更新失败: {text}"

    def run_one(self, name: str) -> int:
        if name == "stock_basic":
            return self.update_stock_basic()
        if name == "index_basic":
            return self.update_index_basic()
        if name == "trade_cal":
            return self.update_trade_cal()
        if name == "index_daily":
            return self.update_index_daily()
        if name in ("daily", "daily_basic", "adj_factor"):
            return self.update_by_trade_date(name, backfill_history=True)
        if name == "income":
            return self.update_finance_period(name, ["income_vip", "income"])
        if name == "balancesheet":
            return self.update_finance_period(name, ["balancesheet_vip", "balancesheet"])
        if name == "cashflow":
            return self.update_finance_period(name, ["cashflow_vip", "cashflow"])
        if name == "fina_indicator":
            return self.update_finance_period(name, ["fina_indicator_vip", "fina_indicator"])
        if name == "forecast":
            return self.update_ann_range(name, ["forecast_vip", "forecast"])
        if name == "stk_holdertrade":
            return self.update_ann_range(name, ["stk_holdertrade"])
        if name == "top10_holders":
            return self.update_top10_holders()
        if name in ("top_list", "top_inst"):
            return self.update_by_trade_date(name, backfill_history=False)
        raise RuntimeError(f"unknown dataset {name}")

    def update_stock_basic(self) -> int:
        fields = "ts_code,symbol,name,area,industry,fullname,market,exchange,list_status,list_date,delist_date,is_hs"
        frames: list[pd.DataFrame] = []
        for i, status in enumerate(["L", "D", "P"], start=1):
            self.status.dataset_progress("stock_basic", i, 3, f"list_status={status}")
            frames.append(self.client.call("stock_basic", {"exchange": "", "list_status": status}, fields))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return self.store.write_upsert("stock_basic", df, overwrite=True)

    def update_index_basic(self) -> int:
        fields = "ts_code,name,fullname,market,publisher,index_type,category,base_date,base_point,list_date,weight_rule,desc,exp_date"
        frames: list[pd.DataFrame] = []
        soft_errors: list[str] = []
        for i, market in enumerate(INDEX_BASIC_MARKETS, start=1):
            self.status.dataset_progress("index_basic", i, len(INDEX_BASIC_MARKETS), f"market={market}")
            try:
                df = self.client.call("index_basic", {"market": market}, fields)
            except Exception as exc:
                soft_errors.append(f"{market}: {exc}")
                continue
            if not df.empty:
                frames.append(df)
        if not frames:
            raise RuntimeError("; ".join(soft_errors[:5]) or "index_basic 未返回数据")
        df = pd.concat(frames, ignore_index=True)
        return self.store.write_upsert("index_basic", df, overwrite=True)

    def update_trade_cal(self) -> int:
        self.status.dataset_progress("trade_cal", 0, 1, f"{DATA_START_DATE}..{today()}")
        df = self.client.call(
            "trade_cal",
            {"exchange": "SSE", "start_date": DATA_START_DATE, "end_date": today()},
            "exchange,cal_date,is_open,pretrade_date",
        )
        self.status.dataset_progress("trade_cal", 1, 1, f"rows={len(df)}")
        return self.store.write_upsert("trade_cal", df, overwrite=True)

    def update_index_daily(self) -> int:
        start = self.start_date or self.incremental_start("index_daily", "trade_date")
        end = today()
        if start > end:
            return 0
        ranges = year_ranges_between(start, end)
        fields = "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount"
        total_steps = len(INDEX_ANCHOR_CODES) * len(ranges)
        total = 0
        ok_codes: set[str] = set()
        soft_errors: list[str] = []
        step = 0
        for ts_code in INDEX_ANCHOR_CODES:
            for begin, finish in ranges:
                step += 1
                self.status.dataset_progress("index_daily", step, total_steps, f"{ts_code} {begin}..{finish} rows={total}")
                try:
                    df = self.client.call_paged(
                        "index_daily",
                        {"ts_code": ts_code, "start_date": begin, "end_date": finish},
                        fields,
                    )
                except Exception as exc:
                    soft_errors.append(f"{ts_code} {begin}..{finish}: {exc}")
                    continue
                if not df.empty:
                    ok_codes.add(ts_code)
                    total += self.store.write_upsert("index_daily", df)
        if total == 0 and soft_errors:
            raise RuntimeError("; ".join(soft_errors[:5]))
        self.status.dataset_progress("index_daily", total_steps, total_steps, f"codes={','.join(sorted(ok_codes))} rows={total}")
        return total

    def update_top10_holders(self) -> int:
        start = self.store.latest_date("top10_holders", "end_date")
        if start:
            start = shift_date(start, -120)
        else:
            # top10_holders requires ts_code, so an all-history first run would
            # call the API once per stock over many years. Keep the default
            # first run practical; pass --start-date for deeper backfill.
            start = self.start_date or shift_date(today(), -760)
        end = today()
        if start > end:
            return 0
        stock_basic = self.store.read_file(self.store.file_path("stock_basic"))
        if stock_basic.empty or "ts_code" not in stock_basic.columns:
            raise RuntimeError("top10_holders 需要 stock_basic 股票列表，请先更新股票基础信息")
        if "list_status" in stock_basic.columns:
            stock_basic = stock_basic[stock_basic["list_status"].astype(str).isin(["L", "P"])]
        stocks = sorted({str(v).strip() for v in stock_basic["ts_code"].dropna().tolist() if str(v).strip()})
        if not stocks:
            raise RuntimeError("top10_holders 未找到可查询股票代码")
        total = 0
        soft_errors: list[str] = []
        fields = "ts_code,ann_date,end_date,holder_name,hold_amount,hold_ratio,hold_float_ratio,hold_change,holder_type"
        for i, ts_code in enumerate(stocks, start=1):
            self.status.dataset_progress("top10_holders", i, len(stocks), f"{ts_code} {start}..{end} rows={total}")
            try:
                df = self.client.call_paged(
                    "top10_holders",
                    {"ts_code": ts_code, "start_date": start, "end_date": end},
                    fields,
                )
            except Exception as exc:
                if is_hard_limit(exc):
                    raise TushareError(f"top10_holders {ts_code} {exc}") from exc
                soft_errors.append(f"{ts_code}: {exc}")
                continue
            if not df.empty:
                total += self.store.write_upsert("top10_holders", df)
        if total == 0 and soft_errors:
            raise RuntimeError("; ".join(soft_errors[:5]))
        self.status.dataset_progress("top10_holders", len(stocks), len(stocks), f"rows={total}")
        return total

    def trade_dates(self, start: str, end: str) -> list[str]:
        df = self.store.read_file(self.store.file_path("trade_cal"))
        if df.empty:
            raise RuntimeError("trade_cal 数据未初始化，请先运行基础阶段")
        df["cal_date"] = df["cal_date"].astype(str)
        open_mask = df["is_open"].astype(str).isin(["1", "1.0", "true", "True"])
        values = df.loc[open_mask, "cal_date"].tolist()
        return sorted(v for v in values if start <= v <= end)

    def ensure_trade_cal_current(self) -> None:
        latest = self.store.latest_date("trade_cal", "cal_date")
        if latest >= today():
            return
        df = self.client.call(
            "trade_cal",
            {"exchange": "SSE", "start_date": DATA_START_DATE, "end_date": today()},
            "exchange,cal_date,is_open,pretrade_date",
        )
        self.store.write_upsert("trade_cal", df, overwrite=True)

    def update_by_trade_date(self, dataset: str, backfill_history: bool) -> int:
        self.ensure_trade_cal_current()
        start = self.start_date or (DATA_START_DATE if backfill_history else self.incremental_start(dataset, "trade_date"))
        dates = self.trade_dates(start, today())
        existing = self.store.existing_values(dataset, "trade_date")
        pending = sorted((d for d in dates if d not in existing), reverse=True)
        if not pending:
            self.status.dataset_progress(dataset, 0, 0, "无缺失交易日")
            return 0
        total = 0
        hard_error: Exception | None = None
        for i, d in enumerate(pending, start=1):
            self.status.dataset_progress(dataset, i, len(pending), d)
            try:
                df = self.client.call(dataset, {"trade_date": d}, "")
            except Exception as exc:
                if is_hard_limit(exc):
                    hard_error = TushareError(f"{dataset} trade_date={d} {exc}")
                    break
                print(f"[data_update] {dataset} {d} soft failure: {exc}", flush=True)
                continue
            if not df.empty:
                total += self.store.write_upsert(dataset, df)
        if hard_error:
            raise hard_error
        return total

    def incremental_start(self, dataset: str, field: str) -> str:
        latest = self.store.latest_date(dataset, field)
        return shift_date(latest, 1) if latest else DATA_START_DATE

    def update_finance_period(self, dataset: str, apis: list[str]) -> int:
        start = self.start_date or DATA_START_DATE
        periods = periods_between(start, today())
        existing = self.store.existing_values(dataset, "end_date")
        pending = sorted((p for p in periods if p not in existing), reverse=True)
        if not pending:
            self.status.dataset_progress(dataset, 0, 0, "最新 period 已有，历史也无缺口")
            return 0
        total = 0
        hard_error: Exception | None = None
        soft_errors: list[str] = []
        for i, period in enumerate(pending, start=1):
            self.status.dataset_progress(dataset, i, len(pending), period)
            try:
                df, used_api = self.client.call_with_fallback(apis, {"period": period})
                if used_api != apis[0]:
                    self.status.dataset_progress(dataset, i, len(pending), f"{period} via {used_api}")
            except Exception as exc:
                if is_hard_limit(exc):
                    hard_error = TushareError(f"{'/'.join(apis)} period={period} {exc}")
                    break
                soft_errors.append(f"{period}: {exc}")
                continue
            if not df.empty:
                total += self.store.write_upsert(dataset, df)
        if hard_error:
            raise hard_error
        if total == 0 and soft_errors:
            raise RuntimeError("; ".join(soft_errors[:3]))
        return total

    def update_ann_range(self, dataset: str, apis: list[str]) -> int:
        latest = self.store.latest_date(dataset, "ann_date")
        end = today()
        if self.start_date:
            ranges = year_ranges_between(self.start_date, end)
        else:
            existing_years = {value[:4] for value in self.store.existing_values(dataset, "ann_date") if len(value) >= 4}
            expected_years = {str(year) for year in range(int(DATA_START_DATE[:4]), int(end[:4]) + 1)}
            missing_years = sorted(expected_years - existing_years, reverse=True)
            ranges = [(max(f"{year}0101", DATA_START_DATE), min(f"{year}1231", end)) for year in missing_years]
            if latest:
                recent_start = shift_date(latest, -7)
                if recent_start <= end:
                    ranges.insert(0, (recent_start, end))
            elif not ranges:
                ranges = year_ranges_between(DATA_START_DATE, end)
        if not ranges:
            self.status.dataset_progress(dataset, 0, 0, "最新增量已有，历史也无缺口")
            return 0
        total = 0
        hard_error: Exception | None = None
        soft_errors: list[str] = []
        for i, (start, finish) in enumerate(ranges, start=1):
            self.status.dataset_progress(dataset, i, len(ranges), f"{start}..{finish}")
            try:
                if len(apis) == 1:
                    df = self.client.call_paged(apis[0], {"start_date": start, "end_date": finish})
                else:
                    df, used_api = self.client.call_with_fallback(apis, {"start_date": start, "end_date": finish})
                    if used_api != apis[0]:
                        self.status.dataset_progress(dataset, i, len(ranges), f"{start}..{finish} via {used_api}")
            except Exception as exc:
                if is_hard_limit(exc):
                    hard_error = TushareError(f"{'/'.join(apis)} {start}..{finish} {exc}")
                    break
                soft_errors.append(f"{start}..{finish}: {exc}")
                continue
            if not df.empty:
                total += self.store.write_upsert(dataset, df)
        if hard_error:
            raise hard_error
        if total == 0 and soft_errors:
            raise RuntimeError("; ".join(soft_errors[:3]))
        self.status.dataset_progress(dataset, len(ranges), len(ranges), f"rows={total}")
        return total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="all")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--exclude-datasets", default="")
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN", ""))
    parser.add_argument("--data-path", default=os.getenv("DATA_ROOT", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = Path(args.data_path or os.getenv("DATA_ROOT", "")).expanduser().resolve()
    status = StatusStore(None)

    def handle_signal(signum: int, _frame: Any) -> None:
        status.error(f"更新进程收到退出信号 {signum}")
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        token = str(args.token or "").strip()
        if not token:
            raise RuntimeError("Tushare Token 未设置，请在设置页填写")
        if not str(data_root):
            raise RuntimeError("数据路径未设置")
        worker = Worker(
            token,
            data_root,
            None,
            str(args.phase or "all").strip().lower(),
            str(args.start_date or ""),
            str(args.dataset or ""),
            str(args.exclude_datasets or ""),
        )
        worker.run()
        return 0
    except Exception as exc:
        status.error(str(exc))
        print(f"[data_update] fatal: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
