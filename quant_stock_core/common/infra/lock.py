"""跨进程互斥锁（基于共享 SQLite）

同一时刻全局只允许一个 quant_stock_core 进程在跑。
进入锁后开后台心跳线程；超过 stale_seconds 没心跳的视为僵尸，可被夺锁。
"""
from __future__ import annotations

import os
import socket
import threading
import time
from datetime import datetime, timedelta

from .db import open_db


class LockBusyError(RuntimeError):
    pass


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


class PyLock:
    def __init__(
        self,
        name: str = "global",
        task: str | None = None,
        stale_seconds: int = 120,
        heartbeat_seconds: int = 30,
    ) -> None:
        self.name = name
        self.task = task or ""
        self.stale_seconds = stale_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._held = False

    def __enter__(self) -> "PyLock":
        self._acquire()
        self._held = True
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._held:
            try:
                with open_db() as conn:
                    conn.execute("DELETE FROM py_run_lock WHERE name = ? AND pid = ?", (self.name, os.getpid()))
            except Exception:
                pass
            self._held = False

    def _acquire(self) -> None:
        pid = os.getpid()
        host = socket.gethostname()
        now = _now_str()
        with open_db() as conn:
            row = conn.execute(
                "SELECT pid, hostname, heartbeat, task FROM py_run_lock WHERE name = ?",
                (self.name,),
            ).fetchone()
            if row is not None:
                heartbeat = _parse(row[2])
                stale_threshold = datetime.now() - timedelta(seconds=self.stale_seconds)
                if heartbeat is None or heartbeat < stale_threshold:
                    conn.execute("DELETE FROM py_run_lock WHERE name = ?", (self.name,))
                else:
                    raise LockBusyError(
                        f"py_run_lock '{self.name}' busy: pid={row[0]} host={row[1]} task={row[3]} heartbeat={row[2]}"
                    )
            conn.execute(
                "INSERT INTO py_run_lock(name, pid, hostname, acquired_at, heartbeat, task) VALUES(?,?,?,?,?,?)",
                (self.name, pid, host, now, now, self.task),
            )

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                with open_db() as conn:
                    conn.execute(
                        "UPDATE py_run_lock SET heartbeat = ? WHERE name = ? AND pid = ?",
                        (_now_str(), self.name, os.getpid()),
                    )
            except Exception:
                time.sleep(1)
