"""Train market regime risk classifiers.

This is not a "predict tomorrow's crash" model.  It estimates whether the
current close belongs to a regime that is unsuitable for small-cap strategies:
market drawdown risk, small-cap ecology deterioration, style shift away from
small caps, or repair. Features are close-of-day values and labels are future
windows, so the model is intended for after-close next-session risk gating. The
historical ``shock_prob`` output is kept for strategy compatibility.
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

from common.infra.db import add_column, replace_sql, table_columns, write_transaction


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

TARGETS = {
    "shock": "label",
    "market_risk": "market_risk_label",
    "smallcap_ecology": "smallcap_ecology_risk_label",
    "style_shift": "style_shift_label",
    "liquidity_squeeze": "liquidity_squeeze_label",
    "repair": "repair_label",
}

PROB_COLUMNS = {
    "shock": "shock_prob",
    "market_risk": "market_risk_prob",
    "smallcap_ecology": "smallcap_ecology_risk_prob",
    "style_shift": "style_shift_prob",
    "liquidity_squeeze": "liquidity_squeeze_prob",
    "repair": "repair_prob",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--min-train-years", type=int, default=4)
    parser.add_argument("--min-test-year", type=int, default=0)
    args = parser.parse_args()

    ensure_tables()
    data = build_dataset(args.start, args.end, args.horizon)
    if data.empty:
        raise RuntimeError("market_risk_state_daily has no usable rows")
    summary = train_walk_forward(args, data)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def ensure_tables() -> None:
    with write_transaction() as conn:
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
                    market_risk_prob DOUBLE,
                    smallcap_ecology_risk_prob DOUBLE,
                    style_shift_prob DOUBLE,
                    liquidity_squeeze_prob DOUBLE,
                    repair_prob DOUBLE,
                    risk_prob DOUBLE,
                    final_smallcap_risk DOUBLE,
                    suggested_exposure DOUBLE,
                    regime VARCHAR(64) NOT NULL DEFAULT '',
                    label BIGINT NOT NULL DEFAULT 0,
                    market_risk_label BIGINT NOT NULL DEFAULT 0,
                    smallcap_ecology_risk_label BIGINT NOT NULL DEFAULT 0,
                    style_shift_label BIGINT NOT NULL DEFAULT 0,
                    liquidity_squeeze_label BIGINT NOT NULL DEFAULT 0,
                    repair_label BIGINT NOT NULL DEFAULT 0,
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
                    market_risk_prob REAL,
                    smallcap_ecology_risk_prob REAL,
                    style_shift_prob REAL,
                    liquidity_squeeze_prob REAL,
                    repair_prob REAL,
                    risk_prob REAL,
                    final_smallcap_risk REAL,
                    suggested_exposure REAL,
                    regime TEXT NOT NULL DEFAULT '',
                    label INTEGER NOT NULL DEFAULT 0,
                    market_risk_label INTEGER NOT NULL DEFAULT 0,
                    smallcap_ecology_risk_label INTEGER NOT NULL DEFAULT 0,
                    style_shift_label INTEGER NOT NULL DEFAULT 0,
                    liquidity_squeeze_label INTEGER NOT NULL DEFAULT 0,
                    repair_label INTEGER NOT NULL DEFAULT 0,
                    test_year INTEGER,
                    summary_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, trade_date)
                );
                """
            )
        existing = table_columns(conn, "market_crash_warning_predictions")
        for name, ddl in [
            ("market_risk_prob", "DOUBLE"),
            ("smallcap_ecology_risk_prob", "DOUBLE"),
            ("style_shift_prob", "DOUBLE"),
            ("liquidity_squeeze_prob", "DOUBLE"),
            ("repair_prob", "DOUBLE"),
            ("risk_prob", "DOUBLE"),
            ("final_smallcap_risk", "DOUBLE"),
            ("suggested_exposure", "DOUBLE"),
            ("regime", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("market_risk_label", "BIGINT NOT NULL DEFAULT 0"),
            ("smallcap_ecology_risk_label", "BIGINT NOT NULL DEFAULT 0"),
            ("style_shift_label", "BIGINT NOT NULL DEFAULT 0"),
            ("liquidity_squeeze_label", "BIGINT NOT NULL DEFAULT 0"),
            ("repair_label", "BIGINT NOT NULL DEFAULT 0"),
        ]:
            if name not in existing:
                sqlite_ddl = ddl.replace("DOUBLE", "REAL").replace("BIGINT", "INTEGER").replace("VARCHAR(64)", "TEXT")
                add_column(conn, "market_crash_warning_predictions", name, ddl if conn.backend == "mysql" else sqlite_ddl)


def build_dataset(start: str, end: str, horizon: int) -> pd.DataFrame:
    warmup_start = (pd.to_datetime(start, format="%Y%m%d") - pd.Timedelta(days=420)).strftime("%Y%m%d")
    with write_transaction() as conn:
        rows = conn.execute(
            """
            SELECT trade_date, state, COALESCE(risk_score, 0), COALESCE(market_return, 0),
                   COALESCE(up_ratio, 0), COALESCE(down_ratio, 0), COALESCE(breadth20, 0),
                   COALESCE(limit_up_ratio, 0), COALESCE(limit_down_ratio, 0),
                   COALESCE(limit_down_ratio5, 0), COALESCE(amount_chg20, 0),
                   COALESCE(small_large_rel20, 0), COALESCE(drawdown20, 0),
                   COALESCE(drawdown60, 0), COALESCE(drawdown120, 0),
                   COALESCE(trend60, 0), COALESCE(volatility20, 0),
                   COALESCE(index_anchor_ret20, 0), COALESCE(index_anchor_drawdown20, 0),
                   COALESCE(index_anchor_rel20, 0)
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
            "index_anchor_ret20", "index_anchor_drawdown20", "index_anchor_rel20",
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

    shock_flags = []
    market_risk_flags = []
    smallcap_ecology_flags = []
    style_shift_flags = []
    liquidity_squeeze_flags = []
    repair_flags = []
    for offset in range(1, horizon + 1):
        future_state = data["state"].shift(-offset).isin(SHOCK_STATES)
        future_hard_drop = data["market_return"].shift(-offset) <= -0.045
        future_limit_spread = data["limit_down_ratio"].shift(-offset) >= 0.025
        shock_flags.append(future_state | future_hard_drop | future_limit_spread)
        market_risk_flags.append(
            data["state"].shift(-offset).isin({"crash", "liquidity_squeeze"})
            | (data["market_return"].shift(-offset) <= -0.045)
            | ((data["drawdown20"].shift(-offset) <= -0.100) & (data["breadth20"].shift(-offset) <= 0.45))
            | ((data["volatility20"].shift(-offset) >= 0.42) & (data["market_return"].shift(-offset) <= -0.020))
            | (data["index_anchor_drawdown20"].shift(-offset) <= -0.120)
        )
        smallcap_ecology_flags.append(
            (data["breadth20"].shift(-offset) <= 0.40)
            | (data["limit_down_ratio"].shift(-offset) >= 0.018)
            | (data["limit_down_ratio5"].shift(-offset) >= 0.012)
            | ((data["limit_up_ratio"].shift(-offset) <= 0.006) & (data["down_ratio"].shift(-offset) >= 0.66))
            | ((data["index_anchor_ret20"].shift(-offset) <= -0.060) & (data["breadth20"].shift(-offset) <= 0.46))
        )
        style_shift_flags.append(
            (data["small_large_rel20"].shift(-offset) <= -0.090)
            | (data["index_anchor_rel20"].shift(-offset) <= -0.070)
            | ((data["index_anchor_ret20"].shift(-offset) <= -0.050) & (data["market_return"].shift(-offset) >= -0.005))
        )
        liquidity_squeeze_flags.append(
            data["state"].shift(-offset).eq("liquidity_squeeze")
            | future_limit_spread
            | ((data["amount_chg20"].shift(-offset) <= -0.25) & (data["volatility20"].shift(-offset) >= 0.26))
            | ((data["market_return"].shift(-offset) <= -0.035) & (data["limit_down_ratio5"].shift(-offset) >= 0.012))
        )
        repair_flags.append(data["state"].shift(-offset).eq("post_crash_repair"))
    label = shock_flags[0]
    for flag in shock_flags[1:]:
        label = label | flag
    data["label"] = label.astype(int)
    for target, flags in [
        ("market_risk_label", market_risk_flags),
        ("smallcap_ecology_risk_label", smallcap_ecology_flags),
        ("style_shift_label", style_shift_flags),
        ("liquidity_squeeze_label", liquidity_squeeze_flags),
        ("repair_label", repair_flags),
    ]:
        target_label = flags[0]
        for flag in flags[1:]:
            target_label = target_label | flag
        data[target] = target_label.astype(int)
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

    predictions_by_target: dict[str, list[pd.DataFrame]] = {target: [] for target in TARGETS}
    fold_metrics_by_target: dict[str, list[dict[str, Any]]] = {target: [] for target in TARGETS}
    feature_importance = pd.Series(0.0, index=FEATURES, dtype="float64")
    latest_models: dict[str, Any] = {}
    x_all = data[FEATURES].astype(float)

    for year in test_years:
        train_mask = data["year"] < year
        test_mask = data["year"] == year
        if int(train_mask.sum()) < 500 or int(test_mask.sum()) == 0:
            continue
        for target, label_col in TARGETS.items():
            y_all = data[label_col].astype(int)
            y_train = y_all.loc[train_mask]
            pos = int(y_train.sum())
            neg = int(len(y_train) - pos)
            if pos <= 3:
                continue
            scale_pos_weight = max(1.0, neg / max(pos, 1))
            model = lgb.LGBMClassifier(
                objective="binary",
                n_estimators=240,
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
            fold = data.loc[test_mask, ["trade_date", label_col, "year"]].copy()
            fold = fold.rename(columns={label_col: "label"})
            fold[PROB_COLUMNS[target]] = prob.astype(float)
            predictions_by_target[target].append(fold)
            fold_metrics_by_target[target].append(_classification_metrics(fold["label"].to_numpy(), prob, int(year)))
            feature_importance += pd.Series(model.feature_importances_, index=FEATURES)
            latest_models[target] = model

    if not predictions_by_target["shock"]:
        raise RuntimeError("no walk-forward prediction was generated")

    pred: pd.DataFrame | None = None
    target_summaries: dict[str, Any] = {}
    for target, frames in predictions_by_target.items():
        if not frames:
            continue
        part = pd.concat(frames, ignore_index=True).sort_values("trade_date")
        label_col = TARGETS[target]
        prob_col = PROB_COLUMNS[target]
        target_summary = _classification_metrics(part["label"].to_numpy(), part[prob_col].to_numpy(), 0)
        target_summary["folds"] = fold_metrics_by_target[target]
        target_summary["positive_rate"] = float(part["label"].mean())
        target_summaries[target] = target_summary
        part = part.rename(columns={"label": label_col})
        keep = ["trade_date", "year", label_col, prob_col]
        pred = part[keep] if pred is None else pred.merge(part[keep], on=["trade_date", "year"], how="outer")
    if pred is None or pred.empty:
        raise RuntimeError("no walk-forward prediction was generated")
    for target, label_col in TARGETS.items():
        prob_col = PROB_COLUMNS[target]
        if label_col not in pred.columns:
            pred[label_col] = 0
        if prob_col not in pred.columns:
            pred[prob_col] = 0.0
        pred[label_col] = pd.to_numeric(pred[label_col], errors="coerce").fillna(0).astype(int)
        pred[prob_col] = pd.to_numeric(pred[prob_col], errors="coerce").fillna(0.0).astype(float)
    pred["risk_prob"] = pred[["shock_prob", "market_risk_prob", "smallcap_ecology_risk_prob", "style_shift_prob", "liquidity_squeeze_prob"]].max(axis=1)
    pred["final_smallcap_risk"] = (
        pred["market_risk_prob"].astype(float) * 0.30
        + pred["smallcap_ecology_risk_prob"].astype(float) * 0.45
        + pred["style_shift_prob"].astype(float) * 0.25
    ).clip(0.0, 1.0)
    pred["regime"] = pred["final_smallcap_risk"].map(risk_regime)
    pred["suggested_exposure"] = pred["final_smallcap_risk"].map(suggested_exposure)
    pred = pred.sort_values("trade_date").reset_index(drop=True)
    overall = dict(target_summaries.get("shock") or {})
    overall["targets"] = target_summaries
    overall["prediction_rows"] = int(len(pred))
    overall["test_start"] = str(pred["trade_date"].min())
    overall["test_end"] = str(pred["trade_date"].max())

    out_dir = data_root() / "crash_warning_models" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.parquet"
    model_path = out_dir / "latest_model.joblib"
    pred.to_parquet(pred_path, index=False, compression="zstd")
    if latest_models:
        joblib.dump(latest_models, model_path)

    importance = (feature_importance / max(len(latest_models), 1)).sort_values(ascending=False)
    now = now_text()
    with write_transaction() as conn:
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
                args.run_id, "market_regime_lgbm", args.start, args.end, int(args.horizon), len(FEATURES), "success",
                json.dumps(overall, ensure_ascii=False), str(model_path), now, now,
            ),
        )
        pred_sql = replace_sql(
            "market_crash_warning_predictions",
            [
                "run_id", "trade_date", "shock_prob", "market_risk_prob", "smallcap_ecology_risk_prob",
                "style_shift_prob", "liquidity_squeeze_prob", "repair_prob", "risk_prob",
                "final_smallcap_risk", "suggested_exposure", "regime", "label", "market_risk_label",
                "smallcap_ecology_risk_label", "style_shift_label", "liquidity_squeeze_label",
                "repair_label", "test_year", "summary_json", "created_at", "updated_at",
            ],
            ["run_id", "trade_date"],
        )
        conn.executemany(
            pred_sql,
            [
                (
                    args.run_id,
                    str(row.trade_date),
                    float(row.shock_prob),
                    float(row.market_risk_prob),
                    float(row.smallcap_ecology_risk_prob),
                    float(row.style_shift_prob),
                    float(row.liquidity_squeeze_prob),
                    float(row.repair_prob),
                    float(row.risk_prob),
                    float(row.final_smallcap_risk),
                    float(row.suggested_exposure),
                    str(row.regime),
                    int(row.label),
                    int(row.market_risk_label),
                    int(row.smallcap_ecology_risk_label),
                    int(row.style_shift_label),
                    int(row.liquidity_squeeze_label),
                    int(row.repair_label),
                    int(row.year),
                    json.dumps(
                        {
                            "horizon": int(args.horizon),
                            "risk_prob": float(row.risk_prob),
                            "final_smallcap_risk": float(row.final_smallcap_risk),
                            "suggested_exposure": float(row.suggested_exposure),
                            "regime": str(row.regime),
                            "market_risk_prob": float(row.market_risk_prob),
                            "smallcap_ecology_risk_prob": float(row.smallcap_ecology_risk_prob),
                            "style_shift_prob": float(row.style_shift_prob),
                            "liquidity_squeeze_prob": float(row.liquidity_squeeze_prob),
                            "repair_prob": float(row.repair_prob),
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    now,
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
        "target_summaries": target_summaries,
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


def risk_regime(value: float) -> str:
    risk = float(value or 0.0)
    if risk >= 0.70:
        return "panic"
    if risk >= 0.55:
        return "weak"
    if risk >= 0.35:
        return "caution"
    if risk <= 0.18:
        return "strong"
    return "normal"


def suggested_exposure(value: float) -> float:
    risk = float(value or 0.0)
    if risk >= 0.70:
        return 0.0
    if risk >= 0.55:
        return 0.30
    if risk >= 0.35:
        return 0.60
    return 1.0


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
