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


def export_params_csv(
    db: Database, path: str | Path, run_ids: Sequence[int] | None = None
) -> Path:
    """One row per (run, param)."""
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
        for key, value in sorted(fetch_params(db, run_id).items()):
            rows.append([run_id, name, key, json.dumps(value, sort_keys=True), type(value).__name__])
    return atomic_write_bytes(path, _csv_text(CSV_PARAM_COLUMNS, rows).encode("utf-8"))


def export_summary_csv(
    db: Database, path: str | Path, run_ids: Sequence[int] | None = None
) -> Path:
    """One row per run with counts instead of the full curves."""
    ids = (
        [int(run_id) for run_id in run_ids]
        if run_ids is not None
        else [record.id for record in query_runs(db, RunFilter())]
    )
    rows: list[list[Any]] = []
    for run_id in ids:
        payload = export_run(db, run_id)
        run = payload["run"]
        started = parse_timestamp(run["started_at"])
        finished = parse_timestamp(run["finished_at"]) if run["finished_at"] else None
        duration = (finished - started).total_seconds() if finished else ""
        rows.append(
            [
                run["id"],
                run["name"],
                run["status"],
                run["started_at"],
                run["finished_at"] or "",
                duration,
                ";".join(payload["tags"]),
                json.dumps(payload["params"], sort_keys=True),
                json.dumps({key: len(points) for key, points in payload["metrics"].items()}, sort_keys=True),
            ]
        )
    return atomic_write_bytes(path, _csv_text(CSV_SUMMARY_COLUMNS, rows).encode("utf-8"))


def export_manifest(db: Database) -> dict[str, Any]:
    """Digest → size plus the runs that reference each blob."""
    rows = db.execute(
        "SELECT a.digest, a.size_bytes, a.run_id, a.name FROM artifacts a ORDER BY a.digest"
    )
    blobs: dict[str, dict[str, Any]] = {}
    for row in rows:
        digest = str(row["digest"])
        entry = blobs.setdefault(
            digest,
            {"digest": digest, "size_bytes": int(row["size_bytes"]), "references": []},
        )
        entry["references"].append({"run_id": int(row["run_id"]), "name": str(row["name"])})
    return {
        "format": EXPORT_FORMAT + ".manifest",
        "version": EXPORT_VERSION,
        "generated_at": iso_now(),
        "blob_count": len(blobs),
        "total_bytes": sum(int(entry["size_bytes"]) for entry in blobs.values()),
        "blobs": blobs,
    }


def _require_export_document(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if payload.get("format") != EXPORT_FORMAT:
        raise ExportError(
            f"unexpected export format {payload.get('format')!r} (expected {EXPORT_FORMAT!r})"
        )
    version = payload.get("version")
    if version != EXPORT_VERSION:
        raise ExportError(f"unsupported export version {version!r}")
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ExportError("export document contains no runs")
    for index, entry in enumerate(runs):
        if not isinstance(entry, dict) or "run" not in entry:
            raise ExportError(f"run entry {index} is malformed")
    return runs


def import_runs(
    db: Database, payload: Mapping[str, Any], *, run_ids: Sequence[int] | None = None
) -> list[int]:
    """Recreate runs from an export document; returns the new run ids."""
    entries = _require_export_document(payload)
    wanted = {int(run_id) for run_id in run_ids} if run_ids is not None else None
    created: list[int] = []
    for entry in entries:
        run = entry["run"]
        original_id = int(run["id"])
        if wanted is not None and original_id not in wanted:
            continue
        with db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO runs (name, status, started_at, finished_at, host, notes, resumed_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(run["name"]),
                    str(run["status"]),
                    str(run["started_at"]),
                    run.get("finished_at"),
                    run.get("host"),
                    run.get("notes"),
                    int(run.get("resumed_count") or 0),
                ),
            )
            new_id = int(cursor.lastrowid)
            params = entry.get("params") or {}
            from tracker.models import coerce_param_value

            conn.executemany(
                "INSERT INTO params (run_id, key, value, value_type) VALUES (?, ?, ?, ?)",
                [(new_id, str(key), *coerce_param_value(value)) for key, value in params.items()],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO tags (run_id, tag) VALUES (?, ?)",
                [(new_id, str(tag)) for tag in entry.get("tags") or []],
            )
            metric_rows = []
            for key, points in (entry.get("metrics") or {}).items():
                for step, value in points:
                    metric_rows.append((new_id, str(key), int(step), float(value), iso_now()))
            if metric_rows:
                conn.executemany(
                    "INSERT INTO metrics (run_id, key, step, value, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    metric_rows,
                )
            artifact_rows = [
                (
                    new_id,
                    str(artifact["name"]),
                    str(artifact["digest"]),
                    int(artifact["size_bytes"]),
                    artifact.get("media_type"),
                    str(artifact.get("created_at") or iso_now()),
                )
                for artifact in entry.get("artifacts") or []
            ]
            if artifact_rows:
                conn.executemany(
                    "INSERT INTO artifacts (run_id, name, digest, size_bytes, media_type, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    artifact_rows,
                )
        created.append(new_id)
    if not created:
        raise ExportError("no runs matched the import selection")
    return created
