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
