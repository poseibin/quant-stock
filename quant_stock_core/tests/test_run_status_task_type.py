from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra import status


def test_offline_task_types_are_observable_separately() -> None:
    assert status._task_type("profit_arena_model") == "model_training"
    assert status._task_type("factor_snapshot") == "factor_snapshot"
    assert status._task_type("factor_autotune") == "historical_offline"


def test_data_and_rebalance_task_types_keep_existing_buckets() -> None:
    assert status._task_type("data_update") == "data_update"
    assert status._task_type("data_file_scan") == "data_update"
    assert status._task_type("daily_signal") == "historical_offline"
