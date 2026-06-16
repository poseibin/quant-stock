from __future__ import annotations

import pandas as pd

from trading.strategy.base import StrategyConfig
from trading.strategy.ml_factor_ranker import _apply_smallcap_ecology_controls, _weights_from_predictions


def test_equal_weighting_does_not_tilt_by_score() -> None:
    preds = pd.DataFrame(
        [
            {"ts_code": "600001.SH", "pred_score": 100.0, "industry": "A"},
            {"ts_code": "600002.SH", "pred_score": 10.0, "industry": "B"},
            {"ts_code": "600003.SH", "pred_score": 1.0, "industry": "C"},
        ]
    )
    cfg = StrategyConfig(
        name="ml_factor_ranker",
        position={
            "n_holdings": 3,
            "max_single_weight": 1.0,
            "max_industry_weight": 1.0,
            "weighting": "equal",
        },
    )

    weights = _weights_from_predictions(preds, "20260612", cfg)

    assert list(weights.index) == ["20260612"]
    assert set(weights.columns) == {"600001.SH", "600002.SH", "600003.SH"}
    assert weights.loc["20260612"].round(10).tolist() == [round(1 / 3, 10)] * 3


def test_equal_weighting_respects_single_stock_cap() -> None:
    preds = pd.DataFrame(
        [
            {"ts_code": "600001.SH", "pred_score": 100.0, "industry": "A"},
            {"ts_code": "600002.SH", "pred_score": 10.0, "industry": "B"},
        ]
    )
    cfg = StrategyConfig(
        name="ml_factor_ranker",
        position={
            "n_holdings": 2,
            "max_single_weight": 0.4,
            "max_industry_weight": 1.0,
            "weighting": "equal",
        },
    )

    weights = _weights_from_predictions(preds, "20260612", cfg)

    assert weights.loc["20260612"].max() <= 0.4
    assert weights.loc["20260612"].sum() == 0.8


def test_secondary_sort_can_break_close_prediction_ties() -> None:
    preds = pd.DataFrame(
        [
            {"ts_code": "600001.SH", "pred_score": 1.000, "industry": "A", "amount": 20_000_000, "vol20": 0.60},
            {"ts_code": "600002.SH", "pred_score": 1.000, "industry": "B", "amount": 90_000_000, "vol20": 0.20},
            {"ts_code": "600003.SH", "pred_score": 1.000, "industry": "C", "amount": 80_000_000, "vol20": 0.25},
        ]
    )
    cfg = StrategyConfig(
        name="ml_factor_ranker",
        position={
            "n_holdings": 2,
            "max_single_weight": 1.0,
            "max_industry_weight": 1.0,
            "weighting": "equal",
            "secondary_sort_strength": 0.20,
            "secondary_sort": [
                {"column": "amount", "ascending": False, "weight": 1.0},
                {"column": "vol20", "ascending": True, "weight": 1.0},
            ],
        },
    )

    weights = _weights_from_predictions(preds, "20260612", cfg)

    assert set(weights.columns) == {"600002.SH", "600003.SH"}
    assert weights.loc["20260612"].round(10).tolist() == [0.5, 0.5]


def test_smallcap_ecology_controls_drop_crowded_candidates() -> None:
    preds = pd.DataFrame(
        [
            {"trade_date": "20260612", "ts_code": "600001.SH", "pred_score": 1.00, "ret20": 0.35, "vol20": 0.80, "amount_chg20": 3.0, "turnover_rate": 20.0, "market_risk_score": 20.0, "market_limit_down_ratio5": 0.02, "market_small_large_rel20": -0.08, "market_state": "weak"},
            {"trade_date": "20260612", "ts_code": "600002.SH", "pred_score": 0.90, "ret20": 0.05, "vol20": 0.20, "amount_chg20": 0.2, "turnover_rate": 5.0, "market_risk_score": 20.0, "market_limit_down_ratio5": 0.02, "market_small_large_rel20": -0.08, "market_state": "weak"},
        ]
    )
    cfg = StrategyConfig(
        name="ml_factor_ranker",
        filters={
            "smallcap_ecology": {
                "enabled": True,
                "states": ["weak"],
                "min_pressure": 0.10,
                "drop_crowding_rank": 0.90,
            }
        },
    )

    out = _apply_smallcap_ecology_controls(preds, cfg)

    assert out["ts_code"].tolist() == ["600002.SH"]


def test_smallcap_ecology_controls_penalize_score() -> None:
    preds = pd.DataFrame(
        [
            {"trade_date": "20260612", "ts_code": "600001.SH", "pred_score": 1.00, "ret20": 0.30, "vol20": 0.50, "amount_chg20": 2.0, "turnover_rate": 12.0, "market_risk_score": 30.0, "market_limit_down_ratio5": 0.01, "market_small_large_rel20": -0.05, "market_state": "normal"},
        ]
    )
    cfg = StrategyConfig(
        name="ml_factor_ranker",
        filters={
            "smallcap_ecology": {
                "enabled": True,
                "crowding_penalty": 0.10,
                "pressure_penalty": 0.05,
                "rank_penalty": 0.01,
            }
        },
    )

    out = _apply_smallcap_ecology_controls(preds, cfg)

    assert out.loc[0, "pred_score"] < preds.loc[0, "pred_score"]
    assert "smallcap_ecology_adjusted_score" in out.columns
