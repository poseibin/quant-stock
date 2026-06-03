"""异步评估运行器：在独立子进程里跑时光机回测，状态机保证一致性。

设计目标（与页面线程解耦，避免"卡死"，且状态与磁盘一致）：
  - start_eval(): 用独立子进程（subprocess.Popen + 独立会话）跑 eval_worker，
    立即返回 run_id（不阻塞页面）。进程脱离 Streamlit，页面切走/重启都不影响。
  - 子进程内 run_time_machine：开始写 running、每个调仓日写心跳、正常完成写 done、
    抛异常写 failed。
  - 进程被强杀（来不及写 failed）→ 靠 time_machine.reconcile_statuses() 的心跳超时
    兜底改 interrupted。
  - 页面只读 status.json 轮询展示，随时可切走/刷新；子进程独立存活。

状态流转：
  pending → running → done
                   ↘ failed（代码异常）
                   ↘ interrupted（进程被杀 / 心跳超时 / 用户取消）
"""
from __future__ import annotations

import json
import os
import signal as _signal
import subprocess
import sys
import time
from datetime import datetime

from common.config import PROJECT_ROOT


def _make_run_id(start_date: str, end_date: str, strategies_filter, eval_name) -> str:
    tag = ""
    if strategies_filter and len(strategies_filter) == 1:
        tag = f"_{strategies_filter[0]}"
    elif strategies_filter:
        tag = f"_multi{len(strategies_filter)}"
    return f"tm{tag}_{start_date}_{end_date}_{datetime.now().strftime('%H%M%S')}"


def start_eval(
    *,
    start_date: str,
    end_date: str,
    initial_cash: float = 500_000.0,
    rebalance_freq: int = 5,
    exit_rules_cfg: dict | None = None,
    strategies_filter: list[str] | None = None,
    eval_name: str | None = None,
) -> str:
    """提交一次后台评估，立即返回 run_id（不阻塞调用方）。

    先把状态写成 pending（带 run_id + 元信息），再用独立子进程拉起 eval_worker。
    子进程起来后会把状态推进到 running。
    """
    from trading.execution import time_machine as tm

    run_id = _make_run_id(start_date, end_date, strategies_filter, eval_name)

    # 先落一份 pending（确保即便子进程起不来，列表页也能看到这条记录）
    tm.write_status(
        run_id,
        status="pending",
        eval_name=(eval_name or "").strip(),
        start=start_date,
        end=end_date,
        initial_cash=float(initial_cash),
        rebalance_freq=rebalance_freq,
        strategies_filter=list(strategies_filter) if strategies_filter else None,
        exit_rules=exit_rules_cfg or {},
        created_at=time.time(),
        heartbeat=time.time(),
        submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        progress={"cur_day": 0, "total_days": 0, "pct": 0.0, "stage": "pending", "eta_sec": 0},
    )

    kwargs = {
        "run_id": run_id,
        "start_date": start_date,
        "end_date": end_date,
        "initial_cash": float(initial_cash),
        "rebalance_freq": rebalance_freq,
        "exit_rules_cfg": exit_rules_cfg,
        "strategies_filter": list(strategies_filter) if strategies_filter else None,
        "eval_name": (eval_name or "").strip(),
    }

    # 独立子进程：start_new_session=True 让它脱离父进程会话，
    # 父进程（Streamlit）退出/重启都不会带走它。
    log_path = tm.TM_DIR / run_id / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "trading.execution.eval_worker", json.dumps(kwargs, ensure_ascii=False)],
        cwd=str(PROJECT_ROOT),
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    tm.write_status(run_id, pid=proc.pid)
    return run_id


def cancel_eval(run_id: str) -> bool:
    """取消一次正在运行的评估：终止其子进程并把状态置为 interrupted。

    返回是否成功发送终止信号。
    """
    from trading.execution import time_machine as tm

    s = tm.read_status(run_id)
    if not s:
        return False
    if s.get("status") not in ("running", "pending"):
        return False  # 已结束，无需取消

    pid = s.get("pid")
    killed = False
    if pid:
        try:
            # 子进程独立会话：杀整个进程组更彻底
            try:
                os.killpg(os.getpgid(int(pid)), _signal.SIGTERM)
            except Exception:
                os.kill(int(pid), _signal.SIGTERM)
            killed = True
        except ProcessLookupError:
            killed = True  # 进程已不在
        except Exception:
            killed = False

    tm.write_status(
        run_id,
        status="interrupted",
        error="用户手动取消评估",
        cancelled=True,
        interrupted_at=time.time(),
        heartbeat=time.time(),
    )
    return killed
