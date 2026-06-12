"""时光机：用与实盘完全相同的"信号 → 调仓 → 成交 → 快照"链路逐日推进。

这是一体化回测：
  - 与「今日信号」用 **同一个** signal.generate（仅传不同 target_date）
  - 与「仓池」用 **同一个** confirm_trades / snapshot
  - 与「账户净值」共享相同的 snapshots 数据结构

输入：start_date, end_date, initial_cash
输出：
  - portfolio_tm_snapshots / portfolio_tm_trades / portfolio_tm_positions
  - 函数返回 summary / snapshots / trades，桌面端统一从配置数据库读取

用法：
    from trading.execution.time_machine import run_time_machine
    result = run_time_machine("20240101", "20241231")
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from common.config import BACKTEST_DIR, RAW_DIR
from common.config.desktop_settings import load_exit_rules
from common.infra.db import insert_ignore_sql, upsert_sql, write_transaction
from research.data.storage import duckdb_query as dq
from trading.execution import position_pool as pp
from trading.execution import signal as sig_mod
from trading.execution import exit_rules as exr
from trading.strategy import combiner as _combiner, registry as _registry
from common.utils import get_logger

log = get_logger("time_machine")

TM_DIR = BACKTEST_DIR.parent / "positions" / "timemachine"
TM_DIR.mkdir(parents=True, exist_ok=True)

def _json_dumps(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=float)


def _task_status(status: str, cancelled: bool = False) -> str:
    if status == "cancelled":
        return "cancelled"
    if status == "interrupted" and cancelled:
        return "cancelled"
    return {
        "pending": "queued",
        "running": "running",
        "done": "success",
        "failed": "failed",
        "cancelled": "cancelled",
        "interrupted": "interrupted",
    }.get(status, status)


def _progress_pct(fields: dict) -> float:
    progress = fields.get("progress") or {}
    pct = float(progress.get("pct") or 0)
    if pct > 1:
        pct = pct / 100.0
    if fields.get("status") == "done":
        return 1.0
    return max(0.0, min(1.0, pct))


def _sync_task_to_db(run_id: str, fields: dict) -> None:
    status = fields.get("status")
    if not status:
        return
    now = datetime.now().isoformat()
    summary = {k: fields.get(k) for k in (
        "elapsed_sec", "total_return", "annual_return", "max_drawdown",
        "sharpe", "win_rate", "n_trades", "final_equity", "strategies", "mode",
        "progress",
    ) if k in fields}
    if fields.get("summary"):
        summary.update(fields["summary"])
    try:
        with write_transaction(None) as conn:
            row = conn.execute(
                "SELECT id, summary_json FROM task_jobs WHERE external_run_id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return
            existing_summary = {}
            if row[1]:
                try:
                    existing_summary = json.loads(row[1])
                except Exception:
                    existing_summary = {}
            existing_summary.update({k: v for k, v in summary.items() if v is not None})
            finished_at = now if status in {"done", "failed", "cancelled", "interrupted"} else None
            conn.execute(
                """UPDATE task_jobs
                   SET status = ?, progress = ?, summary_json = ?, error_message = ?,
                       finished_at = COALESCE(?, finished_at), updated_at = ?
                   WHERE external_run_id = ?""",
                (
                    _task_status(status, bool(fields.get("cancelled"))),
                    _progress_pct(fields),
                    _json_dumps(existing_summary),
                    str(fields.get("error") or ""),
                    finished_at,
                    now,
                    run_id,
                ),
            )
    except Exception as e:  # pragma: no cover
        log.warning(f"同步评估任务到数据库失败 {run_id}：{e}")


def _persist_snapshot_db(run_id: str, row: dict) -> None:
    now = datetime.now().isoformat()
    try:
        with write_transaction(None) as conn:
            columns = [
                "run_id", "trade_date", "cash", "market_value", "equity", "n_holdings",
                "unrealized_pnl", "realized_pnl", "cum_return", "created_at", "updated_at",
            ]
            conn.execute(
                upsert_sql(
                    "portfolio_tm_snapshots",
                    columns,
                    ["run_id", "trade_date"],
                    [
                        "cash", "market_value", "equity", "n_holdings",
                        "unrealized_pnl", "realized_pnl", "cum_return", "updated_at",
                    ],
                ),
                (
                    run_id,
                    str(row.get("date") or ""),
                    float(row.get("cash") or 0),
                    float(row.get("market_value") or 0),
                    float(row.get("equity") or 0),
                    int(row.get("n_holdings") or 0),
                    float(row.get("unrealized_pnl") or 0),
                    float(row.get("realized_pnl") or 0),
                    float(row.get("cum_return") or 0),
                    now,
                    now,
                ),
            )
    except Exception as e:  # pragma: no cover
        log.warning(f"写入时光机快照到数据库失败 {run_id}：{e}")


def _persist_trades_db(run_id: str, date: str, trades: list[dict]) -> None:
    if not trades:
        return
    now = datetime.now().isoformat()
    try:
        with write_transaction(None) as conn:
            rows = []
            for t in trades:
                rows.append((
                    run_id,
                    str(date),
                    str(t.get("ts_code") or ""),
                    str(t.get("name") or ""),
                    str(t.get("action") or ""),
                    int(t.get("shares") or 0),
                    float(t.get("price") or 0),
                    float(t.get("amount") or (float(t.get("shares") or 0) * float(t.get("price") or 0))),
                    int(t.get("hold_days") or 0),
                    float(t.get("realized_pnl") or 0),
                    str(t.get("exit_reason") or ""),
                    str(t.get("exec_date") or ""),
                    1 if t.get("is_new") else 0,
                    now,
                ))
            conn.executemany(
                insert_ignore_sql(
                    "portfolio_tm_trades",
                    [
                        "run_id", "trade_date", "ts_code", "name", "action", "shares", "price", "amount",
                        "hold_days", "realized_pnl", "exit_reason", "exec_date", "is_new", "created_at",
                    ],
                ),
                rows,
            )
    except Exception as e:  # pragma: no cover
        log.warning(f"写入时光机成交流水到数据库失败 {run_id}：{e}")


def _persist_positions_db(run_id: str, date: str, positions: list[dict]) -> None:
    now = datetime.now().isoformat()
    try:
        with write_transaction(None) as conn:
            conn.execute(
                "DELETE FROM portfolio_tm_positions WHERE run_id = ? AND trade_date = ?",
                (run_id, str(date)),
            )
            rows = []
            for p in positions:
                rows.append((
                    run_id,
                    str(date),
                    str(p.get("ts_code") or ""),
                    str(p.get("name") or ""),
                    int(p.get("shares") or 0),
                    float(p.get("avg_cost") or 0),
                    float(p.get("price") or 0),
                    float(p.get("market_value") or 0),
                    float(p.get("unrealized_pnl") or 0),
                    float(p.get("unrealized_pct") or 0),
                    float(p.get("today_pnl") or 0),
                    float(p.get("today_pct") or 0),
                    float(p.get("weight") or 0),
                    int(p.get("hold_days") or 0),
                    now,
                    now,
                ))
            conn.executemany(
                """INSERT INTO portfolio_tm_positions (
                       run_id, trade_date, ts_code, name, shares, avg_cost, price,
                       market_value, unrealized_pnl, unrealized_pct, today_pnl,
                       today_pct, weight, hold_days, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
    except Exception as e:  # pragma: no cover
        log.warning(f"写入时光机持仓快照到数据库失败 {run_id}：{e}")


def _collect_strategy_meta(strategies_filter: list[str] | None) -> list[dict]:
    """收集本次回测实际使用的策略明细：名字 / 中文标签 / 权重。

    与 combiner.load_all 的选择口径一致：配置数据库中 enabled=true 且已注册的策略；
    若给定 strategies_filter 则进一步过滤。
    """
    from trading.strategy.base import StrategyConfig
    registered = set(_registry.all_names())
    flt = set(strategies_filter) if strategies_filter else None
    out: list[dict] = []
    for name in _registry.all_names():
        if name not in registered:
            continue
        try:
            cfg = StrategyConfig.from_yaml(name)
        except Exception:
            continue
        # 显式勾选的策略即便配置数据库中 enabled=false 也算参与本次评估
        forced = flt is not None and name in flt
        if not forced and not cfg.enabled:
            continue
        if flt is not None and name not in flt:
            continue
        out.append({
            "name": name,
            "label": _registry.get_label(name),
            "weight": float(cfg.weight),
        })
    return out


# ──────────────────────────────────── 评估状态机 ────────────────────────────────────
# 每个评估在 <run_id>/status.json 维护一份状态，供异步后台进程实时汇报、UI 轮询。
#
#   status: pending | running | done | failed | interrupted
#   heartbeat: 最后一次心跳的 epoch 秒（后台进程每个调仓日刷新）
#   进程被强杀来不及写 failed 时，靠 heartbeat 超时由 reconcile_statuses() 兜底改 interrupted。

# 心跳超时阈值（秒）：running 但超过该时长无心跳 → 判定异常中断
HEARTBEAT_TIMEOUT_SEC = 90


def _status_path(run_id: str) -> Path:
    return TM_DIR / run_id / "status.json"


def write_status(run_id: str, **fields) -> None:
    """合并写入 <run_id>/status.json（失败不影响主流程）。"""
    import time as _t
    p = _status_path(run_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        cur: dict = {}
        if p.exists():
            try:
                cur = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                cur = {}
        cur.update(fields)
        cur["run_id"] = run_id
        cur["updated_at"] = _t.time()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, default=float), encoding="utf-8")
        tmp.replace(p)  # 原子替换，避免读到半截
        _sync_task_to_db(run_id, cur)
    except Exception as e:  # pragma: no cover
        log.warning(f"写入评估状态失败 {run_id}：{e}")


def read_status(run_id: str) -> dict | None:
    """读取某评估状态；不存在返回 None。"""
    p = _status_path(run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_eval_status() -> list[dict]:
    """列出所有评估状态（最新优先）。先做一次心跳兜底校正。"""
    reconcile_statuses()
    out: list[dict] = []
    if not TM_DIR.exists():
        return out
    for d in sorted(TM_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        s = read_status(d.name)
        if s:
            out.append(s)
    return out


def reconcile_statuses() -> int:
    """启动时/进入列表页扫描：把心跳超时的 running 评估改判为 interrupted。

    返回被改判的数量。这是"线程异常结束→状态异常中断"一致性的兜底机制：
    进程被强杀无法执行 except 时，靠心跳超时在此处统一收口。
    """
    import time as _t
    if not TM_DIR.exists():
        return 0
    now = _t.time()
    changed = 0
    for d in sorted(TM_DIR.iterdir()):
        if not d.is_dir():
            continue
        s = read_status(d.name)
        if not s:
            continue
        if s.get("status") in ("running", "pending"):
            hb = float(s.get("heartbeat", s.get("updated_at", 0)) or 0)
            if now - hb > HEARTBEAT_TIMEOUT_SEC:
                write_status(
                    d.name,
                    status="interrupted",
                    error="心跳超时：后台评估进程已结束或被终止（异常中断）",
                    interrupted_at=now,
                )
                changed += 1
    return changed


# ──────────────────────────────────── 行情批量取价 ────────────────────────────────────

def _close_at(codes: list[str], date: str) -> dict[str, float]:
    """取 codes 在 date 当日的 close。无数据则忽略该 code。"""
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, close
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date = '{date}' AND ts_code IN ({in_clause})
    """)
    if df.empty:
        return {}
    return {r["ts_code"]: float(r["close"])
            for _, r in df.iterrows() if pd.notna(r["close"]) and float(r["close"]) > 0}


def _high_at(codes: list[str], date: str) -> dict[str, float]:
    """取 codes 在 date 当日的 high（最高价）。用于跟踪持有期峰值。"""
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, high
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date = '{date}' AND ts_code IN ({in_clause})
    """)
    if df.empty:
        return {}
    return {r["ts_code"]: float(r["high"])
            for _, r in df.iterrows() if pd.notna(r["high"]) and float(r["high"]) > 0}


def _open_at(codes: list[str], date: str) -> dict[str, float]:
    """取 codes 在 date 当日的 open（开盘价）。用于"次日开盘卖出"撮合。"""
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, open
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date = '{date}' AND ts_code IN ({in_clause})
    """)
    if df.empty:
        return {}
    return {r["ts_code"]: float(r["open"])
            for _, r in df.iterrows() if pd.notna(r["open"]) and float(r["open"]) > 0}


def _next_trade_day(cal: list[str], cur_idx: int) -> str | None:
    """返回交易日历中 cur_idx 之后的下一个交易日；末尾则 None。"""
    if cur_idx + 1 < len(cal):
        return cal[cur_idx + 1]
    return None


def _is_last_feb_trade_day(cal: list[str], cur_idx: int) -> bool:
    """当前是不是该年 2 月的最后一个交易日（即下一个交易日跨入 3 月或更晚）。"""
    d = cal[cur_idx]
    if d[4:6] != "02":
        return False
    nxt = _next_trade_day(cal, cur_idx)
    if nxt is None:
        # 区间末尾刚好停在 2 月 → 也按最后一个 2 月交易日处理
        return True
    # 下一个交易日跨年 (March 永远 > 02)，或同年但月份 != 02
    return nxt[:4] != d[:4] or nxt[4:6] != "02"


def _is_march(date: str) -> bool:
    return date[4:6] == "03"


def _prev_close_at(codes: list[str], date: str) -> dict[str, float]:
    """取 codes 在 date 当日的 pre_close。"""
    if not codes:
        return {}
    in_clause = ",".join(f"'{c}'" for c in codes)
    df = dq.sql(f"""
        SELECT ts_code, pre_close
        FROM read_parquet('{RAW_DIR / "daily" / "*.parquet"}')
        WHERE trade_date = '{date}' AND ts_code IN ({in_clause})
    """)
    if df.empty:
        return {}
    return {r["ts_code"]: float(r["pre_close"])
            for _, r in df.iterrows() if pd.notna(r["pre_close"]) and float(r["pre_close"]) > 0}


# ──────────────────────────────────── 隔离仓池 ────────────────────────────────────

class _IsolatedPool:
    """独立的内存仓池上下文，避免污染 _store/datapositions/pool.json。

    通过临时把 pp.POOL_PATH 指向 run_dir/pool.json 实现隔离。
    """

    def __init__(self, run_dir: Path, initial_cash: float):
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.initial_cash = initial_cash
        self._orig_pool_path = pp.POOL_PATH
        self._orig_snap_path = pp.SNAPSHOT_PATH

    def __enter__(self):
        pp.POOL_PATH = self.run_dir / "pool.json"
        pp.SNAPSHOT_PATH = self.run_dir / "snapshots.parquet"
        # 初始化空仓池（带本金）
        if pp.POOL_PATH.exists():
            pp.POOL_PATH.unlink()
        if pp.SNAPSHOT_PATH.exists():
            pp.SNAPSHOT_PATH.unlink()
        pool = pp.empty_pool()
        pool["initial_cash"] = self.initial_cash
        pool["current_cash"] = self.initial_cash
        pp.save_pool(pool)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pp.POOL_PATH = self._orig_pool_path
        pp.SNAPSHOT_PATH = self._orig_snap_path


# ──────────────────────────────────── 主流程 ────────────────────────────────────

def run_time_machine(
    start_date: str,
    end_date: str,
    *,
    initial_cash: float = 500_000.0,
    run_id: str | None = None,
    rebalance_freq: int = 5,
    exit_rules_cfg: dict | None = None,
    strategies_filter: list[str] | None = None,
    eval_name: str | None = None,
    progress_cb=None,
) -> dict:
    """逐日跑信号→调仓→成交→快照。

    Args:
        start_date, end_date: YYYYMMDD
        initial_cash: 起始本金
        run_id: 输出目录名；缺省用时间戳
        rebalance_freq: 调仓频率（每隔 N 个交易日）。1=每天调仓（最慢，最贴合实盘）；
            5=每周调仓（推荐，10× 加速）；20=每月调仓（50× 加速）。
            非调仓日仅按当日 close 落快照（不重新生成信号）。
        progress_cb: fn(i, total, date, stage, eta_sec, live_state)
            stage in {"signal","trade","snapshot","day_done","done"}
            eta_sec: 预计剩余秒数
            live_state: {date, equity, cash, cum_return, n_holdings,
                         n_trades_total, today_trades, snapshots}
                        UI 可据此实时绘制净值曲线/KPI

    Returns:
        {
          "run_id", "run_dir",
          "snapshots": DataFrame[date, cash, market_value, equity, ...],
          "trades":    DataFrame[date, ts_code, action, shares, price, amount, realized_pnl?],
          "summary": {
            "start", "end", "n_days", "n_rebalance",
            "initial_cash", "final_equity",
            "total_pnl", "total_return", "annual_return",
            "max_drawdown", "sharpe", "win_rate",
            "n_trades", "realized_pnl", "unrealized_pnl",
          }
        }
    """
    import time as _time
    if run_id is None:
        tag = ""
        if strategies_filter and len(strategies_filter) == 1:
            tag = f"_{strategies_filter[0]}"
        elif strategies_filter:
            tag = f"_multi{len(strategies_filter)}"
        run_id = f"tm{tag}_{start_date}_{end_date}_{datetime.now().strftime('%H%M%S')}"
    run_dir = TM_DIR / run_id

    cal = dq.get_trade_dates(start_date, end_date)
    if not cal:
        raise RuntimeError(f"区间 [{start_date}, {end_date}] 无交易日")
    if exit_rules_cfg is None:
        exit_rules_cfg = load_exit_rules()

    # 调仓日索引集（i % freq == 0 + 最后一天兜底）
    rebalance_set = set(range(0, len(cal), max(1, rebalance_freq)))
    rebalance_set.add(len(cal) - 1)
    n_rebalance = len(rebalance_set)

    log.info(f"时光机启动：{start_date} → {end_date}（{len(cal)} 个交易日，{n_rebalance} 次调仓），run_id={run_id}")

    # —— 评估状态机：标记本次评估为「评估中」（running）——
    import os as _os
    import time as _t0
    write_status(
        run_id,
        status="running",
        eval_name=(eval_name or "").strip(),
        start=start_date,
        end=end_date,
        n_days=len(cal),
        n_rebalance=n_rebalance,
        initial_cash=float(initial_cash),
        rebalance_freq=rebalance_freq,
        strategies_filter=list(strategies_filter) if strategies_filter else None,
        exit_rules=exit_rules_cfg or {},
        pid=_os.getpid(),
        created_at=_t0.time(),
        heartbeat=_t0.time(),
        progress={"cur_day": 0, "total_days": len(cal), "pct": 0.0, "stage": "init", "eta_sec": 0},
    )

    trades_log: list[dict] = []
    snapshots_buf: list[dict] = []  # 累计快照（边跑边给 UI）
    last_prices: dict[str, float] = {}  # 最近一次 close 价（持仓 + 候选）
    last_prev_closes: dict[str, float] = {}  # 当日前收盘价
    t0 = _time.time()
    rebalance_done = 0

    def _live_state(d: str, today_trades: list[dict] | None = None) -> dict:
        """构造一份当前快照供 UI 实时展示。

        positions 字段里每只股票都补齐：name/shares/avg_cost/price/market_value/
        unrealized_pnl/unrealized_pct/today_pnl/today_pct/weight/holder_account
        ——和「仓池」页 10 列完全对齐。
        """
        pool_now = pp.load_pool()
        try:
            pnl_view = pp.compute_pnl(pool_now, last_prices, last_prev_closes,
                                      as_of_date=d)
            positions = pnl_view["positions"]
            equity = pnl_view["equity"]
            cash = pnl_view["cash"]
        except Exception:
            # 兜底（比如刚开始还没拿到价）
            positions = []
            equity = (snapshots_buf[-1]["equity"]
                      if snapshots_buf else pool_now["current_cash"])
            cash = pool_now["current_cash"]

        cum_ret = (equity - pool_now["initial_cash"]) / pool_now["initial_cash"] \
                  if pool_now["initial_cash"] > 0 else 0.0

        # 账户表所需字段
        market_value = sum(float(p.get("market_value", 0)) for p in positions)
        unrealized_pnl = sum(float(p.get("unrealized_pnl", 0)) for p in positions)
        # 已实现盈亏 = 总盈亏 - 浮动盈亏
        total_pnl = equity - pool_now["initial_cash"]
        realized_pnl = total_pnl - unrealized_pnl
        # 仓位率
        position_pct = (market_value / equity) if equity > 0 else 0.0

        return {
            "date": d,
            "equity": equity,
            "cash": cash,
            "initial_cash": pool_now["initial_cash"],
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "total_pnl": total_pnl,
            "position_pct": position_pct,
            "cum_return": cum_ret,
            "n_holdings": len(pool_now["positions"]),
            "n_trades_total": len(trades_log),
            "today_trades": today_trades or [],
            "positions": positions,
            "snapshots": list(snapshots_buf),
        }

    def _emit(i: int, stage: str, today_trades: list[dict] | None = None):
        elapsed = _time.time() - t0
        if rebalance_done > 0:
            avg = elapsed / rebalance_done
            eta = max(0, (n_rebalance - rebalance_done) * avg)
        else:
            eta = 0
        cur_d = cal[i] if i < len(cal) else cal[-1]
        # 心跳 + 进度落档（无论是否有 progress_cb，后台进程都靠它实时汇报状态）
        write_status(
            run_id,
            heartbeat=_time.time(),
            progress={
                "cur_day": i + 1,
                "total_days": len(cal),
                "pct": round((i + 1) / max(1, len(cal)) * 100, 1),
                "stage": stage,
                "eta_sec": int(eta),
                "date": cur_d,
            },
        )
        if not progress_cb:
            if stage == "day_done" and today_trades:
                _persist_trades_db(run_id, cur_d, today_trades)
            return
        live = _live_state(cur_d, today_trades)
        if stage == "day_done" and today_trades:
            _persist_trades_db(run_id, cur_d, today_trades)
        progress_cb(i, len(cal), cur_d, stage, eta, live)

    def _record_snap(pool_obj: dict, d: str, prices: dict[str, float]):
        """落快照 + 同步到内存 buffer（供 UI）+ 缓存当日 prev_close。"""
        # 当日成交价就是当日 close，所以 prev_close 用日表里的 pre_close
        codes_for_pc = [p["ts_code"] for p in pool_obj["positions"]]
        last_prices.update(prices)
        last_prev_closes.update(_prev_close_at(codes_for_pc, d))

        pp.snapshot(pool_obj, d, prices)
        market_value = sum(p["shares"] * prices.get(p["ts_code"], p["avg_cost"])
                           for p in pool_obj["positions"])
        equity = pool_obj["current_cash"] + market_value
        unrealized_pnl = sum(
            (prices.get(p["ts_code"], p["avg_cost"]) - p["avg_cost"]) * p["shares"]
            for p in pool_obj["positions"]
        )
        total_pnl = equity - pool_obj["initial_cash"]
        snap_row = {
            "date": d,
            "cash": pool_obj["current_cash"],
            "market_value": market_value,
            "equity": equity,
            "n_holdings": len(pool_obj["positions"]),
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": total_pnl - unrealized_pnl,
            "cum_return": total_pnl / pool_obj["initial_cash"] if pool_obj["initial_cash"] > 0 else 0.0,
        }
        snapshots_buf.append(snap_row)
        _persist_snapshot_db(run_id, snap_row)
        try:
            pnl_view = pp.compute_pnl(pool_obj, last_prices, last_prev_closes, as_of_date=d)
            _persist_positions_db(run_id, d, pnl_view.get("positions") or [])
        except Exception:
            rows = []
            for p in pool_obj["positions"]:
                price = prices.get(p["ts_code"], p["avg_cost"])
                market = p["shares"] * price
                rows.append({
                    "ts_code": p["ts_code"],
                    "name": p.get("name") or "",
                    "shares": p["shares"],
                    "avg_cost": p["avg_cost"],
                    "price": price,
                    "market_value": market,
                    "unrealized_pnl": (price - p["avg_cost"]) * p["shares"],
                    "unrealized_pct": (price / p["avg_cost"] - 1) if p.get("avg_cost") else 0,
                    "today_pnl": 0,
                    "today_pct": 0,
                    "weight": market / equity if equity > 0 else 0,
                    "hold_days": 0,
                })
            _persist_positions_db(run_id, d, rows)

    def _enrich_trades(trades_to_enrich: list[dict], pool_after: dict,
                       prev_pool_map: dict | None, d: str) -> list[dict]:
        """给 today_trades 补字段：time / is_new / hold_days / realized_pnl / exit_reason。

        Args:
            trades_to_enrich: 待增强的成交单（会原地修改）
            pool_after: confirm_trades 之后的仓池
            prev_pool_map: confirm_trades 之前的 ts_code→position 映射；None 表示
                没有"之前快照"（如非调仓日的纯强卖场景）—— 此时 BUY 一律视为非新入
            d: 当前日期 YYYYMMDD
        """
        from datetime import datetime as _dt
        d_dt = _dt.strptime(d, "%Y%m%d")
        closed_map = {c["ts_code"]: c for c in pool_after.get("closed_positions", [])}
        pool_map_after = {p["ts_code"]: p for p in pool_after["positions"]}
        for t in trades_to_enrich:
            code = t["ts_code"]
            act = t["action"]
            t["time"] = "15:00"  # 回测按当日收盘撮合
            if act in ("BUY", "ADD"):
                prev = prev_pool_map.get(code) if prev_pool_map else None
                t["is_new"] = prev is None
                if prev is not None:
                    try:
                        hold_d = (d_dt - _dt.strptime(prev["first_entry_date"], "%Y%m%d")).days
                    except Exception:
                        hold_d = 0
                    t["hold_days"] = hold_d
                else:
                    t["hold_days"] = 0
                t["realized_pnl"] = 0.0
            elif act in ("SELL", "TRIM"):
                t["is_new"] = False
                if code in closed_map and code not in pool_map_after:
                    cc = closed_map[code]
                    t["hold_days"] = cc.get("hold_days", 0)
                    sell_records = [tr for tr in cc.get("trades", [])
                                    if tr.get("date") == d and tr.get("action") in ("SELL", "TRIM")]
                    t["realized_pnl"] = sum(tr.get("realized_pnl", 0) for tr in sell_records)
                    # 从 closed_position 同步 exit_reason（如果 trade 自己没带）
                    if not t.get("exit_reason") and cc.get("exit_reason"):
                        t["exit_reason"] = cc["exit_reason"]
                elif code in pool_map_after:
                    p = pool_map_after[code]
                    try:
                        hold_d = (d_dt - _dt.strptime(p["first_entry_date"], "%Y%m%d")).days
                    except Exception:
                        hold_d = 0
                    t["hold_days"] = hold_d
                    sell_records = [tr for tr in p.get("trades", [])
                                    if tr.get("date") == d and tr.get("action") in ("SELL", "TRIM")]
                    t["realized_pnl"] = sum(tr.get("realized_pnl", 0) for tr in sell_records)
                else:
                    t["hold_days"] = 0
                    t["realized_pnl"] = 0.0
        return trades_to_enrich

    with _IsolatedPool(run_dir, initial_cash):
        for i, d in enumerate(cal):
            is_rebalance_day = i in rebalance_set

            # ===== 日历规则层：2 月最后一个交易日强制清仓 =====
            # 不受 exit_rules.enabled 开关控制；优先级最高
            forced_today: list[dict] = []
            slippage_cal = float(exit_rules_cfg.get("slippage", 0.003)) if exit_rules_cfg else 0.003
            if _is_last_feb_trade_day(cal, i):
                pool = pp.load_pool()
                if pool["positions"]:
                    held_codes_f = [p["ts_code"] for p in pool["positions"]]
                    closes_f = _close_at(held_codes_f, d)
                    last_prices.update(closes_f)
                    feb_clear: list[dict] = []
                    for p in pool["positions"]:
                        code = p["ts_code"]
                        cur = closes_f.get(code) or p.get("avg_cost") or 0.0
                        if cur <= 0 or p["shares"] <= 0:
                            continue
                        feb_clear.append({
                            "ts_code": code,
                            "name": p.get("name") or "",
                            "action": "SELL",
                            "shares": int(p["shares"]),
                            "price": cur * (1 - slippage_cal),
                            "exit_reason": "feb_clear",
                            "exit_pct": 1.0,
                            "exec_date": d,
                        })
                    if feb_clear:
                        pool = pp.confirm_trades(pool, feb_clear, d)
                        for ft in feb_clear:
                            trades_log.append({
                                "date": d,
                                "ts_code": ft["ts_code"],
                                "action": "SELL",
                                "shares": ft["shares"],
                                "price": ft["price"],
                                "amount": ft["shares"] * ft["price"],
                                "exit_reason": "feb_clear",
                                "exec_date": d,
                            })
                        forced_today = feb_clear

            # ===== 每日硬性卖出层（止损 / 移动止盈）=====
            # 不论是否调仓日，先扫一遍持仓，触发风控就立刻强卖
            if exit_rules_cfg and exit_rules_cfg.get("enabled"):
                pool = pp.load_pool()
                if pool["positions"]:
                    held_codes_e = [p["ts_code"] for p in pool["positions"]]
                    closes_e = _close_at(held_codes_e, d)
                    highs_e = _high_at(held_codes_e, d)
                    last_prices.update(closes_e)
                    # 1) 用当日最高价抬 peak_price（捕捉日内插针的高点）
                    #    回退顺序：high → close（无 high 数据时降级）
                    peaks_input = {**closes_e, **highs_e}  # high 优先
                    exr.update_peak_prices(pool, peaks_input)
                    pp.save_pool(pool)
                    # 2) 用当日 close 作触发判定（避免日内噪音误触发）
                    forced_raw = exr.scan(pool, closes_e, d, exit_rules_cfg)
                    if forced_raw:
                        # 3) 根据 exit_reason 决定撮合价
                        slippage = float(exit_rules_cfg.get("slippage", 0.003))
                        trailing_exec = exit_rules_cfg.get("trailing_exec", "next_open")
                        next_d = _next_trade_day(cal, i)
                        # 批量取次日开盘
                        next_opens: dict[str, float] = {}
                        if trailing_exec == "next_open" and next_d:
                            tcodes = [r["ts_code"] for r in forced_raw
                                      if r.get("exit_reason") == "trailing_stop"]
                            if tcodes:
                                next_opens = _open_at(tcodes, next_d)

                        for ft in forced_raw:
                            code = ft["ts_code"]
                            reason = ft.get("exit_reason")
                            if reason == "stop_loss":
                                # 止损：当日 close × (1 - 滑点)，盘中市价卖
                                base = closes_e.get(code) or ft.get("price")
                                ft["price"] = base * (1 - slippage)
                                ft["exec_date"] = d
                            elif reason == "trailing_stop":
                                # 止盈：次日开盘 × (1 - 滑点)；拿不到次日数据降级当日 close
                                if trailing_exec == "next_open" and code in next_opens:
                                    ft["price"] = next_opens[code] * (1 - slippage)
                                    ft["exec_date"] = next_d
                                else:
                                    base = closes_e.get(code) or ft.get("price")
                                    ft["price"] = base * (1 - slippage)
                                    ft["exec_date"] = d
                            else:
                                ft["exec_date"] = d
                        forced_today = forced_raw
                        pool = pp.confirm_trades(pool, forced_today, d)
                        # 写入 trades_log
                        for ft in forced_today:
                            trades_log.append({
                                "date": d,
                                "ts_code": ft["ts_code"],
                                "action": "SELL",
                                "shares": ft["shares"],
                                "price": ft["price"],
                                "amount": ft["shares"] * ft["price"],
                                "exit_reason": ft.get("exit_reason"),
                                "exec_date": ft.get("exec_date", d),
                            })

            if not is_rebalance_day:
                # 非调仓日：只按当日 close 给现有持仓落快照
                pool = pp.load_pool()
                if pool["positions"]:
                    snap_prices = _close_at([p["ts_code"] for p in pool["positions"]], d)
                    _record_snap(pool, d, snap_prices)
                else:
                    _record_snap(pool, d, {})
                # 如果今日有强卖，把 forced_today 当成 today_trades 推给 UI
                if forced_today:
                    _enriched = _enrich_trades(forced_today, pool, None, d)
                    _emit(i, "day_done", _enriched)
                else:
                    _emit(i, "snapshot")
                continue

            _emit(i, "signal")

            # 1. 生成 d 日信号（回测：不写实盘 db；prev = 回测账户当前权重）
            pool_now = pp.load_pool()
            equity = pool_now["current_cash"]
            close_now = _close_at([p["ts_code"] for p in pool_now["positions"]], d) if pool_now["positions"] else {}
            for p in pool_now["positions"]:
                px = close_now.get(p["ts_code"], p["avg_cost"])
                equity += p["shares"] * px
            prev_w_map: dict[str, float] = {}
            if equity > 0:
                for p in pool_now["positions"]:
                    px = close_now.get(p["ts_code"], p["avg_cost"])
                    prev_w_map[p["ts_code"]] = (p["shares"] * px) / equity

            try:
                s = sig_mod.generate(
                    target_date=d,
                    strategies_filter=strategies_filter,
                    persist=False,
                    prev_weights=prev_w_map,
                )
            except Exception as e:
                log.warning(f"[{d}] 信号生成失败：{e}")
                rebalance_done += 1
                continue
            if not s.get("holdings"):
                pool = pp.load_pool()
                _record_snap(pool, d,
                             _close_at([p["ts_code"] for p in pool["positions"]], d))
                _emit(i, "snapshot")
                rebalance_done += 1
                continue

            # 2. 取 d 日成交价
            pool = pp.load_pool()
            held_codes = [p["ts_code"] for p in pool["positions"]]
            target_codes = [h["ts_code"] for h in s["holdings"]]
            all_codes = sorted(set(held_codes + target_codes))
            prices_d = _close_at(all_codes, d)

            # 3. 调仓单
            rb = pp.compute_rebalance(pool, s, prices_d)
            active = [r for r in rb if r["action"] != "HOLD"]

            # 3.5 日历规则：3 月不买入（SELL/TRIM 仍允许执行）
            if _is_march(d):
                active = [r for r in active if r["action"] != "BUY"]

            # 4. 撮合（含滑点）
            slippage_rb = float(exit_rules_cfg.get("slippage", 0.003)) if exit_rules_cfg else 0.003
            trades_today = []
            for r in active:
                shares = abs(r["delta_shares"])
                if shares <= 0:
                    continue
                if r["price"] <= 0:
                    log.warning(f"[{d}] {r['ts_code']} 无有效价格，跳过")
                    continue
                act = r["action"]
                if act == "BUY":
                    fill_price = r["price"] * (1 + slippage_rb)
                elif act in ("SELL", "TRIM"):
                    fill_price = r["price"] * (1 - slippage_rb)
                else:
                    fill_price = r["price"]
                trades_today.append({
                    "ts_code": r["ts_code"],
                    "name": r.get("name") or "",
                    "action": act,
                    "shares": shares,
                    "price": fill_price,
                    "sources": r.get("sources", []),
                })

            _emit(i, "trade", trades_today)

            if trades_today:
                # 撮合前快照仓池：用于判断 BUY 是否新入、SELL 算持仓天数
                prev_pool_map = {p["ts_code"]: p for p in pool["positions"]}

                pool = pp.confirm_trades(pool, trades_today, d)
                for t in trades_today:
                    trades_log.append({
                        "date": d, **{k: t[k] for k in ("ts_code", "action", "shares", "price")},
                        "amount": t["shares"] * t["price"],
                    })

                _enrich_trades(trades_today, pool, prev_pool_map, d)

            # 5. 落快照
            held_after = [p["ts_code"] for p in pool["positions"]]
            snap_prices = _close_at(held_after, d)
            _record_snap(pool, d, snap_prices)
            rebalance_done += 1

            # 合并今天可能在前面"硬性卖出层"先卖掉的 forced_today
            if forced_today:
                # forced_today 已经被 confirm_trades 过，需要单独 enrich（prev_pool_map=None）
                _enrich_trades(forced_today, pool, None, d)
                merged_trades = forced_today + (trades_today or [])
            else:
                merged_trades = trades_today

            # 调仓日完成 → 推一次完整 live_state（含当日成交）
            _emit(i, "day_done", merged_trades)

        if progress_cb:
            progress_cb(len(cal) - 1, len(cal), cal[-1], "done", 0,
                        _live_state(cal[-1]))

        snaps = pp.load_snapshots()
        final_pool = pp.load_pool()

    # 流水落盘
    trades_df = pd.DataFrame(trades_log)
    if not trades_df.empty:
        trades_df.to_parquet(run_dir / "trades.parquet", compression="zstd", index=False)

    # 汇总指标
    summary = _summarize(snaps, initial_cash, final_pool, start_date, end_date, len(trades_df))
    summary["n_rebalance"] = n_rebalance
    summary["rebalance_freq"] = rebalance_freq
    summary["elapsed_sec"] = round(_time.time() - t0, 1)
    summary["strategies_filter"] = list(strategies_filter) if strategies_filter else None
    summary["mode"] = "single" if (strategies_filter and len(strategies_filter) == 1) else "combo"
    # 记录本次评估实际使用的策略明细（名字 + 中文标签 + 权重）
    strat_meta = _collect_strategy_meta(strategies_filter)
    summary["strategies"] = strat_meta
    summary["strategy_names"] = [s["name"] for s in strat_meta]
    summary["strategy_labels"] = [s["label"] for s in strat_meta]
    # 退出规则快照（如有传入）
    summary["exit_rules"] = exit_rules_cfg or {}
    # 评估名字（用户自定义，便于在列表页识别）
    summary["eval_name"] = (eval_name or "").strip()

    log.info(f"时光机完成：{run_id} → 总收益 {summary['total_return']*100:+.2f}% · 用时 {summary['elapsed_sec']}s")

    # —— 评估状态机：标记完成（done）+ 关键收益指标，供列表页直接展示 ——
    write_status(
        run_id,
        status="done",
        heartbeat=_time.time(),
        finished_at=_time.time(),
        elapsed_sec=summary.get("elapsed_sec"),
        total_return=summary.get("total_return"),
        annual_return=summary.get("annual_return"),
        max_drawdown=summary.get("max_drawdown"),
        sharpe=summary.get("sharpe"),
        win_rate=summary.get("win_rate"),
        n_trades=summary.get("n_trades"),
        final_equity=summary.get("final_equity"),
        strategies=strat_meta,
        mode=summary["mode"],
        progress={"cur_day": len(cal), "total_days": len(cal), "pct": 100.0, "stage": "done", "eta_sec": 0},
    )

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "snapshots": snaps,
        "trades": trades_df,
        "summary": summary,
    }


# ──────────────────────────────────── 指标 ────────────────────────────────────

def _summarize(snaps: pd.DataFrame, initial_cash: float, final_pool: dict,
               start: str, end: str, n_trades: int) -> dict:
    if snaps.empty:
        return {
            "start": start, "end": end, "n_days": 0,
            "initial_cash": initial_cash, "final_equity": initial_cash,
            "total_pnl": 0.0, "total_return": 0.0, "annual_return": 0.0,
            "max_drawdown": 0.0, "sharpe": 0.0, "win_rate": 0.0,
            "n_trades": n_trades,
            "realized_pnl": 0.0, "unrealized_pnl": 0.0,
        }
    snaps = snaps.sort_values("date").reset_index(drop=True)
    eq = snaps["equity"].astype(float)
    total_return = float(eq.iloc[-1] / initial_cash - 1)
    n_days = len(snaps)
    # 年化（按 252 交易日）
    if n_days > 1:
        annual_return = float((1 + total_return) ** (252 / n_days) - 1)
    else:
        annual_return = 0.0

    # 日收益
    rets = eq.pct_change().dropna()
    if len(rets) > 1 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * (252 ** 0.5))
    else:
        sharpe = 0.0

    # 最大回撤
    running_max = eq.cummax()
    dd = (eq / running_max - 1)
    max_dd = float(dd.min()) if len(dd) else 0.0

    # 胜率（按交易日）
    win_rate = float((rets > 0).sum() / len(rets)) if len(rets) else 0.0

    realized = float(sum(c["realized_pnl"] for c in final_pool.get("closed_positions", [])))
    unrealized = float(eq.iloc[-1] - initial_cash - realized)

    return {
        "start": start, "end": end, "n_days": n_days,
        "initial_cash": float(initial_cash),
        "final_equity": float(eq.iloc[-1]),
        "total_pnl": float(eq.iloc[-1] - initial_cash),
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "n_trades": int(n_trades),
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
    }


# ──────────────────────────────────── 列出历史 ────────────────────────────────────

def list_runs() -> list[dict]:
    """历史结果不再扫描 summary.json；桌面端从配置数据库查询。"""
    return []


def list_ledger() -> list[dict]:
    """历史台账不再写 index.jsonl；桌面端从配置数据库查询。"""
    return []


def load_run(run_id: str) -> dict | None:
    """不再从结果目录加载 summary.json；桌面端从配置数据库查询。"""
    return None
