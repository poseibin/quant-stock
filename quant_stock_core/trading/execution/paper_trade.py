"""模拟盘记录器

按收盘价模拟成交，每日更新持仓与净值，落盘 parquet。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from common.config import BACKTEST_DIR
from research.data.storage import duckdb_query as dq
from common.utils import get_logger

log = get_logger("paper")

PAPER_DIR = BACKTEST_DIR / "paper_trade"
PAPER_DIR.mkdir(parents=True, exist_ok=True)

INITIAL_CASH: float = 500_000.0  # 起始资金 50 万
LOT_SIZE: int = 100              # A 股一手 = 100 股


def record_signal(date: str, signal: dict) -> Path:
    """把当日信号 + 收盘价快照保存为模拟成交记录。"""
    holdings = signal.get("holdings", [])
    if not holdings:
        log.info(f"{date} 信号为空，跳过记录")
        return None

    codes = [h["ts_code"] for h in holdings]
    sql = ",".join(f"'{c}'" for c in codes)
    px = dq.sql(f"""
        SELECT ts_code, close
        FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
        WHERE ts_code IN ({sql}) AND trade_date = '{date}'
    """)
    px_map = px.set_index("ts_code")["close"].to_dict() if not px.empty else {}

    rows = [{
        "date": date,
        "ts_code": h["ts_code"],
        "weight": h["weight"],
        "close": float(px_map.get(h["ts_code"], 0.0)),
        "recorded_at": datetime.now().isoformat(),
    } for h in holdings]

    df = pd.DataFrame(rows)
    # 建仓预算 / 股数 / 实际成本（按 LOT_SIZE 取整）
    df["target_cash"] = df["weight"] * INITIAL_CASH
    df["shares"] = 0
    df["cost"] = 0.0
    mask = df["close"] > 0
    df.loc[mask, "shares"] = (
        (df.loc[mask, "target_cash"] / df.loc[mask, "close"] // LOT_SIZE) * LOT_SIZE
    ).astype(int)
    df["cost"] = df["shares"] * df["close"]
    path = PAPER_DIR / f"holdings_{date}.parquet"
    df.to_parquet(path, compression="zstd", index=False)
    log.info(f"模拟盘记录写入 {path}")
    return path


def load_history() -> pd.DataFrame:
    files = sorted(PAPER_DIR.glob("holdings_*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def compute_equity_curve() -> pd.DataFrame:
    """根据历史信号 + 实际收盘价回算每日净值。"""
    hist = load_history()
    if hist.empty:
        return pd.DataFrame()

    rows = []
    dates = sorted(hist["date"].unique())
    prev_close: dict[str, float] = {}
    prev_weight: pd.Series = pd.Series(dtype=float)
    equity = 1.0

    for d in dates:
        snap = hist[hist["date"] == d].set_index("ts_code")
        codes = list(snap.index)
        if not codes:
            continue
        cur_close = dq.sql(f"""
            SELECT ts_code, close FROM read_parquet('{dq.RAW_DIR / "daily" / "*.parquet"}')
            WHERE ts_code IN ({",".join(f"'{c}'" for c in codes)})
              AND trade_date = '{d}'
        """).set_index("ts_code")["close"].to_dict()

        # 用前一日权重 + 当日相对前一日的涨跌
        if not prev_weight.empty and prev_close:
            day_ret = 0.0
            for code, w in prev_weight.items():
                p0 = prev_close.get(code)
                p1 = cur_close.get(code)
                if p0 and p1:
                    day_ret += w * (p1 / p0 - 1)
            equity *= (1 + day_ret)

        rows.append({"date": d, "equity": equity, "n_holdings": len(codes)})

        prev_weight = snap["weight"]
        prev_close = cur_close

    return pd.DataFrame(rows)
