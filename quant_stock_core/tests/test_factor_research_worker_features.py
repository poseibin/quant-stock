from __future__ import annotations

import numpy as np
import pandas as pd

from scripts import factor_research_worker as worker


SMALLCAP_ECOLOGY_FACTORS = {
    "smallcap_rel_strength5",
    "smallcap_rel_strength20",
    "smallcap_attack_score",
    "smallcap_repair_score",
    "smallcap_style_resilience",
    "smallcap_crowding_heat",
    "smallcap_liquidity_quality",
    "smallcap_breakout_exhaustion",
}


def test_smallcap_ecology_factors_are_model_candidates() -> None:
    assert SMALLCAP_ECOLOGY_FACTORS <= set(worker.FACTOR_DEFS)
    assert SMALLCAP_ECOLOGY_FACTORS <= set(worker.MODEL_FACTOR_ORDER)
    assert worker.MODEL_FAMILY_MIN_QUOTAS["小盘生态"] >= 1


def test_smallcap_ecology_features_are_selected_without_ic_results() -> None:
    dates = ["20240131"] * 80 + ["20240229"] * 80
    row_count = len(dates)
    rng = np.random.default_rng(20260613)
    cols = {"trade_date": dates}
    for idx, factor in enumerate(worker.FACTOR_DEFS):
        base = rng.permutation(np.linspace(0.01, 0.99, row_count))
        cols[f"{factor}_rank"] = np.roll(base, idx % 17)
        cols[f"{factor}_neutral"] = np.roll(1.0 - base, idx % 19)
    panel = pd.DataFrame(cols)

    selected = worker.selected_model_features(panel, run_id="", horizon="net_fwd20_rank_label")

    assert any(feature.startswith("smallcap_attack_score_") for feature in selected)
