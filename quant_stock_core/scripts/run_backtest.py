"""单策略回测脚本

用法：
    python scripts/run_backtest.py --strategy small_cap_quality --start 20200101 --end 20241231
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading.backtest import run as bt_run, BacktestConfig, CostModel
from trading.strategy import registry
from common.utils import get_logger

log = get_logger("run_backtest")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=registry.all_names(), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--benchmark", default="000905.SH",
                        help="基准代码，默认中证 500")
    parser.add_argument("--slippage", type=float, default=0.002)
    parser.add_argument("--save", default=None, help="结果保存路径前缀")
    args = parser.parse_args()

    strategy = registry.build(args.strategy)

    log.info(f"生成 {args.strategy} 目标权重 [{args.start} -> {args.end}] ...")
    weights = strategy.generate_target_weights(args.start, args.end)
    if weights.empty:
        log.error("策略未生成任何持仓")
        return

    cfg = BacktestConfig(
        start=args.start,
        end=args.end,
        cost=CostModel(slippage=args.slippage),
        benchmark=args.benchmark,
    )
    log.info("开始回测...")
    result = bt_run(weights, cfg)

    print("\n=== 回测结果 ===")
    print(json.dumps(result.summary, ensure_ascii=False, indent=2, default=float))

    if args.save:
        from common.config import BACKTEST_DIR
        out_dir = BACKTEST_DIR / args.save
        out_dir.mkdir(parents=True, exist_ok=True)
        result.returns.to_csv(out_dir / "returns.csv")
        result.equity.to_csv(out_dir / "equity.csv")
        result.weights.to_parquet(out_dir / "weights.parquet")
        with open(out_dir / "summary.json", "w") as f:
            json.dump(result.summary, f, ensure_ascii=False, indent=2, default=float)
        log.info(f"结果已保存到 {out_dir}")


if __name__ == "__main__":
    main()
