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


@dataclass(frozen=True)
class ParamDiff:
    """Difference between the params of two runs."""

    left: int
    right: int
    added: dict[str, Any] = field(default_factory=dict)
    removed: dict[str, Any] = field(default_factory=dict)
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)
    common: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when both runs were configured identically."""
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "added": dict(sorted(self.added.items())),
            "removed": dict(sorted(self.removed.items())),
            "changed": {key: {"left": pair[0], "right": pair[1]} for key, pair in sorted(self.changed.items())},
            "common": dict(sorted(self.common.items())),
            "identical": self.is_empty,
        }


@dataclass(frozen=True)
class RunComparison:
    """A snapshot of several runs, ready to print or serialise."""

    run_ids: tuple[int, ...]
    params: dict[int, dict[str, Any]]
    metrics: dict[int, dict[str, list[tuple[int, float]]]]
    latest: dict[int, dict[str, float]]
    best: dict[str, int]
    direction: str = "max"
    param_diff: ParamDiff | None = None

    @property
    def metric_keys(self) -> tuple[str, ...]:
        """Every metric key present in at least one run, sorted."""
        keys: set[str] = set()
        for per_run in self.metrics.values():
            keys.update(per_run)
        return tuple(sorted(keys))

    def aligned(self, key: str) -> list[dict[str, Any]]:
        """Curve of ``key`` aligned across runs (see :func:`align_curves`)."""
        curves = {
            run_id: per_run.get(key, []) for run_id, per_run in self.metrics.items()
        }
        return align_curves(curves)

    def best_run_id(self, key: str) -> int | None:
        """The run considered best for ``key`` under this comparison's direction."""
        return self.best.get(key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_ids": list(self.run_ids),
            "direction": self.direction,
            "params": {str(k): dict(sorted(v.items())) for k, v in sorted(self.params.items())},
            "latest": {str(k): dict(sorted(v.items())) for k, v in sorted(self.latest.items())},
            "best": {key: run_id for key, run_id in sorted(self.best.items())},
            "metric_keys": list(self.metric_keys),
            "param_diff": self.param_diff.to_dict() if self.param_diff else None,
        }


def diff_params(left: Mapping[str, Any], right: Mapping[str, Any]) -> ParamDiff:
    """Diff two param mappings from the perspective of ``left`` → ``right``."""
    left_keys = set(left)
    right_keys = set(right)
    added = {key: right[key] for key in sorted(right_keys - left_keys)}
    removed = {key: left[key] for key in sorted(left_keys - right_keys)}
    changed = {
        key: (left[key], right[key])
        for key in sorted(left_keys & right_keys)
        if left[key] != right[key]
    }
    common = {
        key: left[key] for key in sorted(left_keys & right_keys) if left[key] == right[key]
    }
    return ParamDiff(left=0, right=0, added=added, removed=removed, changed=changed, common=common)
