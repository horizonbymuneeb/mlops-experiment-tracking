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
