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
