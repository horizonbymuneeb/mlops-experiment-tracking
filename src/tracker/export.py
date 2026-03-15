"""JSON and CSV export, plus the matching importer.

The JSON payload is a self-describing document (``format``/``version``/``runs``)
rather than a bare list, so an old export can be recognised and either imported
or rejected instead of being parsed into nonsense. Import allocates new run ids
and keeps params, tags, metric points and artifact *metadata*; blobs themselves
are not embedded — an export is a description of runs, not a backup of the
artifact store.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tracker.artifacts import atomic_write_bytes
from tracker.db import Database
from tracker.models import (
    iso_now,
    parse_timestamp,
)
from tracker.query import (
    RunFilter,
    fetch_artifacts,
    fetch_metric_series,
    fetch_params,
    fetch_tags,
    query_runs,
)

EXPORT_FORMAT = "mlops-experiment-tracking.export"
EXPORT_VERSION = 1
CSV_METRIC_COLUMNS = ("run_id", "run_name", "key", "step", "value")
CSV_PARAM_COLUMNS = ("run_id", "run_name", "key", "value", "type")
CSV_SUMMARY_COLUMNS = (
    "run_id",
    "name",
    "status",
    "started_at",
    "finished_at",
    "duration_seconds",
    "tags",
    "params",
    "metrics",
)


class ExportError(ValueError):
    """Raised when a payload cannot be exported or imported."""


def to_jsonable(value: Any) -> Any:
    """Convert dataclasses, tuples and nested containers into JSON-safe values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        return to_jsonable(value.to_dict())
    raise ExportError(f"cannot serialise value of type {type(value).__name__}")


def export_run(db: Database, run_id: int) -> dict[str, Any]:
    """One run with params, tags, metric curves and artifact metadata."""
    row = db.execute_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise ExportError(f"run {run_id} does not exist")
    metrics: dict[str, list[list[float]]] = {}
    for key in sorted(
        str(item["key"])
        for item in db.execute(
            "SELECT DISTINCT key FROM metrics WHERE run_id = ?", (run_id,)
        )
    ):
        metrics[key] = [[step, value] for step, value in fetch_metric_series(db, run_id, key)]
    return {
        "run": {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "status": str(row["status"]),
            "started_at": str(row["started_at"]),
            "finished_at": row["finished_at"],
            "host": row["host"],
            "notes": row["notes"],
            "resumed_count": int(row["resumed_count"] or 0),
        },
        "params": to_jsonable(fetch_params(db, run_id)),
        "tags": fetch_tags(db, run_id),
        "metrics": metrics,
        "artifacts": to_jsonable(fetch_artifacts(db, run_id)),
    }


def export_runs(
    db: Database,
    *,
    run_ids: Sequence[int] | None = None,
    run_filter: RunFilter | None = None,
    include_artifacts: bool = True,
) -> dict[str, Any]:
    """Build the export document for the selected runs."""
    if run_ids is not None:
        resolved = []
        for ref in run_ids:
            row = db.execute_one("SELECT id FROM runs WHERE id = ?", (int(ref),))
            if row is None:
                raise ExportError(f"run {ref} does not exist")
            resolved.append(int(row["id"]))
    else:
        resolved = [record.id for record in query_runs(db, run_filter or RunFilter())]
    runs = [export_run(db, run_id) for run_id in resolved]
    if not include_artifacts:
        for payload in runs:
            payload["artifacts"] = []
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": iso_now(),
        "run_count": len(runs),
        "runs": runs,
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Serialise ``payload`` to ``path`` atomically, with stable key order."""
    text = json.dumps(to_jsonable(payload), indent=2, sort_keys=True) + "\n"
    return atomic_write_bytes(path, text.encode("utf-8"))


def read_json(path: str | Path) -> dict[str, Any]:
    """Read a JSON document and check its top level is an object."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExportError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExportError(f"{path} must contain a JSON object")
    return payload


def export_json_file(
    db: Database,
    path: str | Path,
    *,
    run_ids: Sequence[int] | None = None,
    run_filter: RunFilter | None = None,
) -> Path:
    """Write the export document to ``path`` and return it."""
    payload = export_runs(db, run_ids=run_ids, run_filter=run_filter)
    return write_json(path, payload)


def _csv_text(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue()


def export_metrics_csv(
    db: Database, path: str | Path, run_ids: Sequence[int] | None = None
) -> Path:
    """Long-format metrics: one row per (run, key, step)."""
    ids = (
        [int(run_id) for run_id in run_ids]
        if run_ids is not None
        else [record.id for record in query_runs(db, RunFilter())]
    )
    rows: list[list[Any]] = []
    for run_id in ids:
        row = db.execute_one("SELECT name FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise ExportError(f"run {run_id} does not exist")
        name = str(row["name"])
        for item in db.execute(
            "SELECT key, step, value FROM metrics WHERE run_id = ? ORDER BY key, step",
            (run_id,),
        ):
            rows.append([run_id, name, item["key"], int(item["step"]), float(item["value"])])
    return atomic_write_bytes(path, _csv_text(CSV_METRIC_COLUMNS, rows).encode("utf-8"))
