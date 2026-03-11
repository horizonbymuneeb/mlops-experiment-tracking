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
