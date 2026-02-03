"""Comparing runs: parameter diffs, aligned metric curves, best-run selection.

The two non-obvious rules here:

* Curves are aligned on the union of steps, not on row order. Two runs that log
  the same metric at different steps still line up, and a missing point stays
  ``None`` instead of silently borrowing a neighbour's value.
* "Best" is computed from the *latest* value of a metric, with a direction
  (``max`` for accuracy, ``min`` for loss) and a deterministic tie-break on the
  lowest run id. Comparing runs of different lengths on their best-ever value
  hides overfitting, so the default is the final value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from tracker.db import Database
from tracker.models import RunRecord, row_to_dict
from tracker.query import (
    QueryError,
    fetch_metric_series,
    fetch_params,
    fetch_summary,
    fetch_metric_keys,
)

DIRECTIONS = ("max", "min")


class ComparisonError(ValueError):
    """Raised when a comparison request is not well formed."""


def normalize_direction(direction: str) -> str:
    """Validate a direction string, returning the canonical lower-case form."""
    if not isinstance(direction, str):
        raise ComparisonError(f"direction must be a string, got {type(direction).__name__}")
    text = direction.strip().lower()
    if text not in DIRECTIONS:
        raise ComparisonError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    return text
