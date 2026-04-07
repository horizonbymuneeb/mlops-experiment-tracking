"""Record types shared by the storage, query and export layers.

Params are stored as JSON text plus a type tag so that ``lr: 1e-3`` comes back
as a float and ``epochs: 10`` comes back as an int, instead of everything
collapsing to a string the way a naive ``TEXT`` column would. Metrics are
floats only and must be finite; a NaN in a metric curve breaks comparisons and
JSON export, so it is rejected at the boundary.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

RUN_STATUSES = ("running", "finished", "failed", "killed")
TERMINAL_STATUSES = frozenset({"finished", "failed", "killed"})
PARAM_TYPES = ("null", "bool", "int", "float", "str", "json")

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now() -> datetime:
    """Timezone-aware UTC now, truncated to microseconds."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return format_timestamp(utc_now())


def format_timestamp(moment: datetime) -> str:
    """Serialise a datetime in the tracker's canonical UTC form."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Parse a timestamp produced by :func:`format_timestamp`.

    A few other ISO shapes are accepted (``+00:00`` offsets, no microseconds)
    so timestamps written by older versions or by hand still load.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid timestamp {value!r}")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def coerce_param_value(value: Any) -> tuple[str, str]:
    """Encode a parameter into ``(json_text, type_name)``.

    Lists and dicts are allowed and stored as ``json``; anything else is a bug
    in the caller and raises ``TypeError`` rather than being stringified.
    """
    if value is None:
        return "null", "null"
    if isinstance(value, bool):
        return json.dumps(value), "bool"
    if isinstance(value, int):
        return json.dumps(value), "int"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"parameter value must be finite, got {value!r}")
        return json.dumps(value), "float"
    if isinstance(value, str):
        return json.dumps(value), "str"
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, sort_keys=True), "json"
    raise TypeError(f"unsupported parameter type: {type(value).__name__}")


def decode_param_value(json_text: str, type_name: str) -> Any:
    """Inverse of :func:`coerce_param_value`."""
    if type_name not in PARAM_TYPES:
        raise ValueError(f"unknown parameter type {type_name!r}")
    value = json.loads(json_text)
    if type_name == "null":
        return None
    if type_name == "bool":
        return bool(value)
    if type_name == "int":
        return int(value)
    if type_name == "float":
        return float(value)
    return value


def coerce_metric_value(value: Any) -> float:
    """Validate and normalise a metric value.

    ``bool`` is rejected on purpose: logging ``True`` as a metric almost always
    means the caller wanted a param or a tag.
    """
    if isinstance(value, bool):
        raise TypeError("metric value must be numeric, not bool")
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"metric value must be finite, got {value!r}")
        return numeric
    raise TypeError(f"metric value must be numeric, got {type(value).__name__}")


def row_to_dict(row: sqlite3.Row | Mapping[str, Any] | None) -> dict[str, Any]:
    """Convert a SQLite row (or mapping) to a plain dict."""
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    return dict(row)


@dataclass(frozen=True)
class RunRecord:
    """One row of ``runs``."""

    id: int
    name: str
    status: str
    started_at: str
    finished_at: str | None = None
    host: str | None = None
    notes: str | None = None
    resumed_count: int = 0

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {self.status!r}")

    @property
    def is_finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock duration, or ``None`` while the run is still open."""
        if not self.finished_at:
            return None
        delta = parse_timestamp(self.finished_at) - parse_timestamp(self.started_at)
        return delta.total_seconds()

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any]) -> "RunRecord":
        data = row_to_dict(row)
        return cls(
            id=int(data["id"]),
            name=str(data["name"]),
            status=str(data["status"]),
            started_at=str(data["started_at"]),
            finished_at=data.get("finished_at"),
            host=data.get("host"),
            notes=data.get("notes"),
            resumed_count=int(data.get("resumed_count") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "host": self.host,
            "notes": self.notes,
            "resumed_count": self.resumed_count,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class ParamRecord:
    """One ``(run_id, key)`` parameter entry."""

    run_id: int
    key: str
    value: str
    value_type: str

    @property
    def python_value(self) -> Any:
        return decode_param_value(self.value, self.value_type)

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any]) -> "ParamRecord":
        data = row_to_dict(row)
        return cls(
            run_id=int(data["run_id"]),
            key=str(data["key"]),
            value=str(data["value"]),
            value_type=str(data["value_type"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.python_value, "type": self.value_type}


@dataclass(frozen=True)
class MetricRecord:
    """One point on a metric curve."""

    id: int
    run_id: int
    key: str
    step: int
    value: float
    recorded_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any]) -> "MetricRecord":
        data = row_to_dict(row)
        return cls(
            id=int(data["id"]),
            run_id=int(data["run_id"]),
            key=str(data["key"]),
            step=int(data["step"]),
            value=float(data["value"]),
            recorded_at=str(data["recorded_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "step": self.step,
            "value": self.value,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class ArtifactRecord:
    """A named pointer to a content-addressed blob."""

    id: int
    run_id: int
    name: str
    digest: str
    size_bytes: int
    media_type: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any]) -> "ArtifactRecord":
        data = row_to_dict(row)
        return cls(
            id=int(data["id"]),
            run_id=int(data["run_id"]),
            name=str(data["name"]),
            digest=str(data["digest"]),
            size_bytes=int(data["size_bytes"]),
            media_type=data.get("media_type"),
            created_at=str(data["created_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "name": self.name,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class TagRecord:
    """A free-form label attached to a run."""

    run_id: int
    tag: str

    @classmethod
    def from_row(cls, row: sqlite3.Row | Mapping[str, Any]) -> "TagRecord":
        data = row_to_dict(row)
        return cls(run_id=int(data["run_id"]), tag=str(data["tag"]))


@dataclass(frozen=True)
class RunSummary:
    """A run plus everything needed to render or export it."""

    run: RunRecord
    params: dict[str, Any] = field(default_factory=dict)
    latest_metrics: dict[str, float] = field(default_factory=dict)
    metric_counts: dict[str, int] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    artifact_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "params": dict(sorted(self.params.items())),
            "latest_metrics": dict(sorted(self.latest_metrics.items())),
            "metric_counts": dict(sorted(self.metric_counts.items())),
            "tags": list(self.tags),
            "artifact_count": self.artifact_count,
        }
