"""每日信号生成

生成下一交易日的目标持仓与买卖建议。

设计原则：
  - 唯一存储：SQLite 表 daily_recommendation（按 date 主键），不再有任何文件缓存。
  - prev（"上一次持仓"）= pool_holdings 当前实盘权重。
    → 持仓为空 → buy/sell 全部基于 0 权重对比 → 不会出现"减仓/清仓"幽灵。
  - 每次调用 generate() 都重新跑策略 combiner，永不命中缓存。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from common.config.desktop_settings import load_portfolio_risk
from research.data.storage import duckdb_query as dq
from common.infra import get_recommendation, upsert_recommendation
from trading.strategy import combiner
from common.utils import get_logger

log = get_logger("signal")


def _load_pool_weights() -> dict[str, float]:
    """从 pool_holdings 读当前实盘权重作为 prev。失败时返回空 dict。"""
    try:
        from common.infra.pool import current_holdings_for_signal
        rows = current_holdings_for_signal()
        return {r["ts_code"]: float(r.get("weight") or 0.0) for r in rows if r.get("ts_code")}
    except Exception as exc:
        log.warning(f"加载 pool_holdings 失败，prev 视为空: {exc}")
        return {}


def _load_meta(codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    try:
        basic = dq.get_stock_basic()
    except Exception as exc:
        log.warning(f"get_stock_basic 失败: {exc}")
        return {}
    if basic.empty:
        return {}
    sub = basic[basic["ts_code"].isin(codes)]
    out: dict[str, dict] = {}
    for _, row in sub.iterrows():
        out[str(row["ts_code"])] = {
            "name": str(row.get("name") or ""),
            "industry": str(row.get("industry") or ""),
        }
    return out


def _load_close(codes: list[str], date: str) -> dict[str, dict]:
    """取 date 当日 close + pre_close → {ts_code: {close, pct_chg}}。"""
    if not codes or not date:
        return {}
    try:
        from research.data.storage.duckdb_query import get_price
        start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=15)).strftime("%Y%m%d")
        df = get_price(ts_codes=codes, start=start, end=date,
                       cols=("ts_code", "trade_date", "close", "pre_close"))
    except Exception as exc:
        log.warning(f"get_price 失败: {exc}")
        return {}
    if df.empty:
        return {}
    df = df.sort_values(["ts_code", "trade_date"])
    last = df.groupby("ts_code").tail(1)
    out: dict[str, dict] = {}
    for _, row in last.iterrows():
        close_val = float(row["close"]) if row["close"] is not None else 0.0
        pre_close = float(row["pre_close"]) if row["pre_close"] not in (None, 0) else 0.0
        pct = ((close_val - pre_close) / pre_close * 100.0) if pre_close > 0 else 0.0
        out[str(row["ts_code"])] = {"close": close_val, "pct_chg": pct}
    return out


def _action_label(from_w: float, to_w: float) -> str:
    eps = 1e-6
    if from_w <= eps and to_w > eps:
        return "新建"
    if to_w <= eps and from_w > eps:
        return "清仓"
    if to_w > from_w + eps:
        return "加仓"
    if to_w < from_w - eps:
        return "减仓"
    return "持平"


def generate(
    target_date: str | None = None,
    *,
    lookback_days: int = 90,
    progress_cb=None,
    strategies_filter: list[str] | None = None,
    persist: bool = True,
    prev_weights: dict[str, float] | None = None,
) -> dict:
    """生成 target_date 的目标持仓信号。

    流程：
      1. 跑 combiner.combine() 拿全市场目标权重 latest
      2. prev = prev_weights（显式传入）或从 pool_holdings 读（实盘默认）
      3. 构造 rows：union(prev_codes, latest_codes)，每行 {action, from, to, delta, ...}
      4. persist=True → upsert 到 daily_recommendation 表（仅实盘）

    progress_cb: 可选回调 fn(idx, total, name, stage)。
    prev_weights: 显式提供 prev 权重表（回测时光机用，避免读到实盘账户）。
    """
    cal = dq.get_trade_dates()
    if not cal:
        raise RuntimeError("交易日历为空，请先运行 daily_update.py")

    if target_date is None:
        target_date = cal[-1]
    elif target_date not in cal:
        future = [d for d in cal if d >= target_date]
        target_date = future[0] if future else cal[-1]

    start = (datetime.strptime(target_date, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")

    strategies = combiner.load_all(
        enabled_only_for=strategies_filter,
        force_names=strategies_filter,
    )
    if not strategies:
        raise RuntimeError(
            "SQLite 配置表中没有启用的策略"
            + (f"（filter={strategies_filter}）" if strategies_filter else "")
        )

    risk_cfg = load_portfolio_risk()

    weights, attribution = combiner.combine(
        strategies, start, target_date,
        portfolio_risk=risk_cfg, progress_cb=progress_cb,
        return_attribution=True,
    )

    if weights.empty:
        latest = pd.Series(dtype=float)
        ref_date = target_date
    else:
        if target_date in weights.index:
            latest = weights.loc[target_date]
            ref_date = target_date
        else:
            latest = weights.iloc[-1]
            ref_date = weights.index[-1]
        latest = latest[latest > 0].sort_values(ascending=False)

    # prev：显式传入优先（回测），否则读实盘 pool_holdings
    prev_map = prev_weights if prev_weights is not None else _load_pool_weights()
    latest_map = {str(code): float(w) for code, w in latest.items()}

    union_codes = sorted(set(prev_map.keys()) | set(latest_map.keys()))
    meta_map = _load_meta(union_codes)
    bar_map = _load_close(union_codes, target_date)

    # 归因：对每只 latest 持仓股，找出贡献它的策略及权重
    sources_map: dict[str, list] = {}
    for code in latest_map.keys():
        sources = []
        for sname, panel in attribution.items():
            if code not in panel.columns:
                continue
            if ref_date in panel.index:
                sw = float(panel.loc[ref_date, code])
            else:
                col = panel[code]
                col = col[col.index <= ref_date]
                sw = float(col.iloc[-1]) if len(col) else 0.0
            if sw > 1e-6:
                sources.append({"strategy": sname, "weight": sw})
        sources.sort(key=lambda x: -x["weight"])
        sources_map[code] = sources

    # 估算下单股数（仅给 to_weight > 0 的标的）
    from trading.execution.paper_trade import INITIAL_CASH, LOT_SIZE

    rows: list[dict] = []
    eps = 1e-6
    for code in union_codes:
        from_w = prev_map.get(code, 0.0)
        to_w = latest_map.get(code, 0.0)
        if from_w <= eps and to_w <= eps:
            continue
        meta = meta_map.get(code, {})
        bar = bar_map.get(code, {})
        price = float(bar.get("close") or 0.0)
        target_shares = 0
        target_amount = 0.0
        if to_w > eps and price > 0:
            target_shares = int(to_w * INITIAL_CASH / price) // LOT_SIZE * LOT_SIZE
            target_amount = float(target_shares) * price
        rows.append({
            "action": _action_label(from_w, to_w),
            "ts_code": code,
            "name": meta.get("name", ""),
            "industry": meta.get("industry", ""),
            "from_weight": float(from_w),
            "to_weight": float(to_w),
            "delta_weight": float(to_w - from_w),
            "price": price,
            "pct_chg": float(bar.get("pct_chg") or 0.0),
            "target_shares": int(target_shares),
            "target_amount": float(target_amount),
            "sources": sources_map.get(code, []),
        })

    rows.sort(key=lambda r: abs(r["delta_weight"]), reverse=True)

    n_buy = sum(1 for r in rows if r["delta_weight"] > eps)
    n_sell = sum(1 for r in rows if r["delta_weight"] < -eps)
    n_holdings = sum(1 for r in rows if r["to_weight"] > eps)
    total_weight = sum(r["to_weight"] for r in rows)

    # 兼容旧消费方（paper_trade / validation）所需字段
    holdings = [
        {"ts_code": r["ts_code"], "weight": r["to_weight"], "sources": r["sources"]}
        for r in rows if r["to_weight"] > eps
    ]
    buy = [
        {"ts_code": r["ts_code"], "from": r["from_weight"], "to": r["to_weight"]}
        for r in rows if r["delta_weight"] > eps
    ]
    sell = [
        {"ts_code": r["ts_code"], "from": r["from_weight"], "to": r["to_weight"]}
        for r in rows if r["delta_weight"] < -eps
    ]

    payload = {
        "date": target_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
        "holdings": holdings,
        "trades": {"buy": buy, "sell": sell},
        "n_holdings": n_holdings,
        "n_buy": n_buy,
        "n_sell": n_sell,
        "total_weight": float(total_weight),
    }

    log.info(f"信号 {target_date}：rows={len(rows)} 持仓={n_holdings} 买入={n_buy} 卖出={n_sell}")

    if persist:
        try:
            upsert_recommendation(target_date, payload, payload["generated_at"])
        except Exception as exc:
            log.warning(f"upsert_recommendation 失败: {exc}")

    return payload


def load_latest() -> dict | None:
    """从 db 读最近一日的 daily_recommendation；空 → None。"""
    from common.infra.db import open_db
    with open_db() as conn:
        row = conn.execute(
            "SELECT date FROM daily_recommendation ORDER BY date DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return get_recommendation(row[0])


def list_dates() -> list[str]:
    """返回 db 中所有已存信号日期升序。"""
    from common.infra.db import open_db
    with open_db() as conn:
        rows = conn.execute(
            "SELECT date FROM daily_recommendation ORDER BY date ASC"
        ).fetchall()
    return [r[0] for r in rows]


def load_by_date(date: str) -> dict | None:
    return get_recommendation(date)


def format_report(signal: dict) -> str:
    """格式化为可读文本，用于推送。"""
    lines = [f"# 选股信号 {signal['date']}", ""]
    holdings = signal.get("holdings", [])
    trades = signal.get("trades", {})
    buy = trades.get("buy", [])
    sell = trades.get("sell", [])
    lines.append(f"## 持仓 ({len(holdings)} 只)")
    for h in holdings[:50]:
        lines.append(f"- {h['ts_code']}  {h['weight']*100:.2f}%")
    lines.append("")
    lines.append(f"## 调仓 - 买入 ({len(buy)} 笔)")
    for b in buy[:50]:
        lines.append(f"- 买入 {b['ts_code']}  {b['from']*100:.2f}% -> {b['to']*100:.2f}%")
    lines.append("")
    lines.append(f"## 调仓 - 卖出 ({len(sell)} 笔)")
    for s in sell[:50]:
        lines.append(f"- 卖出 {s['ts_code']}  {s['from']*100:.2f}% -> {s['to']*100:.2f}%")
    return "\n".join(lines)
