"""每日信号生成 + 推送 + 模拟盘记录 + SQLite 落库

行为：
  1. 拿全局 py 进程锁（同一时刻只能一个）
  2. 调 signal.generate 重新计算目标持仓与调仓清单
  3. signal.generate 自动写入 rec_daily_recommendations
  4. 刷新 portfolio_pool_summary 估值
  5. 输出 JSON / 文本报告 / 可选推送与模拟盘记录

参数：
  --date YYYYMMDD       目标交易日
  --json-only           仅 stdout JSON（供 desktop app 读取）
  --progress            stderr 输出 PROGRESS {idx,total,stage,name} 行
  --push                推送到钉钉/企微/邮件
  --paper               记录到模拟盘

环境变量：
  QUANT_CPU_LIMIT       默认 2，限制 BLAS/OMP 线程
  DESKTOP_DB_PATH       默认 <DATA_ROOT>/meta.db
  DATA_ROOT INITIAL_CASH REBALANCE_FREQ
"""
from __future__ import annotations

import os

# 限制 BLAS / OpenMP 线程，避免桌面端独占 CPU；可被 QUANT_CPU_LIMIT 覆盖
_cpu_limit = os.environ.get("QUANT_CPU_LIMIT", "2")
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, _cpu_limit)

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config import RAW_DIR
from trading.execution import signal as sig, notifier, paper_trade
from common.infra import LockBusyError, PyLock, status
from common.infra.db import desktop_db_path
from common.utils import get_logger

log = get_logger("daily_signal")

TASK_NAME = "daily_signal"


def _make_progress_cb(stderr_enabled: bool):
    def cb(idx, total, name, stage):
        try:
            status.progress(TASK_NAME, int(idx), int(total), str(stage or ""), str(name or ""))
        except Exception as exc:
            log.debug(f"status.progress failed: {exc}")
        if stderr_enabled:
            payload = {
                "idx": int(idx),
                "total": int(total),
                "stage": str(stage or ""),
                "name": str(name or ""),
            }
            print("PROGRESS " + json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)

    return cb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="目标交易日 YYYYMMDD")
    parser.add_argument("--json-only", action="store_true", help="仅输出 JSON")
    parser.add_argument("--progress", action="store_true", help="向 stderr 输出 PROGRESS 进度行")
    parser.add_argument("--push", action="store_true", help="推送到钉钉/企微/邮件")
    parser.add_argument("--paper", action="store_true", help="记录到模拟盘")
    args = parser.parse_args()

    progress_cb = _make_progress_cb(args.progress)
    print(
        "DIAG daily_signal "
        f"DATA_ROOT={os.environ.get('DATA_ROOT', '')} "
        f"DESKTOP_DB_PATH={os.environ.get('DESKTOP_DB_PATH', '')} "
        f"RAW_DIR={RAW_DIR} "
        f"desktop_db_path={desktop_db_path()}",
        file=sys.stderr,
        flush=True,
    )

    try:
        with PyLock("global", task=TASK_NAME):
            status.begin(TASK_NAME)
            try:
                payload = sig.generate(target_date=args.date, progress_cb=progress_cb)
                date_key = str(payload.get("date") or args.date or "")
                if date_key:
                    try:
                        from common.infra.pool import refresh_valuation
                        refresh_valuation(date_key)
                    except Exception as exc:
                        log.warning(f"refresh_valuation failed: {exc}")

                if args.json_only:
                    print(json.dumps(payload, ensure_ascii=False))
                else:
                    text = sig.format_report(payload)
                    print(text)
                    print("\n--- JSON ---")
                    print(json.dumps(payload, ensure_ascii=False, indent=2))

                if args.paper and payload.get("date"):
                    paper_trade.record_signal(payload["date"], payload)

                if args.push:
                    text = sig.format_report(payload)
                    result = notifier.broadcast(f"选股信号 {payload.get('date', '')}", text)
                    log.info(f"推送结果: {result}")

                status.done(TASK_NAME, message=str(payload.get("date") or ""))
            except Exception as exc:
                status.error(TASK_NAME, str(exc))
                raise
    except LockBusyError as exc:
        log.error(str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
