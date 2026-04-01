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
