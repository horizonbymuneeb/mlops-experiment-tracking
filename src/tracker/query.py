"""Filtering and read helpers over the tracker tables.

``RunFilter`` is deliberately declarative: it turns into one SQL statement with
bound parameters, so a filter object can be built by the CLI, by tests or by a
notebook and still produce the same rows. Two conventions are worth knowing:

* ``params`` compares the *encoded* value and its type, so ``epochs=10`` does
  not match a run that logged ``epochs=10.0``. Silent float/int coercion is how
  experiment queries end up wrong.
* ``metric_ranges`` matches when *any* point of that metric falls inside the
  range, which is what people mean by "runs that reached loss < 0.3".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from tracker.db import Database
from tracker.models import (
    ArtifactRecord,
    MetricRecord,
    RunRecord,
    RunSummary,
    coerce_param_value,
    decode_param_value,
    row_to_dict,
)

ORDERABLE_COLUMNS = ("id", "started_at", "finished_at", "name", "status")
MAX_LIMIT = 1000


class QueryError(ValueError):
    """Raised for filters that cannot be translated to SQL."""


def escape_like(text: str) -> str:
    """Escape ``%``, ``_`` and ``\\`` so a LIKE pattern is matched literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def normalize_limit(limit: int | None) -> int | None:
    """Validate a row limit (``None`` means unlimited)."""
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise QueryError(f"limit must be an int, got {limit!r}")
    if limit < 1:
        raise QueryError("limit must be >= 1")
    if limit > MAX_LIMIT:
        raise QueryError(f"limit must be <= {MAX_LIMIT}")
    return limit


def normalize_offset(offset: int) -> int:
    """Validate a pagination offset."""
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise QueryError(f"offset must be an int, got {offset!r}")
    if offset < 0:
        raise QueryError("offset must be >= 0")
    return offset


@dataclass
class RunFilter:
    """Declarative run query."""

    status: str | Sequence[str] | None = None
    name_like: str | None = None
    tags: Sequence[str] = field(default_factory=tuple)
    params: Mapping[str, Any] = field(default_factory=dict)
    param_ranges: Mapping[str, tuple[float | None, float | None]] = field(
        default_factory=dict
    )
    metric_ranges: Mapping[str, tuple[float | None, float | None]] = field(
        default_factory=dict
    )
    started_after: str | None = None
    started_before: str | None = None
    order_by: str = "id"
    descending: bool = False
    limit: int | None = None
    offset: int = 0

    def validate(self) -> "RunFilter":
        """Raise ``QueryError`` if the filter cannot be executed as written."""
        if self.status is not None:
            statuses = [self.status] if isinstance(self.status, str) else list(self.status)
            if not statuses:
                raise QueryError("status filter is empty")
            for status in statuses:
                if not isinstance(status, str) or not status:
                    raise QueryError(f"invalid status {status!r}")
        if self.name_like is not None and not isinstance(self.name_like, str):
            raise QueryError("name_like must be a string")
        if self.order_by not in ORDERABLE_COLUMNS:
            raise QueryError(
                f"order_by must be one of {ORDERABLE_COLUMNS}, got {self.order_by!r}"
            )
        normalize_limit(self.limit)
        normalize_offset(self.offset)
        for label, mapping in (("params", self.params), ("param_ranges", self.param_ranges),
                               ("metric_ranges", self.metric_ranges)):
            if not isinstance(mapping, Mapping):
                raise QueryError(f"{label} must be a mapping")
        for key, bounds in self.param_ranges.items():
            _validate_bounds("param_ranges", key, bounds)
        for key, bounds in self.metric_ranges.items():
            _validate_bounds("metric_ranges", key, bounds)
        return self


def _validate_bounds(label: str, key: str, bounds: Any) -> None:
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        raise QueryError(f"{label}[{key!r}] must be a (low, high) pair")
    low, high = bounds
    for value in (low, high):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise QueryError(f"{label}[{key!r}] bounds must be numbers or None")
    if low is not None and high is not None and low > high:
        raise QueryError(f"{label}[{key!r}] has low > high")


def where_clause(filt: RunFilter) -> tuple[str, list[Any]]:
    """Translate a validated filter into a ``WHERE`` fragment plus parameters."""
    filt.validate()
    clauses: list[str] = []
    params: list[Any] = []

    if filt.status is not None:
        statuses = [filt.status] if isinstance(filt.status, str) else list(filt.status)
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"r.status IN ({placeholders})")
        params.extend(statuses)

    if filt.name_like:
        clauses.append("r.name LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(filt.name_like)}%")

    if filt.started_after:
        clauses.append("r.started_at >= ?")
        params.append(filt.started_after)
    if filt.started_before:
        clauses.append("r.started_at <= ?")
        params.append(filt.started_before)

    if filt.tags:
        tags = [str(tag) for tag in filt.tags]
        placeholders = ", ".join("?" for _ in tags)
        clauses.append(
            "(SELECT COUNT(DISTINCT t.tag) FROM tags t "
            f"WHERE t.run_id = r.id AND t.tag IN ({placeholders})) = ?"
        )
        params.extend(tags)
        params.append(len(tags))

    for key, value in filt.params.items():
        encoded, type_name = coerce_param_value(value)
        clauses.append(
            "EXISTS (SELECT 1 FROM params p WHERE p.run_id = r.id "
            "AND p.key = ? AND p.value = ? AND p.value_type = ?)"
        )
        params.extend([str(key), encoded, type_name])

    for key, (low, high) in filt.param_ranges.items():
        clause = (
            "EXISTS (SELECT 1 FROM params p WHERE p.run_id = r.id "
            "AND p.key = ? AND p.value_type IN ('int','float')"
        )
        params.append(str(key))
        if low is not None:
            clause += " AND CAST(p.value AS REAL) >= ?"
            params.append(float(low))
        if high is not None:
            clause += " AND CAST(p.value AS REAL) <= ?"
            params.append(float(high))
        clauses.append(clause + ")")

    for key, (low, high) in filt.metric_ranges.items():
        clause = (
            "EXISTS (SELECT 1 FROM metrics m WHERE m.run_id = r.id AND m.key = ?"
        )
        params.append(str(key))
        if low is not None:
            clause += " AND m.value >= ?"
            params.append(float(low))
        if high is not None:
            clause += " AND m.value <= ?"
            params.append(float(high))
        clauses.append(clause + ")")

    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def build_run_query(filt: RunFilter) -> tuple[str, list[Any]]:
    """Full ``SELECT`` for a filter, including order and pagination."""
    where, params = where_clause(filt)
    direction = "DESC" if filt.descending else "ASC"
    sql = f"SELECT r.* FROM runs r{where} ORDER BY r.{filt.order_by} {direction}, r.id {direction}"
    limit = normalize_limit(filt.limit)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
        offset = normalize_offset(filt.offset)
        if offset:
            sql += " OFFSET ?"
            params.append(offset)
    return sql, params


def query_runs(db: Database, filt: RunFilter | None = None) -> list[RunRecord]:
    """Return the runs matching ``filt``."""
    sql, params = build_run_query(filt or RunFilter())
    return [RunRecord.from_row(row) for row in db.execute(sql, params)]


def count_runs(db: Database, filt: RunFilter | None = None) -> int:
    """Number of runs matching ``filt``, ignoring limit/offset."""
    where, params = where_clause(filt or RunFilter())
    row = db.execute_one(f"SELECT COUNT(*) AS n FROM runs r{where}", params)
    return int(row["n"]) if row else 0


def fetch_params(db: Database, run_id: int) -> dict[str, Any]:
    """Decoded params for one run."""
    rows = db.execute(
        "SELECT key, value, value_type FROM params WHERE run_id = ? ORDER BY key",
        (run_id,),
    )
    return {row["key"]: decode_param_value(row["value"], row["value_type"]) for row in rows}


def fetch_metric_series(db: Database, run_id: int, key: str) -> list[tuple[int, float]]:
    """``[(step, value), ...]`` for one run and metric key."""
    rows = db.execute(
        "SELECT step, value FROM metrics WHERE run_id = ? AND key = ? ORDER BY step",
        (run_id, str(key)),
    )
    return [(int(row["step"]), float(row["value"])) for row in rows]


def fetch_metric_rows(db: Database, run_id: int, key: str | None = None) -> list[MetricRecord]:
    """Metric rows for a run, optionally narrowed to one key."""
    if key is None:
        rows = db.execute(
            "SELECT * FROM metrics WHERE run_id = ? ORDER BY key, step", (run_id,)
        )
    else:
        rows = db.execute(
            "SELECT * FROM metrics WHERE run_id = ? AND key = ? ORDER BY step",
            (run_id, str(key)),
        )
    return [MetricRecord.from_row(row) for row in rows]


def fetch_latest_metric(db: Database, run_id: int, key: str) -> float | None:
    """Most recent value of one metric, or ``None`` if it was never logged."""
    row = db.execute_one(
        "SELECT value FROM metrics WHERE run_id = ? AND key = ? ORDER BY step DESC LIMIT 1",
        (run_id, str(key)),
    )
    return float(row["value"]) if row else None


def fetch_metric_keys(db: Database, run_id: int) -> list[str]:
    """Distinct metric keys of one run."""
    rows = db.execute(
        "SELECT DISTINCT key FROM metrics WHERE run_id = ? ORDER BY key", (run_id,)
    )
    return [str(row["key"]) for row in rows]


def fetch_artifacts(db: Database, run_id: int) -> list[ArtifactRecord]:
    """Artifacts linked to one run."""
    rows = db.execute(
        "SELECT * FROM artifacts WHERE run_id = ? ORDER BY name", (run_id,)
    )
    return [ArtifactRecord.from_row(row) for row in rows]


def fetch_tags(db: Database, run_id: int) -> list[str]:
    """Tags attached to one run."""
    rows = db.execute("SELECT tag FROM tags WHERE run_id = ? ORDER BY tag", (run_id,))
    return [str(row["tag"]) for row in rows]


def fetch_summary(db: Database, run_id: int) -> RunSummary:
    """Assemble a :class:`RunSummary` with a handful of grouped queries."""
    row = db.execute_one("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise QueryError(f"run {run_id} does not exist")
    latest = {
        str(item["key"]): float(item["value"])
        for item in db.execute(
            """
            SELECT m.key, m.value
              FROM metrics m
              JOIN (SELECT key, MAX(step) AS step FROM metrics
                     WHERE run_id = ? GROUP BY key) last
                ON last.key = m.key AND last.step = m.step
             WHERE m.run_id = ?
            """,
            (run_id, run_id),
        )
    }
    counts = {
        str(item["key"]): int(item["n"])
        for item in db.execute(
            "SELECT key, COUNT(*) AS n FROM metrics WHERE run_id = ? GROUP BY key",
            (run_id,),
        )
    }
    artifact_row = db.execute_one(
        "SELECT COUNT(*) AS n FROM artifacts WHERE run_id = ?", (run_id,)
    )
    return RunSummary(
        run=RunRecord.from_row(row),
        params=fetch_params(db, run_id),
        latest_metrics=latest,
        metric_counts=counts,
        tags=tuple(fetch_tags(db, run_id)),
        artifact_count=int(artifact_row["n"]) if artifact_row else 0,
    )


def run_detail(db: Database, run_id: int) -> dict[str, Any]:
    """Everything needed to render one run (CLI ``show`` and JSON export)."""
    summary = fetch_summary(db, run_id)
    series: dict[str, list[tuple[int, float]]] = {}
    for key in summary.metric_counts:
        series[key] = fetch_metric_series(db, run_id, key)
    return {
        "run": summary.run.to_dict(),
        "params": dict(sorted(summary.params.items())),
        "tags": list(summary.tags),
        "metrics": {key: [[step, value] for step, value in points] for key, points in series.items()},
        "artifacts": [record.to_dict() for record in fetch_artifacts(db, run_id)],
    }


def search_runs(db: Database, text: str, limit: int = 50) -> list[RunRecord]:
    """Substring search over run names and notes."""
    pattern = f"%{escape_like(str(text))}%"
    rows = db.execute(
        "SELECT * FROM runs WHERE name LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\' "
        "ORDER BY id DESC LIMIT ?",
        (pattern, pattern, normalize_limit(limit) or 50),
    )
    return [RunRecord.from_row(row) for row in rows]


def distinct_tags(db: Database) -> list[str]:
    """Every tag in the database, sorted."""
    return [str(row["tag"]) for row in db.execute("SELECT DISTINCT tag FROM tags ORDER BY tag")]


def distinct_param_keys(db: Database) -> list[str]:
    """Every parameter key in the database, sorted."""
    return [str(row["key"]) for row in db.execute("SELECT DISTINCT key FROM params ORDER BY key")]
