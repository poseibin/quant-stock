"""硬性卖出规则（止损 / 移动止盈）。

与"目标持仓换名单"类型的 SELL 不同——这里是不论信号怎么样，
持仓触发风控线就刻强立卖。每个交易日都会扫描（不仅限于调仓日）。

规则：
  1. 成本止损 stop_loss：(current - avg_cost) / avg_cost <= 阈值（默认 -12%）
  2. 移动止盈 trailing_stop：(current - peak_<= 阈值（默认 -8price) / peak_price %）
     注意：必须 current > avg_cost（已盈利）才触发，避免亏损时被双杀

字段约定：
  - 触发后产出的 trade dict 带 exit_reason: "stop_loss" | "trailing_stop"
  - position_pool.confirm_trades 会把 exit_reason 透传到 trades 记录里
  - peak_price：每日按当日 close 累加最大值，新建持仓时初始化为买入价
"""
from __future__ import annotations


def update_peak_prices(pool: dict, prices: dict[str, float]) -> None:
    """每日按当日 close 更新所有持仓的 peak_price（持有期最高价）。

    新建持仓时已经初始化 peak_price = avg_cost；这里负责持续抬高。
    """
    for p in pool["positions"]:
        cur = prices.get(p["ts_code"])
        if cur is None or cur <= 0:
            continue
        prev_peak = p.get("peak_price") or p.get("avg_cost") or cur
        if cur > prev_peak:
            p["peak_price"] = cur
        elif "peak_price" not in p:
            # 老仓池没有 peak_price 字段，补一个
            p["peak_price"] = max(prev_peak, cur)


def scan(pool: dict, prices: dict[str, float], as_of_date: str,
         rules: dict | None) -> list[dict]:
    """扫描持仓，返回需要强卖的 trade 列表（已可直接喂给 confirm_trades）。

    Args:
        pool: 当前仓池
        prices: 当日参考成交价（回测 = 当日 close，实盘 = 实时价）
        as_of_date: 当前日期 YYYYMMDD（保留参数，便于未来加"持有期上限"）
        rules: {enabled, stop_loss, trailing_stop}；缺失或 enabled=False 则跳过

    Returns:
        [{ts_code, name, action="SELL", shares, price, exit_reason, exit_pct}, ...]
    """
    if not rules or not rules.get("enabled", False):
        return []
    sl = float(rules.get("stop_loss", -0.12))
    ts = float(rules.get("trailing_stop", -0.08))

    forced: list[dict] = []
    for p in pool["positions"]:
        code = p["ts_code"]
        cur = prices.get(code)
        if cur is None or cur <= 0:
            continue
        avg_cost = p.get("avg_cost") or 0
        if avg_cost <= 0:
            continue

        # 1) 成本止损：跌破成本 sl
        cost_pct = (cur - avg_cost) / avg_cost
        if cost_pct <= sl:
            forced.append({
                "ts_code": code,
                "name": p.get("name", ""),
                "action": "SELL",
                "shares": p["shares"],
                "price": cur,
                "exit_reason": "stop_loss",
                "exit_pct": cost_pct,
            })
            continue

        # 2) 移动止盈：从持有期最高价回撤 ts；且必须已盈利才止盈
        if cur > avg_cost:
            peak = p.get("peak_price") or avg_cost
            if peak > 0:
                trail_pct = (cur - peak) / peak
                if trail_pct <= ts:
                    forced.append({
                        "ts_code": code,
                        "name": p.get("name", ""),
                        "action": "SELL",
                        "shares": p["shares"],
                        "price": cur,
                        "exit_reason": "trailing_stop",
                        "exit_pct": trail_pct,
                    })

    return forced
