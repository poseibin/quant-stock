from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from common.infra import db
from scripts.limit_breakout_worker import BreakoutBar, Candidate, write_cache as write_breakout_cache
from scripts.limit_up_momentum_worker import MomentumCandidate, write_cache as write_momentum_cache


def _mysql_available() -> bool:
    try:
        with db.open_db() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mysql_available(), reason="local MySQL quant_stock database is not available")


@pytest.fixture()
def cache_key() -> str:
    return f"pytest:{uuid4().hex}"


def _cleanup(cache_key: str) -> None:
    with db.write_transaction() as conn:
        for table in ("market_limit_breakout_cache", "market_limit_breakout_cache_meta"):
            if db.table_exists(conn, table):
                conn.execute(f"DELETE FROM {table} WHERE cache_key = ?", (cache_key,))
        for table in ("market_limit_momentum_cache", "market_limit_momentum_cache_meta"):
            if db.table_exists(conn, table):
                conn.execute(f"DELETE FROM {table} WHERE cache_key = ?", (cache_key,))
        if db.table_exists(conn, "market_limit_signal_predictions"):
            conn.execute("DELETE FROM market_limit_signal_predictions WHERE parameter_key = ?", (cache_key,))


def _bar(date: str = "20260611") -> BreakoutBar:
    return BreakoutBar(
        trade_date=date,
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        pct_chg=2.0,
    )


def test_limit_breakout_worker_writes_rank_no_cache(cache_key: str) -> None:
    _cleanup(cache_key)
    candidate = Candidate(
        ts_code="600001.SH",
        name="测试横盘",
        industry="测试",
        latest_date="20260611",
        close=10.2,
        score=81.5,
        flat_score=0.8,
        breakout_score=0.7,
        quality_score=0.6,
        base_low=9.5,
        base_high=10.5,
        base_ratio=0.1,
        base_return=0.02,
        recent_return=0.05,
        limit_up_count=1,
        volume_surge=1.8,
        roe=12.0,
        net_margin=8.0,
        debt_to_assets=45.0,
        reasons=["pytest"],
        bars=[_bar()],
        projected_bars=[],
    )

    try:
        write_breakout_cache(Path("."), cache_key, [candidate])
        with db.open_db() as conn:
            cols = db.table_columns(conn, "market_limit_breakout_cache")
            row = conn.execute(
                "SELECT rank_no, ts_code, latest_date, score FROM market_limit_breakout_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            pred = conn.execute(
                "SELECT COUNT(*) FROM market_limit_signal_predictions WHERE parameter_key = ? AND signal_type = 'limit_breakout'",
                (cache_key,),
            ).fetchone()

        assert "rank_no" in cols
        assert "rank" not in cols
        assert row == (1, "600001.SH", "20260611", 81.5)
        assert int(pred[0]) == 1
    finally:
        _cleanup(cache_key)


def test_limit_up_worker_writes_rank_no_cache(cache_key: str) -> None:
    _cleanup(cache_key)
    candidate = MomentumCandidate(
        ts_code="600002.SH",
        name="测试涨停",
        industry="测试",
        trade_date="20260611",
        close=12.3,
        stage="watch",
        recommendation="可试仓",
        score=76.0,
        chain_potential=72.0,
        end_risk=20.0,
        liquidity_risk=15.0,
        fund_confirmation=68.0,
        limit_up_count=2,
        consecutive_boards=1,
        next_day_return=0.01,
        return_3d=0.03,
        return_5d=0.05,
        return_10d=0.08,
        max_drawdown_5d=-0.04,
        recent_20_return=0.16,
        recent_60_return=0.22,
        turnover_rate=4.2,
        volume_ratio=1.6,
        amount=120000.0,
        total_mv=500000.0,
        circ_mv=300000.0,
        dragon_tiger_net_buy=0.0,
        institution_net_buy=0.0,
        reasons=["pytest"],
        risks=[],
        bars=[_bar()],
        projected_bars=[],
    )

    try:
        write_momentum_cache(None, cache_key, [candidate])
        with db.open_db() as conn:
            cols = db.table_columns(conn, "market_limit_momentum_cache")
            row = conn.execute(
                "SELECT rank_no, ts_code, trade_date, score FROM market_limit_momentum_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            pred = conn.execute(
                "SELECT COUNT(*) FROM market_limit_signal_predictions WHERE parameter_key = ? AND signal_type = 'limit_up_momentum'",
                (cache_key,),
            ).fetchone()

        assert "rank_no" in cols
        assert "rank" not in cols
        assert row == (1, "600002.SH", "20260611", 76.0)
        assert int(pred[0]) == 1
    finally:
        _cleanup(cache_key)
