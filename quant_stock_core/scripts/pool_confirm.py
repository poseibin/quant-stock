"""确认成交脚本：读取 trades JSON 文件，写入 pool。

Usage:
  python scripts/pool_confirm.py --trades-json /path/to/trades.json

trades.json 内容：
  [
    {"ts_code": "000001.SZ", "side": "buy", "shares": 1000, "price": 12.34, "trade_date": "20260601"},
    ...
  ]

成功后 stdout 输出新的 summary JSON。
"""
from __future__ import annotations

import os

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

from common.infra.pool import confirm_trades
from common.utils import get_logger

log = get_logger("pool_confirm")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades-json", required=True, help="成交 JSON 文件路径")
    args = parser.parse_args()

    path = Path(args.trades_json).expanduser().resolve()
    if not path.exists():
        print(json.dumps({"error": f"trades file not found: {path}"}), file=sys.stderr)
        return 2

    try:
        with path.open("r", encoding="utf-8") as fh:
            trades = json.load(fh)
        if not isinstance(trades, list):
            print(json.dumps({"error": "trades must be a JSON array"}), file=sys.stderr)
            return 2

        summary = confirm_trades(trades)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        log.exception("pool_confirm failed")
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
