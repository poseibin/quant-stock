"""Unified entry point for PyInstaller packaging.

Usage (mirrors original python invocations):
  quant_worker scripts/daily_signal.py [args...]
  quant_worker scripts/data_update_worker.py [args...]
  quant_worker scripts/scan_market_files.py [args...]
  quant_worker scripts/limit_breakout_worker.py [args...]
  quant_worker scripts/limit_up_momentum_worker.py [args...]
  quant_worker scripts/evaluate_strategies.py [args...]
  quant_worker scripts/crash_warning_model_worker.py [args...]
  quant_worker scripts/optimize_portfolio.py [args...]
  quant_worker scripts/run_portfolio_candidate.py [args...]
  quant_worker scripts/pool_confirm.py [args...]
  quant_worker -m trading.execution.eval_worker [args...]
"""
from __future__ import annotations

import sys
import os


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: quant_worker <script_or_module> [args...]", file=sys.stderr)
        sys.exit(1)

    first = sys.argv[1]

    if first == "-m" and len(sys.argv) >= 3:
        module_name = sys.argv[2]
        sys.argv = [module_name] + sys.argv[3:]
        import runpy
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        return

    script_path = first
    sys.argv = [script_path] + sys.argv[2:]

    script_map = {
        "scripts/daily_signal.py": "scripts.daily_signal",
        "scripts/data_update_worker.py": "scripts.data_update_worker",
        "scripts/scan_market_files.py": "scripts.scan_market_files",
        "scripts/limit_breakout_worker.py": "scripts.limit_breakout_worker",
        "scripts/limit_up_momentum_worker.py": "scripts.limit_up_momentum_worker",
        "scripts/evaluate_strategies.py": "scripts.evaluate_strategies",
        "scripts/crash_warning_model_worker.py": "scripts.crash_warning_model_worker",
        "scripts/optimize_portfolio.py": "scripts.optimize_portfolio",
        "scripts/run_portfolio_candidate.py": "scripts.run_portfolio_candidate",
        "scripts/pool_confirm.py": "scripts.pool_confirm",
        "scripts/run_backtest.py": "scripts.run_backtest",
    }

    normalized = script_path.replace(os.sep, "/")
    module_name = script_map.get(normalized)
    if module_name is None:
        for key, mod in script_map.items():
            if normalized.endswith(key):
                module_name = mod
                break

    if module_name is None:
        print(f"Unknown script: {script_path}", file=sys.stderr)
        sys.exit(1)

    import runpy
    runpy.run_module(module_name, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
