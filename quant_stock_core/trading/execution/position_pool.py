"""仓池：管理真实账户持仓 + 信号驱动调仓单 + 盈亏计算

数据存储：
- data_store/positions/pool.json          当前账户状态（现金 + 持仓 + 已平仓记录）
- data_store/positions/snapshots.parquet  每日快照（净值/现金/市值/盈亏）

核心流程：
  signal -> compute_rebalance(pool, signal, prices) -> 调仓单
  用户确认 -> confirm_trades(pool, trades)         -> 更新 pool.json
  收盘后 -> snapshot(pool, prices)                 -> 写入 snapshots.parquet
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from common.config import BACKTEST_DIR, RAW_DIR
from research.data.storage import duckdb_query as dq
from common.utils import get_logger

log = get_logger("pool")

POOL_DIR = BACKTEST_DIR.parent / "positions"
POOL_DIR.mkdir(parents=True, exist_ok=True)
POOL_PATH = POOL_DIR / "pool.json"
SNAPSHOT_PATH = POOL_DIR / "snapshots.parquet"

INITIAL_CASH: float = 500_000.0
LOT_SIZE: int = 100


# ──────────────────────────────────── 基础 IO ────────────────────────────────────

def empty_pool() -> dict:
    return {
        "initial_cash": INITIAL_CASH,
        "current_cash": INITIAL_CASH,
        "updated_at": "",
        "positions": [],
        "closed_positions": [],
    }


def load_pool() -> dict:
    if not POOL_PATH.exists():
        p = empty_pool()
        save_pool(p)
        return p
    with open(POOL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pool(pool: dict) -> Path:
    pool["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(POOL_PATH, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    return POOL_PATH


def reset_pool(initial_cash: float = INITIAL_CASH) -> dict:
    p = empty_pool()
    p["initial_cash"] = initial_cash
    p["current_cash"] = initial_cash
    save_pool(p)
    return p


def set_holder_account(pool: dict, ts_code: str, holder_account: str) -> dict:
    """更新某持仓的股东代码（沪 A / 深 A），便于券商对单。"""
    for p in pool["positions"]:
        if p["ts_code"] == ts_code:
            p["holder_account"] = holder_account
            save_pool(pool)
            return pool
    log.warning(f"set_holder_account: 仓池无 {ts_code}")
    return pool


# ──────────────────────────────────── 行情辅助 ────────────────────────────────────

def fetch_latest_prices(codes: list[str]) -> dict[str, float]:
    """取这些股票最近一个交易日的 close。"""
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, close
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE ts_code IN ({in_clause})
          AND trade_date = (SELECT MAX(trade_date)
                            FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}'))
    """)
    return {r["ts_code"]: float(r["close"]) for _, r in df.iterrows() if pd.notna(r["close"])}


def fetch_meta(codes: list[str]) -> dict[str, dict]:
    """取股票名称和行业。"""
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    try:
        df = dq.sql(f"""
            SELECT ts_code, name, industry
            FROM read_parquet('{RAW_DIR / "stock_basic" / "*.parquet"}')
            WHERE ts_code IN ({in_clause})
        """)
        return {r["ts_code"]: {"name": r["name"], "industry": r.get("industry") or "—"}
                for _, r in df.iterrows()}
    except Exception:
        return {}


def fetch_prev_close(codes: list[str]) -> dict[str, float]:
    """取这些股票最近一个交易日的 pre_close（即"昨日收盘"）。

    用于"今日盈亏" = shares × (当前价 − pre_close)。
    """
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    try:
        df = dq.sql(f"""
            SELECT ts_code, pre_close
            FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
            WHERE ts_code IN ({in_clause})
              AND trade_date = (SELECT MAX(trade_date)
                                FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}'))
        """)
        return {r["ts_code"]: float(r["pre_close"])
                for _, r in df.iterrows() if pd.notna(r["pre_close"])}
    except Exception as e:
        log.warning(f"取 pre_close 失败: {e}")
        return {}


def fetch_realtime_prices(codes: list[str]) -> dict[str, float]:
    """通过 akshare 拉 A 股实时报价（延迟约 3 分钟，免费）。

    失败时返回空 dict（调用方应回退到 daily close）。
    """
    if not codes:
        return {}
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {}
        # 列名："代码"=6位股票代码（无后缀）, "最新价"=当前价
        df = df[["代码", "最新价"]].rename(columns={"代码": "_code", "最新价": "_px"})
        df = df.dropna(subset=["_px"])
        # 把 '600000' / '000001' / '300750' / '688981' 映射回 ts_code 后缀
        wanted = {c.split(".")[0]: c for c in codes}
        out: dict[str, float] = {}
        for _, r in df.iterrows():
            raw = str(r["_code"]).zfill(6)
            if raw in wanted:
                try:
                    px = float(r["_px"])
                    if px > 0:
                        out[wanted[raw]] = px
                except (TypeError, ValueError):
                    continue
        log.info(f"akshare 实时报价命中 {len(out)}/{len(codes)}")
        return out
    except Exception as e:
        log.warning(f"akshare 实时报价获取失败: {e}")
        return {}


# ──────────────────────────────────── 调仓单 ────────────────────────────────────

def compute_rebalance(
    pool: dict,
    signal: dict,
    prices: dict[str, float] | None = None,
) -> list[dict]:
    """对比仓池 vs 信号目标，生成调仓单。

    Args:
        pool: 当前仓池
        signal: 信号字典 {date, holdings: [{ts_code, weight, sources}], ...}
        prices: 当前价（用于估算金额 + 计算目标股数）；缺省自动取最新

    Returns:
        list of dict: [
            {
              "ts_code", "name", "industry",
              "action": "BUY/ADD/TRIM/SELL/HOLD",
              "current_shares", "target_shares", "delta_shares",
              "price", "est_amount",
              "current_weight", "target_weight",
              "reason",  // 信号新建/升权/降权/剔除
              "sources": [{"strategy", "weight"}],
              "avg_cost",   // 仓池里的成本（新建则为 None）
              "unrealized_pnl",  // 当前浮盈，若新建为 None
            }
        ]
    """
    target_holdings = signal.get("holdings", [])
    target_weights = {h["ts_code"]: h["weight"] for h in target_holdings}
    target_sources = {h["ts_code"]: h.get("sources", []) for h in target_holdings}

    pool_map = {p["ts_code"]: p for p in pool["positions"]}
    all_codes = sorted(set(target_weights) | set(pool_map))

    if prices is None:
        prices = fetch_latest_prices(all_codes)
    meta = fetch_meta(all_codes)

    # 总资产估算（用于 weight -> shares）
    total_equity = pool["current_cash"]
    for p in pool["positions"]:
        total_equity += p["shares"] * prices.get(p["ts_code"], p["avg_cost"])

    rebalance = []
    for code in all_codes:
        target_w = target_weights.get(code, 0.0)
        cur_pos = pool_map.get(code)
        cur_shares = cur_pos["shares"] if cur_pos else 0
        avg_cost = cur_pos["avg_cost"] if cur_pos else None
        price = prices.get(code, avg_cost or 0.0)

        # 计算目标股数
        if target_w > 0 and price > 0:
            raw = (target_w * total_equity) / price
            target_shares = int(raw / LOT_SIZE) * LOT_SIZE
        else:
            target_shares = 0

        delta = target_shares - cur_shares

        # 当前权重（基于估算总资产）
        cur_value = cur_shares * price
        cur_w = cur_value / total_equity if total_equity > 0 else 0.0

        # 动作判定
        if cur_shares == 0 and target_shares > 0:
            action = "BUY"
            reason = "信号新建"
        elif cur_shares > 0 and target_shares == 0:
            action = "SELL"
            reason = "信号剔除"
        elif delta > 0:
            action = "ADD"
            reason = "信号升权"
        elif delta < 0:
            action = "TRIM"
            reason = "信号降权"
        else:
            action = "HOLD"
            reason = "持平"

        # 不到 1 手的差额忽略
        if abs(delta) < LOT_SIZE and action in ("ADD", "TRIM"):
            action = "HOLD"
            reason = "差额不足 1 手"
            delta = 0
            target_shares = cur_shares

        unrealized = None
        if cur_pos and price > 0:
            unrealized = cur_shares * (price - avg_cost)

        rebalance.append({
            "ts_code": code,
            "name": meta.get(code, {}).get("name", "—"),
            "industry": meta.get(code, {}).get("industry", "—"),
            "action": action,
            "current_shares": cur_shares,
            "target_shares": target_shares,
            "delta_shares": delta,
            "price": price,
            "est_amount": delta * price,  # 正=买入需要的钱，负=卖出回笼的钱
            "current_weight": cur_w,
            "target_weight": target_w,
            "avg_cost": avg_cost,
            "unrealized_pnl": unrealized,
            "sources": target_sources.get(code, []),
            "reason": reason,
        })

    # 排序：操作类（非 HOLD）在前，按 |est_amount| 降序
    rebalance.sort(key=lambda r: (r["action"] == "HOLD", -abs(r["est_amount"])))
    return rebalance


# ─────────────────────────────────── 确认成交 ───────────────────────────────────

def confirm_trades(pool: dict, trades: list[dict], date: str) -> dict:
    """根据用户确认的成交单更新仓池。

    Args:
        pool: 当前仓池（会被修改）
        trades: [{ts_code, action(BUY/ADD/TRIM/SELL), shares, price, sources?}]
        date:   成交日期 YYYYMMDD

    Returns:
        更新后的 pool
    """
    pool_map = {p["ts_code"]: p for p in pool["positions"]}
    meta_codes = [t["ts_code"] for t in trades]
    meta = fetch_meta(meta_codes)

    for t in trades:
        code = t["ts_code"]
        action = t["action"]
        shares = int(t["shares"])
        price = float(t["price"])
        amount = shares * price

        if action in ("BUY", "ADD"):
            pool["current_cash"] -= amount
            if code in pool_map:
                p = pool_map[code]
                # 加权平均成本
                old_cost = p["shares"] * p["avg_cost"]
                p["shares"] += shares
                p["avg_cost"] = (old_cost + amount) / p["shares"]
                p["last_action_date"] = date
                # 加仓价若高于历史峰值则刷新（保护移动止盈基线）
                p["peak_price"] = max(p.get("peak_price") or price, price)
                p["trades"].append({
                    "date": date, "action": action,
                    "shares": shares, "price": price, "amount": amount,
                })
            else:
                # 新建
                m = meta.get(code, {})
                pool["positions"].append({
                    "ts_code": code,
                    "name": m.get("name", "—"),
                    "industry": m.get("industry", "—"),
                    "shares": shares,
                    "avg_cost": price,
                    "peak_price": price,  # 持有期最高价（用于移动止盈）
                    "first_entry_date": date,
                    "last_action_date": date,
                    "trades": [{
                        "date": date, "action": "BUY",
                        "shares": shares, "price": price, "amount": amount,
                    }],
                    "sources": t.get("sources", []),
                    "holder_account": "",
                    "note": "",
                })
        elif action in ("TRIM", "SELL"):
            if code not in pool_map:
                log.warning(f"卖出 {code} 但仓池无此持仓，跳过")
                continue
            p = pool_map[code]
            shares = min(shares, p["shares"])
            amount = shares * price
            pool["current_cash"] += amount
            realized = shares * (price - p["avg_cost"])
            trade_record = {
                "date": date, "action": action,
                "shares": shares, "price": price, "amount": amount,
                "realized_pnl": realized,
            }
            # 透传强卖原因（来自 exit_rules）
            if t.get("exit_reason"):
                trade_record["exit_reason"] = t["exit_reason"]
            if t.get("exit_pct") is not None:
                trade_record["exit_pct"] = t["exit_pct"]
            p["trades"].append(trade_record)
            p["shares"] -= shares
            p["last_action_date"] = date

            if p["shares"] == 0:
                # 平仓 -> 移到 closed_positions
                first_date = p["first_entry_date"]
                hold_days = (datetime.strptime(date, "%Y%m%d")
                             - datetime.strptime(first_date, "%Y%m%d")).days
                total_realized = sum(tr.get("realized_pnl", 0) for tr in p["trades"])
                # 总买入金额 / 总买入股数 -> 反推持仓成本累计盈亏
                total_buy_amount = sum(tr["amount"] for tr in p["trades"]
                                       if tr["action"] in ("BUY", "ADD"))
                realized_pct = (total_realized / total_buy_amount) if total_buy_amount > 0 else 0
                # 找最后一笔 SELL 的 exit_reason（决定平仓性质）
                last_exit = None
                for tr in reversed(p["trades"]):
                    if tr.get("action") in ("SELL", "TRIM") and tr.get("exit_reason"):
                        last_exit = tr.get("exit_reason")
                        break
                pool["closed_positions"].append({
                    "ts_code": code,
                    "name": p["name"],
                    "industry": p["industry"],
                    "open_date": first_date,
                    "close_date": date,
                    "hold_days": hold_days,
                    "realized_pnl": total_realized,
                    "realized_pct": realized_pct,
                    "exit_reason": last_exit,  # stop_loss / trailing_stop / None(=信号剔除)
                    "open_sources": p.get("sources", []),  # 买入来源策略
                    "trades": p["trades"],
                })
                pool["positions"].remove(p)
                del pool_map[code]

    save_pool(pool)
    return pool


# ──────────────────────────────────── 盈亏快照 ────────────────────────────────────

def compute_pnl(pool: dict, prices: dict[str, float] | None = None,
                prev_closes: dict[str, float] | None = None,
                as_of_date: str | None = None) -> dict:
    """计算仓池当前盈亏快照。

    Args:
        pool: 仓池
        prices: 当前价（建议传实时价；缺省取 daily 最新 close）
        prev_closes: 昨日收盘价（用于"今日盈亏"）；缺省自动取
        as_of_date: 计算 hold_days 所用的"今天"YYYYMMDD；缺省=真实今天。
                    时光机回测时应传入回测当天的日期。

    Returns:
        {
          "cash", "market_value", "equity",
          "total_cost", "unrealized_pnl", "unrealized_pct",
          "today_pnl", "today_pct",
          "realized_pnl", "cum_return",
          "n_holdings", "n_closed",
          "positions": [{ts_code, name, shares, avg_cost, price, market_value,
                         cost, unrealized_pnl, unrealized_pct,
                         prev_close, today_pnl, today_pct,
                         weight, hold_days, holder_account, ...}]
        }
    """
    codes = [p["ts_code"] for p in pool["positions"]]
    if prices is None:
        prices = fetch_latest_prices(codes)
    if prev_closes is None:
        prev_closes = fetch_prev_close(codes)

    today = as_of_date or datetime.now().strftime("%Y%m%d")
    pos_view = []
    market_value = 0.0
    total_cost = 0.0
    today_pnl_sum = 0.0
    today_base_sum = 0.0  # 昨日市值，用于今日%
    for p in pool["positions"]:
        price = prices.get(p["ts_code"], p["avg_cost"])
        cost = p["shares"] * p["avg_cost"]
        mv = p["shares"] * price
        upnl = mv - cost
        upnl_pct = upnl / cost if cost > 0 else 0

        # 今日盈亏
        prev_c = prev_closes.get(p["ts_code"])
        if prev_c and prev_c > 0:
            today_pnl = p["shares"] * (price - prev_c)
            today_pct = (price - prev_c) / prev_c
            today_base = p["shares"] * prev_c
        else:
            today_pnl = 0.0
            today_pct = 0.0
            today_base = mv  # 兜底：用今日市值
        today_pnl_sum += today_pnl
        today_base_sum += today_base

        try:
            hold_days = (datetime.strptime(today, "%Y%m%d")
                         - datetime.strptime(p["first_entry_date"], "%Y%m%d")).days
        except Exception:
            hold_days = 0
        pos_view.append({
            **p,
            "price": price,
            "cost": cost,
            "market_value": mv,
            "unrealized_pnl": upnl,
            "unrealized_pct": upnl_pct,
            "prev_close": prev_c or 0.0,
            "today_pnl": today_pnl,
            "today_pct": today_pct,
            "hold_days": hold_days,
        })
        market_value += mv
        total_cost += cost

    realized_pnl = sum(c["realized_pnl"] for c in pool["closed_positions"])
    equity = pool["current_cash"] + market_value
    cum_return = (equity - pool["initial_cash"]) / pool["initial_cash"]

    # 持仓比例 = 个股市值 / 总资产（=权益）
    for v in pos_view:
        v["weight"] = (v["market_value"] / equity) if equity > 0 else 0.0

    today_pct_total = (today_pnl_sum / today_base_sum) if today_base_sum > 0 else 0.0

    return {
        "cash": pool["current_cash"],
        "market_value": market_value,
        "equity": equity,
        "total_cost": total_cost,
        "unrealized_pnl": market_value - total_cost,
        "unrealized_pct": (market_value - total_cost) / total_cost if total_cost > 0 else 0,
        "today_pnl": today_pnl_sum,
        "today_pct": today_pct_total,
        "realized_pnl": realized_pnl,
        "cum_return": cum_return,
        "n_holdings": len(pool["positions"]),
        "n_closed": len(pool["closed_positions"]),
        "positions": pos_view,
        "initial_cash": pool["initial_cash"],
    }


def snapshot(pool: dict, date: str | None = None,
             prices: dict[str, float] | None = None) -> Path:
    """落盘当日快照到 snapshots.parquet。"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    pnl = compute_pnl(pool, prices)
    row = {
        "date": date,
        "cash": pnl["cash"],
        "market_value": pnl["market_value"],
        "equity": pnl["equity"],
        "n_holdings": pnl["n_holdings"],
        "unrealized_pnl": pnl["unrealized_pnl"],
        "realized_pnl": pnl["realized_pnl"],
        "cum_return": pnl["cum_return"],
    }
    if SNAPSHOT_PATH.exists():
        df = pd.read_parquet(SNAPSHOT_PATH)
        df = df[df["date"] != date]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df = df.sort_values("date").reset_index(drop=True)
    df.to_parquet(SNAPSHOT_PATH, compression="zstd", index=False)
    return SNAPSHOT_PATH


def load_snapshots() -> pd.DataFrame:
    if not SNAPSHOT_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(SNAPSHOT_PATH)
