"""Analyze state-backed shareholders from top10_holders parquet data.

This script reads DATA_ROOT/raw/top10_holders and aggregates stocks whose top
10 shareholders match "国家队" style holders such as Central Huijin, CSF, social
security funds, and SAFE investment platforms.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.config.settings import DATA_ROOT
from common.infra.db import desktop_db_path, write_transaction
from common.infra import status as run_status

TASK = "state_team_analysis"

STATE_TEAM_KEYWORDS = (
    "中央汇金",
    "中国证券金融",
    "证金公司",
    "全国社保基金",
    "社保基金",
    "国家集成电路产业投资基金",
    "国新投资",
    "中国国有企业结构调整基金",
    "外汇局",
    "梧桐树投资平台",
    "北京凤山投资",
    "北京坤藤投资",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("holdings", "changes"), default="holdings")
    parser.add_argument("--data-root", default=str(DATA_ROOT), help="data_store path")
    parser.add_argument("--period", default="", help="report period, e.g. 20250331; default latest")
    parser.add_argument("--previous-period", default="", help="previous report period for changes mode")
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--min-ratio-change", type=float, default=0.1, help="minimum hold_ratio delta for ADD/TRIM")
    parser.add_argument("--keyword", action="append", default=[], help="extra holder keyword")
    parser.add_argument("--csv", default="", help="optional output csv path")
    parser.add_argument("--db-path", default="", help="SQLite path; default DATA_ROOT/meta.db")
    parser.add_argument("--no-save-db", action="store_true", help="do not persist analysis result to SQLite")
    parser.add_argument("--json", action="store_true", help="print JSON instead of table")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.db_path:
        os.environ["DESKTOP_DB_PATH"] = str(Path(args.db_path).expanduser().resolve())
    try:
        run_status.begin(TASK)
        data_root = Path(args.data_root).expanduser().resolve()
        extra_keywords = tuple(str(k).strip() for k in args.keyword if str(k).strip())
        run_status.progress(TASK, 1, 6, "prepare", "检查数据目录")
        if args.mode == "changes":
            rows = analyze_state_team_changes(
                data_root=data_root,
                current_period=str(args.period or "").strip(),
                previous_period=str(args.previous_period or "").strip(),
                limit=args.top,
                min_ratio_change=float(args.min_ratio_change),
                extra_keywords=extra_keywords,
            )
        else:
            rows = analyze_state_team_holders(
                data_root=data_root,
                period=str(args.period or "").strip(),
                limit=args.top,
                extra_keywords=extra_keywords,
            )
        if args.csv:
            run_status.progress(TASK, 5, 6, "export", "导出 CSV")
            out = Path(args.csv).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_csv(out, index=False)
        if not args.no_save_db:
            run_status.progress(TASK, 5, 6, "sqlite", "写入 SQLite")
            db_path = Path(args.db_path).expanduser().resolve() if args.db_path else desktop_db_path()
            if args.mode == "changes":
                save_state_team_changes(db_path, rows)
            else:
                save_state_team_holdings(db_path, rows)
        run_status.progress(TASK, 6, 6, "done", "分析完成")
        run_status.done(TASK, f"国家队分析完成，结果 {len(rows)} 条")
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        else:
            if args.mode == "changes":
                print_changes_table(rows)
            else:
                print_table(rows)
        return 0
    except Exception as exc:
        run_status.error(TASK, str(exc))
        raise


def analyze_state_team_holders(
    *,
    data_root: Path,
    period: str = "",
    limit: int = 100,
    extra_keywords: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    holders_glob = data_root / "raw" / "top10_holders" / "*.parquet"
    if not list(holders_glob.parent.glob("*.parquet")):
        raise RuntimeError("缺少 top10_holders 数据，请先运行: python scripts/data_update_worker.py --dataset top10_holders ...")

    keywords = STATE_TEAM_KEYWORDS + extra_keywords
    keyword_sql = " OR ".join("holder_name LIKE ?" for _ in keywords)
    params: list[Any] = [f"%{k}%" for k in keywords]

    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL parquet; LOAD parquet;")
    run_status.progress(TASK, 2, 6, "load", "读取前十大股东数据")
    period_filter = ""
    if period:
        period_filter = "AND end_date = ?"
        params.append(period)
    else:
        latest = con.execute(
            "SELECT max(end_date) FROM read_parquet(?)",
            [str(holders_glob)],
        ).fetchone()[0]
        if not latest:
            return []
        period_filter = "AND end_date = ?"
        params.append(str(latest))

    stock_basic_path = data_root / "raw" / "stock_basic" / "data.parquet"
    has_stock_basic = stock_basic_path.exists()
    join_sql = ""
    select_stock_cols = "'' AS name, '' AS industry"
    if has_stock_basic:
        join_sql = """
            LEFT JOIN read_parquet(?) s
              ON h.ts_code = s.ts_code
        """
        select_stock_cols = "coalesce(max(s.name), '') AS name, coalesce(max(s.industry), '') AS industry"
        params.append(str(stock_basic_path))

    params.append(max(1, min(int(limit or 100), 1000)))
    sql = f"""
        WITH matched AS (
            SELECT *
            FROM read_parquet(?) h
            WHERE ({keyword_sql})
              {period_filter}
        )
        SELECT
            h.ts_code,
            max(h.end_date) AS end_date,
            max(h.ann_date) AS ann_date,
            {select_stock_cols},
            count(distinct h.holder_name) AS holder_count,
            sum(coalesce(h.hold_amount, 0)) AS hold_amount,
            sum(coalesce(h.hold_ratio, 0)) AS hold_ratio,
            sum(coalesce(h.hold_float_ratio, 0)) AS hold_float_ratio,
            string_agg(distinct h.holder_name, ' / ') AS holders
        FROM matched h
        {join_sql}
        GROUP BY h.ts_code
        ORDER BY hold_ratio DESC, hold_float_ratio DESC, holder_count DESC
        LIMIT ?
    """
    params.insert(0, str(holders_glob))
    df = con.execute(sql, params).fetchdf()
    run_status.progress(TASK, 4, 6, "aggregate", "生成持仓快照")
    return df.fillna("").to_dict("records")


def analyze_state_team_changes(
    *,
    data_root: Path,
    current_period: str = "",
    previous_period: str = "",
    limit: int = 100,
    min_ratio_change: float = 0.1,
    extra_keywords: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    holders_glob = data_root / "raw" / "top10_holders" / "*.parquet"
    if not list(holders_glob.parent.glob("*.parquet")):
        raise RuntimeError("缺少 top10_holders 数据，请先运行: python scripts/data_update_worker.py --dataset top10_holders ...")

    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL parquet; LOAD parquet;")
    run_status.progress(TASK, 2, 6, "load", "读取前十大股东数据")
    current_period, previous_period = resolve_period_pair(
        con,
        holders_glob,
        current_period=current_period,
        previous_period=previous_period,
    )

    keywords = STATE_TEAM_KEYWORDS + extra_keywords
    keyword_sql = " OR ".join("holder_name LIKE ?" for _ in keywords)
    run_status.progress(TASK, 3, 6, "match", "匹配国家队账户")

    stock_basic_path = data_root / "raw" / "stock_basic" / "data.parquet"
    has_stock_basic = stock_basic_path.exists()
    stock_cte = ""
    stock_join = ""
    stock_cols = "'' AS name, '' AS industry"
    params: list[Any] = [str(holders_glob), *[f"%{k}%" for k in keywords], current_period, previous_period]
    if has_stock_basic:
        stock_cte = ", stock AS (SELECT ts_code, max(name) AS name, max(industry) AS industry FROM read_parquet(?) GROUP BY ts_code)"
        stock_join = "LEFT JOIN stock s ON coalesce(c.ts_code, p.ts_code) = s.ts_code"
        stock_cols = "coalesce(max(s.name), '') AS name, coalesce(max(s.industry), '') AS industry"
        params.append(str(stock_basic_path))
    params.extend([float(min_ratio_change), float(min_ratio_change), max(1, min(int(limit or 100), 1000))])

    sql = f"""
        WITH raw AS (
            SELECT *
            FROM read_parquet(?)
            WHERE ({keyword_sql})
              AND end_date IN (?, ?)
        ),
        agg AS (
            SELECT
                ts_code,
                end_date,
                count(distinct holder_name) AS holder_count,
                sum(coalesce(hold_amount, 0)) AS hold_amount,
                sum(coalesce(hold_ratio, 0)) AS hold_ratio,
                sum(coalesce(hold_float_ratio, 0)) AS hold_float_ratio,
                string_agg(distinct holder_name, ' / ') AS holders
            FROM raw
            GROUP BY ts_code, end_date
        ),
        cur AS (SELECT * FROM agg WHERE end_date = '{current_period}'),
        prev AS (SELECT * FROM agg WHERE end_date = '{previous_period}')
        {stock_cte}
        SELECT
            coalesce(c.ts_code, p.ts_code) AS ts_code,
            '{current_period}' AS current_period,
            '{previous_period}' AS previous_period,
            {stock_cols},
            CASE
                WHEN p.ts_code IS NULL THEN 'NEW'
                WHEN c.ts_code IS NULL THEN 'EXIT'
                WHEN coalesce(c.hold_ratio, 0) - coalesce(p.hold_ratio, 0) >= ? THEN 'ADD'
                WHEN coalesce(p.hold_ratio, 0) - coalesce(c.hold_ratio, 0) >= ? THEN 'TRIM'
                ELSE 'KEEP'
            END AS action,
            coalesce(c.holder_count, 0) AS current_holder_count,
            coalesce(p.holder_count, 0) AS previous_holder_count,
            coalesce(c.hold_amount, 0) AS current_hold_amount,
            coalesce(p.hold_amount, 0) AS previous_hold_amount,
            coalesce(c.hold_ratio, 0) AS current_hold_ratio,
            coalesce(p.hold_ratio, 0) AS previous_hold_ratio,
            coalesce(c.hold_ratio, 0) - coalesce(p.hold_ratio, 0) AS hold_ratio_delta,
            coalesce(c.hold_float_ratio, 0) AS current_float_ratio,
            coalesce(p.hold_float_ratio, 0) AS previous_float_ratio,
            coalesce(c.holders, '') AS current_holders,
            coalesce(p.holders, '') AS previous_holders,
            CASE
                WHEN p.ts_code IS NULL THEN '本期首次出现在国家队前十大股东匹配名单'
                WHEN c.ts_code IS NULL THEN '本期未出现在国家队前十大股东匹配名单；可能退出前十大，不等于确认清仓'
                WHEN coalesce(c.hold_ratio, 0) > coalesce(p.hold_ratio, 0) THEN '持股比例上升'
                WHEN coalesce(c.hold_ratio, 0) < coalesce(p.hold_ratio, 0) THEN '持股比例下降'
                ELSE '持股比例基本不变'
            END AS note
        FROM cur c
        FULL OUTER JOIN prev p ON c.ts_code = p.ts_code
        {stock_join}
        GROUP BY
            coalesce(c.ts_code, p.ts_code), c.ts_code, p.ts_code,
            c.holder_count, p.holder_count,
            c.hold_amount, p.hold_amount,
            c.hold_ratio, p.hold_ratio,
            c.hold_float_ratio, p.hold_float_ratio,
            c.holders, p.holders
        HAVING action <> 'KEEP'
        ORDER BY
            CASE action WHEN 'NEW' THEN 1 WHEN 'ADD' THEN 2 WHEN 'TRIM' THEN 3 WHEN 'EXIT' THEN 4 ELSE 5 END,
            abs(hold_ratio_delta) DESC,
            current_hold_ratio DESC
        LIMIT ?
    """
    df = con.execute(sql, params).fetchdf()
    run_status.progress(TASK, 4, 6, "compare", "比较两期持仓变化")
    return df.fillna("").to_dict("records")


def resolve_period_pair(
    con: duckdb.DuckDBPyConnection,
    holders_glob: Path,
    *,
    current_period: str,
    previous_period: str,
) -> tuple[str, str]:
    periods = [
        str(row[0])
        for row in con.execute(
            "SELECT DISTINCT end_date FROM read_parquet(?) WHERE end_date IS NOT NULL ORDER BY end_date DESC",
            [str(holders_glob)],
        ).fetchall()
        if row[0]
    ]
    if current_period:
        if current_period not in periods:
            raise RuntimeError(f"找不到报告期 {current_period}")
    elif periods:
        current_period = periods[0]
    if not current_period:
        raise RuntimeError("top10_holders 没有可用报告期")

    if previous_period:
        if previous_period not in periods:
            raise RuntimeError(f"找不到上一报告期 {previous_period}")
    else:
        older = [p for p in periods if p < current_period]
        if not older:
            raise RuntimeError(f"报告期 {current_period} 没有上一期可比较")
        previous_period = older[0]
    return current_period, previous_period


def save_state_team_holdings(db_path: Path, rows: list[dict[str, Any]]) -> None:
    with write_transaction(db_path) as conn:
        ensure_state_team_tables(conn)
        if not rows:
            return
        period = str(rows[0].get("end_date") or "")
        conn.execute("DELETE FROM state_team_holder_snapshots WHERE end_date = ?", (period,))
        conn.executemany(
            """
            INSERT INTO state_team_holder_snapshots(
                ts_code, name, industry, end_date, ann_date, holder_count,
                hold_amount, hold_ratio, hold_float_ratio, holders, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'))
            """,
            [
                (
                    str(row.get("ts_code") or ""),
                    str(row.get("name") or ""),
                    str(row.get("industry") or ""),
                    str(row.get("end_date") or ""),
                    str(row.get("ann_date") or ""),
                    int(row.get("holder_count") or 0),
                    float(row.get("hold_amount") or 0),
                    float(row.get("hold_ratio") or 0),
                    float(row.get("hold_float_ratio") or 0),
                    str(row.get("holders") or ""),
                )
                for row in rows
            ],
        )


def save_state_team_changes(db_path: Path, rows: list[dict[str, Any]]) -> None:
    with write_transaction(db_path) as conn:
        ensure_state_team_tables(conn)
        if not rows:
            return
        current_period = str(rows[0].get("current_period") or "")
        previous_period = str(rows[0].get("previous_period") or "")
        conn.execute(
            "DELETE FROM state_team_holder_changes WHERE current_period = ? AND previous_period = ?",
            (current_period, previous_period),
        )
        conn.executemany(
            """
            INSERT INTO state_team_holder_changes(
                ts_code, name, industry, action, current_period, previous_period,
                current_holder_count, previous_holder_count,
                current_hold_amount, previous_hold_amount,
                current_hold_ratio, previous_hold_ratio, hold_ratio_delta,
                current_float_ratio, previous_float_ratio,
                current_holders, previous_holders, note, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            """,
            [
                (
                    str(row.get("ts_code") or ""),
                    str(row.get("name") or ""),
                    str(row.get("industry") or ""),
                    str(row.get("action") or ""),
                    str(row.get("current_period") or ""),
                    str(row.get("previous_period") or ""),
                    int(row.get("current_holder_count") or 0),
                    int(row.get("previous_holder_count") or 0),
                    float(row.get("current_hold_amount") or 0),
                    float(row.get("previous_hold_amount") or 0),
                    float(row.get("current_hold_ratio") or 0),
                    float(row.get("previous_hold_ratio") or 0),
                    float(row.get("hold_ratio_delta") or 0),
                    float(row.get("current_float_ratio") or 0),
                    float(row.get("previous_float_ratio") or 0),
                    str(row.get("current_holders") or ""),
                    str(row.get("previous_holders") or ""),
                    str(row.get("note") or ""),
                )
                for row in rows
            ],
        )


def ensure_state_team_tables(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_team_holder_snapshots (
            ts_code TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            end_date TEXT NOT NULL,
            ann_date TEXT NOT NULL DEFAULT '',
            holder_count INTEGER NOT NULL DEFAULT 0,
            hold_amount REAL NOT NULL DEFAULT 0,
            hold_ratio REAL NOT NULL DEFAULT 0,
            hold_float_ratio REAL NOT NULL DEFAULT 0,
            holders TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(ts_code, end_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_team_holder_changes (
            ts_code TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            current_period TEXT NOT NULL,
            previous_period TEXT NOT NULL,
            current_holder_count INTEGER NOT NULL DEFAULT 0,
            previous_holder_count INTEGER NOT NULL DEFAULT 0,
            current_hold_amount REAL NOT NULL DEFAULT 0,
            previous_hold_amount REAL NOT NULL DEFAULT 0,
            current_hold_ratio REAL NOT NULL DEFAULT 0,
            previous_hold_ratio REAL NOT NULL DEFAULT 0,
            hold_ratio_delta REAL NOT NULL DEFAULT 0,
            current_float_ratio REAL NOT NULL DEFAULT 0,
            previous_float_ratio REAL NOT NULL DEFAULT 0,
            current_holders TEXT NOT NULL DEFAULT '',
            previous_holders TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(ts_code, current_period, previous_period)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_state_team_changes_period_action ON state_team_holder_changes(current_period, action)")


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("未找到国家队持仓记录")
        return
    columns = [
        ("ts_code", "代码", 12),
        ("name", "名称", 12),
        ("industry", "行业", 12),
        ("end_date", "报告期", 10),
        ("holder_count", "账户数", 6),
        ("hold_ratio", "总持股%", 10),
        ("hold_float_ratio", "流通%", 10),
        ("holders", "持有人", 48),
    ]
    print(" ".join(title.ljust(width) for _, title, width in columns))
    for row in rows:
        parts = []
        for key, _, width in columns:
            value = row.get(key, "")
            if isinstance(value, float):
                text = f"{value:.2f}"
            else:
                text = str(value)
            if len(text) > width:
                text = text[: max(0, width - 1)] + "…"
            parts.append(text.ljust(width))
        print(" ".join(parts))


def print_changes_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("未找到国家队持仓变化")
        return
    columns = [
        ("action", "动作", 6),
        ("ts_code", "代码", 12),
        ("name", "名称", 12),
        ("industry", "行业", 12),
        ("current_period", "本期", 10),
        ("previous_period", "上期", 10),
        ("current_hold_ratio", "本期%", 8),
        ("previous_hold_ratio", "上期%", 8),
        ("hold_ratio_delta", "变化", 8),
        ("note", "说明", 30),
    ]
    print(" ".join(title.ljust(width) for _, title, width in columns))
    for row in rows:
        parts = []
        for key, _, width in columns:
            value = row.get(key, "")
            if isinstance(value, float):
                text = f"{value:.2f}"
            else:
                text = str(value)
            if len(text) > width:
                text = text[: max(0, width - 1)] + "…"
            parts.append(text.ljust(width))
        print(" ".join(parts))


if __name__ == "__main__":
    raise SystemExit(main())
