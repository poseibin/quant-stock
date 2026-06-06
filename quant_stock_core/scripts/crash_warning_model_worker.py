"""Train a market-level crash warning classifier.

The model predicts whether the next 1-3 trading days will contain a crash or
liquidity shock using only market state features known at today's close.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.infra.db import replace_sql, write_transaction


FEATURES = [
    "risk_score", "market_return", "up_ratio", "down_ratio", "breadth20",
    "limit_up_ratio", "limit_down_ratio", "limit_down_ratio5",
    "amount_chg20", "small_large_rel20", "drawdown20", "drawdown60",
    "drawdown120", "trend60", "volatility20",
    "risk_score_chg3", "market_return3", "market_return5",
    "up_ratio_chg3", "breadth20_chg5", "limit_down_ratio_chg3",
    "amount_chg5", "volatility20_chg5",
    "state_weak", "state_crash", "state_liquidity_squeeze", "state_post_crash_repair",
]

SHOCK_STATES = {"crash", "liquidity_squeeze"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--min-train-years", type=int, default=4)
    parser.add_argument("--min-test-year", type=int, default=0)
    args = parser.parse_args()

    ensure_tables(args.db_path)
    data = build_dataset(args.db_path, args.start, args.end, args.horizon)
    if data.empty:
        raise RuntimeError("market_risk_state_daily has no usable rows")
    summary = train_walk_forward(args, data)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def ensure_tables(db_path: str | None) -> None:
    with write_transaction(db_path) as conn:
        if conn.backend == "mysql":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_crash_warning_runs (
                    run_id VARCHAR(255) PRIMARY KEY,
                    model_type VARCHAR(64) NOT NULL,
                    start_date VARCHAR(16) NOT NULL,
                    end_date VARCHAR(16) NOT NULL,
                    horizon BIGINT NOT NULL DEFAULT 3,
                    feature_count BIGINT NOT NULL DEFAULT 0,
                    status VARCHAR(32) NOT NULL,
                    summary_json LONGTEXT,
                    model_path VARCHAR(1024),
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_crash_warning_features (
                    run_id VARCHAR(255) NOT NULL,
                    feature VARCHAR(255) NOT NULL,
                    importance DOUBLE,
                    rank_no BIGINT NOT NULL DEFAULT 0,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, feature)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_crash_warning_predictions (
                    run_id VARCHAR(255) NOT NULL,
                    trade_date VARCHAR(16) NOT NULL,
                    shock_prob DOUBLE,
                    label BIGINT NOT NULL DEFAULT 0,
                    test_year BIGINT,
                    summary_json LONGTEXT,
                    created_at VARCHAR(64) NOT NULL,
                    updated_at VARCHAR(64) NOT NULL,
                    PRIMARY KEY(run_id, trade_date),
                    KEY idx_crash_warning_run_date (run_id, trade_date),
                    KEY idx_crash_warning_prob (run_id, shock_prob)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        else:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_crash_warning_runs (
                    run_id TEXT PRIMARY KEY,
                    model_type TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    horizon INTEGER NOT NULL DEFAULT 3,
                    feature_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    summary_json TEXT,
                    model_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_crash_warning_features (
                    run_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    importance REAL,
                    rank_no INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, feature)
                );
                CREATE TABLE IF NOT EXISTS market_crash_warning_predictions (
                    run_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    shock_prob REAL,
                    label INTEGER NOT NULL DEFAULT 0,
                    test_year INTEGER,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, trade_date)
                );
                """
            )


def build_dataset(db_path: str | None, start: str, end: str, horizon: int) -> pd.DataFrame:
    warmup_start = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=420)).strftime("%Y%m%d")
    with write_transaction(db_path) as conn:
        rows = conn.execute(
            """
            SELECT trade_date, state, COALESCE(risk_score, 0), COALESCE(market_return, 0),
                   COALESCE(up_ratio, 0), COALESCE(down_ratio, 0), COALESCE(breadth20, 0),
                   COALESCE(limit_up_ratio, 0), COALESCE(limit_down_ratio, 0),
                   COALESCE(limit_down_ratio5, 0), COALESCE(amount_chg20, 0),
                   COALESCE(small_large_rel20, 0), COALESCE(drawdown20, 0),
                   COALESCE(drawdown60, 0), COALESCE(drawdown120, 0),
                   COALESCE(trend60, 0), COALESCE(volatility20, 0)
            FROM market_risk_state_daily
            WHERE trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            (warmup_start, end),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    data = pd.DataFrame(
        rows,
        columns=[
            "trade_date", "state", "risk_score", "market_return", "up_ratio", "down_ratio", "breadth20",
            "limit_up_ratio", "limit_down_ratio", "limit_down_ratio5", "amount_chg20",
            "small_large_rel20", "drawdown20", "drawdown60", "drawdown120", "trend60", "volatility20",
        ],
    )
    data["trade_date"] = data["trade_date"].astype(str)
    data["state"] = data["state"].fillna("normal").astype(str)
    for col in data.columns:
        if col not in {"trade_date", "state"}:
            data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0.0)

    data = data.sort_values("trade_date").reset_index(drop=True)
    data["risk_score_chg3"] = data["risk_score"].diff(3)
    data["market_return3"] = data["market_return"].rolling(3, min_periods=1).sum()
    data["market_return5"] = data["market_return"].rolling(5, min_periods=1).sum()
    data["up_ratio_chg3"] = data["up_ratio"].diff(3)
    data["breadth20_chg5"] = data["breadth20"].diff(5)
    data["limit_down_ratio_chg3"] = data["limit_down_ratio"].diff(3)
    data["amount_chg5"] = data["amount_chg20"].diff(5)
    data["volatility20_chg5"] = data["volatility20"].diff(5)
    for state in ["weak", "crash", "liquidity_squeeze", "post_crash_repair"]:
        data[f"state_{state}"] = data["state"].eq(state).astype(int)

    future_flags = []
    for offset in range(1, horizon + 1):
        future_state = data["state"].shift(-offset).isin(SHOCK_STATES)
        future_hard_drop = data["market_return"].shift(-offset) <= -0.045
        future_limit_spread = data["limit_down_ratio"].shift(-offset) >= 0.025
        future_flags.append(future_state | future_hard_drop | future_limit_spread)
    label = future_flags[0]
    for flag in future_flags[1:]:
        label = label | flag
    data["label"] = label.astype(int)
    data["year"] = data["trade_date"].str.slice(0, 4).astype(int)
    data = data.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return data[data["trade_date"].between(start, end)].reset_index(drop=True)


def train_walk_forward(args: argparse.Namespace, data: pd.DataFrame) -> dict[str, Any]:
    lgb, import_error = import_lightgbm()
    if lgb is None:
        raise RuntimeError(import_error or "LightGBM package is not installed")

    min_year = max(int(data["year"].min()) + int(args.min_train_years), int(args.min_test_year or 0))
    test_years = [year for year in sorted(data["year"].unique()) if year >= min_year]
    if not test_years:
        raise RuntimeError("not enough years for walk-forward training")

    predictions: list[pd.DataFrame] = []
    fold_metrics: list[dict[str, Any]] = []
    feature_importance = pd.Series(0.0, index=FEATURES, dtype="float64")
    models: list[Any] = []
    x_all = data[FEATURES].astype(float)
    y_all = data["label"].astype(int)

    for year in test_years:
        train_mask = data["year"] < year
        test_mask = data["year"] == year
        if int(train_mask.sum()) < 500 or int(test_mask.sum()) == 0:
            continue
        y_train = y_all.loc[train_mask]
        pos = int(y_train.sum())
        neg = int(len(y_train) - pos)
        if pos <= 3:
            continue
        scale_pos_weight = max(1.0, neg / max(pos, 1))
        model = lgb.LGBMClassifier(
            objective="binary",
            n_estimators=220,
            learning_rate=0.035,
            num_leaves=15,
            max_depth=4,
            min_child_samples=20,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_alpha=0.05,
            reg_lambda=1.0,
            scale_pos_weight=scale_pos_weight,
            random_state=20260606,
            n_jobs=4,
            verbosity=-1,
        )
        model.fit(x_all.loc[train_mask], y_train)
        prob = model.predict_proba(x_all.loc[test_mask])[:, 1]
        fold = data.loc[test_mask, ["trade_date", "label", "year"]].copy()
        fold["shock_prob"] = prob.astype(float)
        predictions.append(fold)
        fold_metrics.append(_classification_metrics(fold["label"].to_numpy(), prob, int(year)))
        feature_importance += pd.Series(model.feature_importances_, index=FEATURES)
        models.append(model)

    if not predictions:
        raise RuntimeError("no walk-forward prediction was generated")

    pred = pd.concat(predictions, ignore_index=True).sort_values("trade_date")
    overall = _classification_metrics(pred["label"].to_numpy(), pred["shock_prob"].to_numpy(), 0)
    overall["folds"] = fold_metrics
    overall["positive_rate"] = float(pred["label"].mean())
    overall["prediction_rows"] = int(len(pred))
    overall["test_start"] = str(pred["trade_date"].min())
    overall["test_end"] = str(pred["trade_date"].max())

    out_dir = data_root() / "crash_warning_models" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.parquet"
    model_path = out_dir / "latest_model.joblib"
    pred.to_parquet(pred_path, index=False, compression="zstd")
    if models:
        joblib.dump(models[-1], model_path)

    importance = (feature_importance / max(len(models), 1)).sort_values(ascending=False)
    now = now_text()
    with write_transaction(args.db_path) as conn:
        conn.execute("DELETE FROM market_crash_warning_predictions WHERE run_id = ?", (args.run_id,))
        conn.execute("DELETE FROM market_crash_warning_features WHERE run_id = ?", (args.run_id,))
        conn.execute(
            replace_sql(
                "market_crash_warning_runs",
                [
                    "run_id", "model_type", "start_date", "end_date", "horizon", "feature_count", "status",
                    "summary_json", "model_path", "created_at", "updated_at",
                ],
                ["run_id"],
            ),
            (
                args.run_id, "lgbm_classifier", args.start, args.end, int(args.horizon), len(FEATURES), "success",
                json.dumps(overall, ensure_ascii=False), str(model_path), now, now,
            ),
        )
        pred_sql = replace_sql(
            "market_crash_warning_predictions",
            ["run_id", "trade_date", "shock_prob", "label", "test_year", "summary_json", "created_at", "updated_at"],
            ["run_id", "trade_date"],
        )
        conn.executemany(
            pred_sql,
            [
                (
                    args.run_id, str(row.trade_date), float(row.shock_prob), int(row.label), int(row.year),
                    json.dumps({"horizon": int(args.horizon)}, ensure_ascii=False), now, now,
                )
                for row in pred.itertuples(index=False)
            ],
        )
        feat_sql = replace_sql(
            "market_crash_warning_features",
            ["run_id", "feature", "importance", "rank_no", "created_at", "updated_at"],
            ["run_id", "feature"],
        )
        conn.executemany(
            feat_sql,
            [
                (args.run_id, str(feature), float(value), int(rank), now, now)
                for rank, (feature, value) in enumerate(importance.items(), start=1)
            ],
        )

    return {
        "run_id": args.run_id,
        "stage": "train_crash_warning_model",
        "model_path": str(model_path),
        "prediction_path": str(pred_path),
        "feature_count": len(FEATURES),
        "top_features": [{"feature": str(k), "importance": float(v)} for k, v in importance.head(12).items()],
        **overall,
    }


def _classification_metrics(y_true: np.ndarray, prob: np.ndarray, year: int) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score

    y_true = np.asarray(y_true).astype(int)
    prob = np.asarray(prob).astype(float)
    out: dict[str, Any] = {
        "year": int(year),
        "rows": int(len(y_true)),
        "positives": int(y_true.sum()),
        "positive_rate": float(y_true.mean()) if len(y_true) else 0.0,
    }
    if len(np.unique(y_true)) > 1:
        out["roc_auc"] = float(roc_auc_score(y_true, prob))
        out["avg_precision"] = float(average_precision_score(y_true, prob))
    else:
        out["roc_auc"] = None
        out["avg_precision"] = None
    for pct in [0.05, 0.10, 0.20]:
        n = max(1, int(math_floor(len(prob) * pct)))
        idx = np.argsort(prob)[-n:]
        out[f"top{int(pct * 100)}_precision"] = float(y_true[idx].mean()) if len(idx) else 0.0
        out[f"top{int(pct * 100)}_capture"] = float(y_true[idx].sum() / max(y_true.sum(), 1))
    threshold = float(np.quantile(prob, 0.90)) if len(prob) else 1.0
    pred = (prob >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y_true, pred, average="binary", zero_division=0)
    out["p90_threshold"] = threshold
    out["p90_precision"] = float(precision)
    out["p90_recall"] = float(recall)
    out["p90_f1"] = float(f1)
    return out


def math_floor(value: float) -> int:
    return int(np.floor(value))


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def data_root() -> Path:
    return Path(os.getenv("DATA_ROOT", str(ROOT.parent / "data_store"))).expanduser().resolve()


def import_lightgbm() -> tuple[Any | None, str]:
    try:
        import lightgbm as lgb
        return lgb, ""
    except Exception as exc:
        return None, str(exc)


if __name__ == "__main__":
    main()
