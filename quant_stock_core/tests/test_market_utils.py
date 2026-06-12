from __future__ import annotations

import pandas as pd

from common.utils.market import (
    exclude_restricted_stocks,
    price_limit_rate,
    price_limit_threshold_pct,
    restricted_exclude_sql,
    restricted_stock_mask,
)


def test_restricted_stock_mask_blocks_untradable_boards() -> None:
    data = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "exchange": "SSE", "market": "主板"},
            {"ts_code": "000001.SZ", "exchange": "SZSE", "market": "主板"},
            {"ts_code": "300750.SZ", "exchange": "SZSE", "market": "创业板"},
            {"ts_code": "688981.SH", "exchange": "SSE", "market": "科创板"},
            {"ts_code": "833000.BJ", "exchange": "BJ", "market": "北交所"},
        ]
    )

    assert restricted_stock_mask(data).tolist() == [False, False, True, True, True]
    assert exclude_restricted_stocks(data)["ts_code"].tolist() == ["600000.SH", "000001.SZ"]


def test_price_limit_helpers_match_board_rules() -> None:
    assert price_limit_rate("600000.SH", "") == 0.10
    assert price_limit_rate("000001.SZ", "") == 0.10
    assert price_limit_rate("300750.SZ", "") == 0.20
    assert price_limit_rate("688981.SH", "") == 0.20
    assert price_limit_rate("833000.BJ", "", "BJ", "北交所") == 0.30
    assert price_limit_rate("600001.SH", "*ST测试") == 0.05
    assert price_limit_threshold_pct("600000.SH") == 9.2


def test_restricted_exclude_sql_mentions_all_untradable_boards() -> None:
    sql = restricted_exclude_sql("s")

    assert "s.exchange" in sql
    assert "北交" in sql
    assert "科创" in sql
    assert "创业" in sql
    assert "688%" in sql
    assert "300%" in sql
    assert "301%" in sql
