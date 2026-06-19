from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .registry import FactorDefinition, FeatureSetDefinition


@dataclass(frozen=True)
class FactorSnapshotSpec:
    factor_store_id: str
    start: str
    end: str
    horizons: tuple[int, ...]
    feature_set: str
    universe: str
    version: str
    params: dict[str, Any]

    def digest_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["horizons"] = sorted(int(value) for value in self.horizons)
        return payload


def _safe_part(value: str) -> str:
    text = str(value or "default").strip() or "default"
    return "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text)


def factor_snapshot_digest(spec: FactorSnapshotSpec) -> str:
    raw = json.dumps(spec.digest_payload(), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def factor_snapshot_dir(data_path: str | Path, spec: FactorSnapshotSpec) -> Path:
    horizon_text = "-".join(str(int(value)) for value in sorted(spec.horizons))
    return (
        Path(data_path)
        / "factor_store"
        / _safe_part(spec.factor_store_id)
        / f"version={_safe_part(spec.version)}"
        / f"feature_set={_safe_part(spec.feature_set)}"
        / f"start={_safe_part(spec.start)}"
        / f"end={_safe_part(spec.end)}"
        / f"horizons={_safe_part(horizon_text)}"
        / factor_snapshot_digest(spec)
    )


def factor_snapshot_path(data_path: str | Path, spec: FactorSnapshotSpec) -> Path:
    return factor_snapshot_dir(data_path, spec) / "panel.parquet"


def factor_snapshot_meta_path(data_path: str | Path, spec: FactorSnapshotSpec) -> Path:
    return factor_snapshot_dir(data_path, spec) / "metadata.json"


def latest_factor_snapshot_meta_path(data_path: str | Path, factor_store_id: str) -> Path:
    return Path(data_path) / "factor_store" / _safe_part(factor_store_id) / "latest.json"


def load_latest_factor_snapshot_meta(data_path: str | Path, factor_store_id: str) -> dict[str, Any]:
    path = latest_factor_snapshot_meta_path(data_path, factor_store_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_factor_snapshot(data_path: str | Path, spec: FactorSnapshotSpec, frame: pd.DataFrame, *, extra: dict[str, Any] | None = None) -> Path:
    path = factor_snapshot_path(data_path, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")
    meta = {
        "factor_store_id": spec.factor_store_id,
        "version": spec.version,
        "feature_set": spec.feature_set,
        "start": spec.start,
        "end": spec.end,
        "horizons": list(spec.horizons),
        "universe": spec.universe,
        "params": spec.params,
        "path": str(path),
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "columns": list(frame.columns),
        "trade_date_min": str(frame["trade_date"].min()) if "trade_date" in frame.columns and not frame.empty else "",
        "trade_date_max": str(frame["trade_date"].max()) if "trade_date" in frame.columns and not frame.empty else "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        meta.update(extra)
    factor_snapshot_meta_path(data_path, spec).write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    latest_path = latest_factor_snapshot_meta_path(data_path, spec.factor_store_id)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def update_factor_snapshot_metadata(data_path: str | Path, spec: FactorSnapshotSpec, updates: dict[str, Any]) -> None:
    meta_path = factor_snapshot_meta_path(data_path, spec)
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta.update(updates)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    latest_path = latest_factor_snapshot_meta_path(data_path, spec.factor_store_id)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_factor_manifest(data_path: str | Path, spec: FactorSnapshotSpec, manifest: dict[str, Any]) -> str:
    root = factor_snapshot_dir(data_path, spec)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(path)


def write_factor_artifacts(
    data_path: str | Path,
    spec: FactorSnapshotSpec,
    *,
    factor_definitions: Sequence[FactorDefinition] = (),
    feature_set: FeatureSetDefinition | None = None,
    preprocess_before_frame: pd.DataFrame | None = None,
    preprocess_after_frame: pd.DataFrame | None = None,
    single_factor_frame: pd.DataFrame | None = None,
    correlation_frame: pd.DataFrame | None = None,
    selection_frame: pd.DataFrame | None = None,
    quality_gate_frame: pd.DataFrame | None = None,
    drift_frame: pd.DataFrame | None = None,
) -> dict[str, str]:
    root = factor_snapshot_dir(data_path, spec)
    root.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    if factor_definitions:
        path = root / "factor_definitions.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "name": item.name,
                        "category": item.category,
                        "description": item.description,
                        "lookback_days": item.lookback_days,
                        "enabled": item.enabled,
                    }
                    for item in factor_definitions
                ],
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        out["factor_definitions_path"] = str(path)
    if feature_set is not None:
        path = root / "feature_set.json"
        path.write_text(
            json.dumps(
                {
                    "feature_set_id": feature_set.feature_set_id,
                    "strategy_id": feature_set.strategy_id,
                    "factor_names": list(feature_set.factor_names),
                    "description": feature_set.description,
                    "preprocess": feature_set.preprocess,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        out["feature_set_path"] = str(path)
    if preprocess_before_frame is not None:
        parquet_path = root / "preprocess_before_report.parquet"
        json_path = root / "preprocess_before_report.json"
        preprocess_before_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(preprocess_before_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["preprocess_before_report_path"] = str(parquet_path)
        out["preprocess_before_report_json_path"] = str(json_path)
    if preprocess_after_frame is not None:
        parquet_path = root / "preprocess_after_report.parquet"
        json_path = root / "preprocess_after_report.json"
        preprocess_after_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(preprocess_after_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["preprocess_after_report_path"] = str(parquet_path)
        out["preprocess_after_report_json_path"] = str(json_path)
    if single_factor_frame is not None:
        parquet_path = root / "single_factor_report.parquet"
        json_path = root / "single_factor_report.json"
        single_factor_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(single_factor_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["single_factor_report_path"] = str(parquet_path)
        out["single_factor_report_json_path"] = str(json_path)
    if correlation_frame is not None:
        parquet_path = root / "factor_correlation_report.parquet"
        json_path = root / "factor_correlation_report.json"
        correlation_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(correlation_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["factor_correlation_report_path"] = str(parquet_path)
        out["factor_correlation_report_json_path"] = str(json_path)
    if selection_frame is not None:
        parquet_path = root / "factor_selection_report.parquet"
        json_path = root / "factor_selection_report.json"
        selection_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(selection_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["factor_selection_report_path"] = str(parquet_path)
        out["factor_selection_report_json_path"] = str(json_path)
    if quality_gate_frame is not None:
        parquet_path = root / "quality_gate_report.parquet"
        json_path = root / "quality_gate_report.json"
        quality_gate_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(quality_gate_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["quality_gate_report_path"] = str(parquet_path)
        out["quality_gate_report_json_path"] = str(json_path)
    if drift_frame is not None:
        parquet_path = root / "factor_drift_report.parquet"
        json_path = root / "factor_drift_report.json"
        drift_frame.to_parquet(parquet_path, index=False, compression="zstd")
        json_path.write_text(drift_frame.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
        out["factor_drift_report_path"] = str(parquet_path)
        out["factor_drift_report_json_path"] = str(json_path)
    return out


def load_factor_snapshot(data_path: str | Path, spec: FactorSnapshotSpec, required_columns: Sequence[str] = ()) -> pd.DataFrame | None:
    path = factor_snapshot_path(data_path, spec)
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        return None
    return frame
