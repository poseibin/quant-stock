"""真实账户持仓管理（portfolio_pool_summary / portfolio_pool_holdings / portfolio_pool_trades）。

桌面 app 通过 Go 调用 daily_signal.py / pool_confirm.py 触发。
本模块负责所有 pool 表的读写，以及基于行情刷新估值。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from common.config import COMMISSION_RATE, DEFAULT_SLIPPAGE, STAMP_TAX_RATE
from common.infra.db import add_column, open_db, table_columns

INITIAL_CASH: float = 500_000.0
LOT_SIZE: int = 100


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _norm_trade_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("-", "")[:8]


def _trade_fee(amount: float, side: str, slippage: float | None = None) -> float:
    slip = DEFAULT_SLIPPAGE if slippage is None else float(slippage)
    rate = COMMISSION_RATE + slip
    if side == "sell":
        rate += STAMP_TAX_RATE
    return max(0.0, float(amount) * rate)


def _ensure_fee_columns(conn) -> None:
    cols = table_columns(conn, "portfolio_pool_trades")
    if "fee" not in cols:
        add_column(conn, "portfolio_pool_trades", "fee", "REAL NOT NULL DEFAULT 0")
    if "net_amount" not in cols:
        add_column(conn, "portfolio_pool_trades", "net_amount", "REAL NOT NULL DEFAULT 0")
    summary_cols = table_columns(conn, "portfolio_pool_summary")
    if "total_fee" not in summary_cols:
        add_column(conn, "portfolio_pool_summary", "total_fee", "REAL NOT NULL DEFAULT 0")


def list_summary() -> dict[str, Any]:
    with open_db() as conn:
        _ensure_fee_columns(conn)
        row = conn.execute(
            """SELECT initial_cash, current_cash, market_value, total_assets, total_cost,
                      COALESCE(total_fee,0), total_pnl, today_pnl, today_pct, unrealized_pnl, unrealized_pct,
                      realized_pnl, cum_return, n_closed, updated_at
               FROM portfolio_pool_summary WHERE id = 1"""
        ).fetchone()
    if not row:
        return {
            "initial_cash": INITIAL_CASH,
            "current_cash": INITIAL_CASH,
            "market_value": 0.0,
            "total_assets": INITIAL_CASH,
            "total_cost": 0.0,
            "total_fee": 0.0,
            "total_pnl": 0.0,
            "today_pnl": 0.0,
            "today_pct": 0.0,
            "unrealized_pnl": 0.0,
            "unrealized_pct": 0.0,
            "realized_pnl": 0.0,
            "cum_return": 0.0,
            "n_closed": 0,
            "updated_at": "",
        }
    return {
        "initial_cash": float(row[0] or 0),
        "current_cash": float(row[1] or 0),
        "market_value": float(row[2] or 0),
        "total_assets": float(row[3] or 0),
        "total_cost": float(row[4] or 0),
        "total_fee": float(row[5] or 0),
        "total_pnl": float(row[6] or 0),
        "today_pnl": float(row[7] or 0),
        "today_pct": float(row[8] or 0),
        "unrealized_pnl": float(row[9] or 0),
        "unrealized_pct": float(row[10] or 0),
        "realized_pnl": float(row[11] or 0),
        "cum_return": float(row[12] or 0),
        "n_closed": int(row[13] or 0),
        "updated_at": row[14] or "",
    }


def list_holdings() -> list[dict[str, Any]]:
    with open_db() as conn:
        rows = conn.execute(
            """SELECT ts_code, name, industry, shares, avg_cost, last_price,
                      market_value, weight, pnl, pnl_pct, open_date, updated_at
               FROM portfolio_pool_holdings WHERE shares > 0 ORDER BY weight DESC"""
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "ts_code": r[0],
                "name": r[1] or "",
                "industry": r[2] or "",
                "shares": int(r[3] or 0),
                "avg_cost": float(r[4] or 0),
                "last_price": float(r[5] or 0),
                "market_value": float(r[6] or 0),
                "weight": float(r[7] or 0),
                "pnl": float(r[8] or 0),
                "pnl_pct": float(r[9] or 0),
                "open_date": r[10] or "",
                "updated_at": r[11] or "",
            }
        )
    return out


def list_trades(limit: int = 200) -> list[dict[str, Any]]:
    with open_db() as conn:
        _ensure_fee_columns(conn)
        rows = conn.execute(
            """SELECT id, ts_code, side, shares, price, amount, trade_date, pnl, created_at,
                      COALESCE(fee,0), COALESCE(net_amount,0)
               FROM portfolio_pool_trades ORDER BY id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
    return [
        {
            "id": r[0],
            "ts_code": r[1],
            "side": r[2],
            "shares": int(r[3] or 0),
            "price": float(r[4] or 0),
            "amount": float(r[5] or 0),
            "trade_date": r[6] or "",
            "pnl": float(r[7] or 0),
            "created_at": r[8] or "",
            "fee": float(r[9] or 0),
            "net_amount": float(r[10] or 0),
        }
        for r in rows
    ]


def confirm_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """处理用户成交确认，更新 portfolio_pool_holdings + portfolio_pool_trades + portfolio_pool_summary。

    trades item: {ts_code, side(buy/sell), shares, price, trade_date}
    """
    if not trades:
        return list_summary()

    now = _now()
    with open_db() as conn:
        conn.execute("BEGIN")
        try:
            _ensure_fee_columns(conn)
            summary = conn.execute(
                "SELECT initial_cash, current_cash FROM portfolio_pool_summary WHERE id = 1"
            ).fetchone()
            if not summary:
                conn.execute(
                    """INSERT INTO portfolio_pool_summary(id, initial_cash, current_cash, total_assets, updated_at)
                       VALUES(1, ?, ?, ?, ?)""",
                    (INITIAL_CASH, INITIAL_CASH, INITIAL_CASH, now),
                )
                initial_cash = INITIAL_CASH
                current_cash = INITIAL_CASH
            else:
                initial_cash = float(summary[0] or INITIAL_CASH)
                current_cash = float(summary[1] or INITIAL_CASH)

            realized_pnl_total = 0.0
            for trade in trades:
                ts_code = str(trade.get("ts_code", "")).strip()
                side = str(trade.get("side", "")).strip().lower()
                shares = int(trade.get("shares") or 0)
                price = float(trade.get("price") or 0.0)
                trade_date = str(trade.get("trade_date") or now[:10].replace("-", ""))
                if not ts_code or shares <= 0 or price <= 0 or side not in ("buy", "sell"):
                    continue
                amount = price * shares
                fee = _trade_fee(amount, side, trade.get("slippage"))
                net_amount = amount + fee if side == "buy" else amount - fee

                row = conn.execute(
                    "SELECT shares, avg_cost FROM portfolio_pool_holdings WHERE ts_code = ?",
                    (ts_code,),
                ).fetchone()
                cur_shares = int(row[0]) if row else 0
                cur_cost = float(row[1]) if row else 0.0

                realized_pnl = 0.0
                if side == "buy":
                    if net_amount > current_cash + 1e-6:
                        raise ValueError(f"现金不足: 需要 {net_amount:.2f}, 仅有 {current_cash:.2f}")
                    new_shares = cur_shares + shares
                    new_cost = (cur_cost * cur_shares + amount) / new_shares if new_shares > 0 else 0.0
                    current_cash -= net_amount
                    if row:
                        conn.execute(
                            """UPDATE portfolio_pool_holdings SET shares=?, avg_cost=?, updated_at=?
                               WHERE ts_code=?""",
                            (new_shares, new_cost, now, ts_code),
                        )
                    else:
                        conn.execute(
                            """INSERT INTO portfolio_pool_holdings(ts_code, shares, avg_cost, last_price,
                               market_value, open_date, updated_at)
                               VALUES(?, ?, ?, ?, ?, ?, ?)""",
                            (ts_code, new_shares, new_cost, price, amount, trade_date, now),
                        )
                else:  # sell
                    if shares > cur_shares:
                        raise ValueError(f"卖出 {shares} 超过持仓 {cur_shares}: {ts_code}")
                    realized_pnl = (price - cur_cost) * shares - fee
                    new_shares = cur_shares - shares
                    current_cash += net_amount
                    realized_pnl_total += realized_pnl
                    if new_shares > 0:
                        conn.execute(
                            "UPDATE portfolio_pool_holdings SET shares=?, updated_at=? WHERE ts_code=?",
                            (new_shares, now, ts_code),
                        )
                    else:
                        conn.execute("DELETE FROM portfolio_pool_holdings WHERE ts_code=?", (ts_code,))

                conn.execute(
                    """INSERT INTO portfolio_pool_trades(ts_code, side, shares, price, amount, trade_date, pnl, created_at, fee, net_amount)
                       VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ts_code, side, shares, price, amount, trade_date, realized_pnl, now, fee, net_amount),
                )

            conn.execute(
                """UPDATE portfolio_pool_summary SET current_cash=?, updated_at=?
                       , total_pnl = total_pnl + ?
                       , total_fee = COALESCE(total_fee,0) + (
                         SELECT COALESCE(SUM(fee),0) FROM portfolio_pool_trades WHERE created_at = ?
                       )
                   WHERE id=1""",
                (current_cash, now, realized_pnl_total, now),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    refresh_valuation()
    return list_summary()


def refresh_valuation(date: str | None = None) -> None:
    """用最新行情刷新 portfolio_pool_holdings.last_price/market_value/weight/pnl 与 portfolio_pool_summary。"""
    holdings_rows = list_holdings()
    if not holdings_rows:
        with open_db() as conn:
            row = conn.execute(
                "SELECT current_cash, initial_cash FROM portfolio_pool_summary WHERE id=1"
            ).fetchone()
            current_cash = float(row[0] or INITIAL_CASH) if row else INITIAL_CASH
            initial_cash = float(row[1] or INITIAL_CASH) if row else INITIAL_CASH
            realized = conn.execute(
                "SELECT COALESCE(SUM(pnl),0) FROM portfolio_pool_trades WHERE side='sell'"
            ).fetchone()
            realized_total = float(realized[0]) if realized else 0.0
            n_closed = conn.execute(
                "SELECT COUNT(DISTINCT ts_code) FROM portfolio_pool_trades WHERE side='sell'"
            ).fetchone()
            n_closed_val = int(n_closed[0]) if n_closed else 0
            total_pnl = current_cash - initial_cash
            cum_return = total_pnl / initial_cash if initial_cash > 0 else 0.0
            conn.execute(
                """UPDATE portfolio_pool_summary SET market_value=0, total_assets=?, total_cost=0,
                       today_pnl=0, today_pct=0, unrealized_pnl=0, unrealized_pct=0,
                       realized_pnl=?, total_pnl=?, cum_return=?, n_closed=?,
                       updated_at=? WHERE id=1""",
                (
                    current_cash,
                    realized_total,
                    total_pnl,
                    cum_return,
                    n_closed_val,
                    _now(),
                ),
            )
        return

    codes = [h["ts_code"] for h in holdings_rows]

    name_map: dict[str, dict[str, str]] = {}
    try:
        from research.data.storage.duckdb_query import get_stock_basic
        basic = get_stock_basic()
        if not basic.empty:
            sub = basic[basic["ts_code"].isin(codes)]
            for _, br in sub.iterrows():
                name_map[str(br["ts_code"])] = {
                    "name": str(br.get("name") or ""),
                    "industry": str(br.get("industry") or ""),
                }
    except Exception:
        pass

    bar_map: dict[str, dict[str, float]] = {}
    try:
        from research.data.storage.duckdb_query import get_price
        from datetime import timedelta as _td

        end = date or datetime.now().strftime("%Y%m%d")
        start = (datetime.strptime(end, "%Y%m%d") - _td(days=15)).strftime("%Y%m%d")
        df = get_price(ts_codes=codes, start=start, end=end,
                       cols=("ts_code", "trade_date", "close", "pre_close"))
        if not df.empty:
            df = df.sort_values(["ts_code", "trade_date"])
            last = df.groupby("ts_code").tail(1)
            for _, br in last.iterrows():
                close_val = float(br["close"]) if br["close"] is not None else 0.0
                pre_close = float(br["pre_close"]) if br["pre_close"] not in (None, 0) else 0.0
                bar_map[str(br["ts_code"])] = {
                    "close": close_val,
                    "pre_close": pre_close,
                    "trade_date": _norm_trade_date(br.get("trade_date")),
                }
    except Exception:
        pass

    now = _now()
    total_market_value = 0.0
    total_today_pnl = 0.0
    total_unrealized_pnl = 0.0
    total_cost = 0.0

    with open_db() as conn:
        today_buys: dict[str, dict[str, float]] = {}
        bar_dates = sorted({str(v.get("trade_date") or "") for v in bar_map.values() if v.get("trade_date")})
        valuation_date = bar_dates[-1] if bar_dates else _norm_trade_date(date)
        if valuation_date:
            rows = conn.execute(
                """SELECT ts_code, COALESCE(SUM(shares),0), COALESCE(SUM(amount),0)
                   FROM portfolio_pool_trades
                   WHERE side='buy' AND REPLACE(trade_date, '-', '') = ?
                   GROUP BY ts_code""",
                (valuation_date,),
            ).fetchall()
            for r in rows:
                shares_val = float(r[1] or 0)
                amount_val = float(r[2] or 0)
                today_buys[str(r[0])] = {"shares": shares_val, "amount": amount_val}

        conn.execute("BEGIN")
        try:
            for h in holdings_rows:
                ts = h["ts_code"]
                shares = int(h["shares"])
                avg_cost = float(h["avg_cost"])
                bar = bar_map.get(ts, {})
                last_price = float(bar.get("close") or h.get("last_price") or avg_cost)
                pre_close = float(bar.get("pre_close") or last_price)
                market_value = last_price * shares
                pnl = (last_price - avg_cost) * shares
                pnl_pct = (last_price / avg_cost - 1) * 100 if avg_cost > 0 else 0.0
                buy_info = today_buys.get(ts, {})
                today_buy_shares = min(float(shares), float(buy_info.get("shares") or 0.0))
                today_buy_avg = (
                    float(buy_info.get("amount") or 0.0) / today_buy_shares
                    if today_buy_shares > 0 else avg_cost
                )
                overnight_shares = max(0.0, float(shares) - today_buy_shares)
                today_pnl = 0.0
                if pre_close > 0 and overnight_shares > 0:
                    today_pnl += (last_price - pre_close) * overnight_shares
                if today_buy_shares > 0:
                    today_pnl += (last_price - today_buy_avg) * today_buy_shares

                meta = name_map.get(ts, {})
                conn.execute(
                    """UPDATE portfolio_pool_holdings SET name=?, industry=?, last_price=?, market_value=?,
                       pnl=?, pnl_pct=?, updated_at=? WHERE ts_code=?""",
                    (
                        meta.get("name", h.get("name", "")),
                        meta.get("industry", h.get("industry", "")),
                        last_price,
                        market_value,
                        pnl,
                        pnl_pct,
                        now,
                        ts,
                    ),
                )
                total_market_value += market_value
                total_today_pnl += today_pnl
                total_unrealized_pnl += pnl
                total_cost += avg_cost * shares

            row = conn.execute(
                "SELECT current_cash, initial_cash FROM portfolio_pool_summary WHERE id=1"
            ).fetchone()
            current_cash = float(row[0] or INITIAL_CASH) if row else INITIAL_CASH
            initial_cash = float(row[1] or INITIAL_CASH) if row else INITIAL_CASH

            total_assets = current_cash + total_market_value
            if total_assets > 0:
                conn.execute(
                    """UPDATE portfolio_pool_holdings SET weight = market_value / ? WHERE shares > 0""",
                    (total_assets,),
                )

            realized = conn.execute(
                "SELECT COALESCE(SUM(pnl),0) FROM portfolio_pool_trades WHERE side='sell'"
            ).fetchone()
            realized_total = float(realized[0]) if realized else 0.0

            n_closed = conn.execute(
                "SELECT COUNT(DISTINCT ts_code) FROM portfolio_pool_trades WHERE side='sell'"
            ).fetchone()
            n_closed_val = int(n_closed[0]) if n_closed else 0

            unrealized_pct = (total_unrealized_pnl / total_cost) if total_cost > 0 else 0.0
            yesterday_value = total_market_value - total_today_pnl
            today_pct = (total_today_pnl / yesterday_value) if yesterday_value > 0 else 0.0
            total_pnl = realized_total + total_unrealized_pnl
            cum_return = total_pnl / initial_cash if initial_cash > 0 else 0.0

            conn.execute(
                """UPDATE portfolio_pool_summary SET market_value=?, total_assets=?, total_cost=?,
                   today_pnl=?, today_pct=?, unrealized_pnl=?, unrealized_pct=?,
                   realized_pnl=?, total_pnl=?, cum_return=?, n_closed=?,
                   updated_at=? WHERE id=1""",
                (
                    total_market_value,
                    total_assets,
                    total_cost,
                    total_today_pnl,
                    today_pct,
                    total_unrealized_pnl,
                    unrealized_pct,
                    realized_total,
                    total_pnl,
                    cum_return,
                    n_closed_val,
                    now,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def current_holdings_for_signal() -> list[dict[str, Any]]:
    """给信号生成模块用：返回 [{ts_code, weight}]，weight 基于 total_assets。"""
    summary = list_summary()
    total_assets = float(summary.get("total_assets") or 0.0)
    holdings = list_holdings()
    if total_assets <= 0 or not holdings:
        return [{"ts_code": h["ts_code"], "weight": 0.0, "shares": h["shares"], "avg_cost": h["avg_cost"]} for h in holdings]
    return [
        {
            "ts_code": h["ts_code"],
            "weight": float(h.get("market_value") or 0.0) / total_assets,
            "shares": h["shares"],
            "avg_cost": h["avg_cost"],
        }
        for h in holdings
    ]
