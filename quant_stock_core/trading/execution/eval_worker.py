"""后台评估 CLI 入口：被 eval_runner 以独立子进程（subprocess）方式拉起。

用法（由 eval_runner.start_eval 自动调用，一般不手动执行）：
    python -m trading.execution.eval_worker '<json-encoded-kwargs>'

设计要点：
  - 独立进程，完全脱离 Streamlit 的 __main__，互不影响（页面切走/重启都不影响本进程）。
  - 跑 run_time_machine（其内部已写 running/心跳/done 状态）。
  - 捕获任何异常 → 写 failed 状态。
  - 进程被强杀来不及写 failed → 靠 time_machine.reconcile_statuses() 心跳超时兜底 interrupted。
"""
from __future__ import annotations

import json
import signal
import sys
import time
import traceback


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m trading.execution.eval_worker '<json-kwargs>'", file=sys.stderr)
        return 2

    kwargs = json.loads(argv[1])
    run_id = kwargs["run_id"]

    from trading.execution import time_machine as tm

    def _handle_term(signum, frame):  # noqa: ARG001
        try:
            tm.write_status(
                run_id,
                status="cancelled",
                error="用户手动取消评估",
                cancelled=True,
                cancelled_at=time.time(),
                heartbeat=time.time(),
            )
        finally:
            raise SystemExit(143)

    signal.signal(signal.SIGTERM, _handle_term)

    try:
        tm.run_time_machine(
            start_date=kwargs["start_date"],
            end_date=kwargs["end_date"],
            initial_cash=kwargs["initial_cash"],
            run_id=run_id,
            rebalance_freq=kwargs["rebalance_freq"],
            exit_rules_cfg=kwargs["exit_rules_cfg"],
            strategies_filter=kwargs["strategies_filter"],
            eval_name=kwargs["eval_name"],
            progress_cb=None,  # 后台进程不回调 UI，只靠 status.json 汇报
        )
        return 0
    except SystemExit as e:
        return int(e.code or 143)
    except BaseException as e:  # noqa: BLE001
        tb = traceback.format_exc()
        try:
            tm.write_status(
                run_id,
                status="failed",
                error=f"{type(e).__name__}: {e}",
                traceback=tb[-2000:],
                failed_at=time.time(),
                heartbeat=time.time(),
            )
        except Exception:
            pass
        print(tb, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
