"""Run lifecycle: creating runs, logging data, finishing and resuming them.

Two objects live here. ``Run`` is the handle a training script talks to, and
``Tracker`` owns the database, the artifact store and the factory methods.
Both are context managers: leaving a ``with tracker.run(...)`` block finishes
the run, and leaving it because of an exception marks the run ``failed`` and
re-raises.

State transitions are checked inside the same transaction as the write they
guard. That matters when two processes share a database: a worker that finds
the run finished while it was computing cannot slip a metric in afterwards.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from tracker.artifacts import ArtifactRef, ArtifactStore, infer_media_type
from tracker.config import TrackerConfig
from tracker.db import Database
from tracker.models import (
    RUN_STATUSES,
    TERMINAL_STATUSES,
    ArtifactRecord,
    MetricRecord,
    RunRecord,
    RunSummary,
    coerce_metric_value,
    coerce_param_value,
    decode_param_value,
    iso_now,
)
from tracker.schema import ensure_schema


class RunStateError(RuntimeError):
    """Raised when a write is not allowed in the run's current state."""


class RunNotFoundError(LookupError):
    """Raised when a run id or name does not resolve."""


def _fetch_run_row(conn, run_id: int):
    return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def _status_in(conn, run_id: int) -> str:
    row = _fetch_run_row(conn, run_id)
    if row is None:
        raise RunNotFoundError(f"run {run_id} does not exist")
    return str(row["status"])
