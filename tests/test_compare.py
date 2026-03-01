"""Parameter diffs, curve alignment and best-run selection."""

from __future__ import annotations

import pytest

from tracker.compare import (
    ComparisonError,
    ParamDiff,
    RunComparison,
    aggregate_metric,
    align_curves,
    best_run,
    compare_runs,
    diff_params,
    format_comparison,
    latest_values,
    metric_table,
    normalize_direction,
    summarize_params,
)


def test_diff_params_added_removed_changed_common():
    diff = diff_params({"a": 1, "b": 2, "c": 3}, {"b": 20, "c": 3, "d": 4})
    assert diff.added == {"d": 4}
    assert diff.removed == {"a": 1}
    assert diff.changed == {"b": (2, 20)}
    assert diff.common == {"c": 3}
    assert diff.is_empty is False


def test_diff_params_identical():
    diff = diff_params({"a": 1}, {"a": 1})
    assert diff.is_empty is True
    assert diff.to_dict()["identical"] is True


def test_param_diff_to_dict_shape():
    diff = ParamDiff(left=1, right=2, changed={"lr": (0.1, 0.2)})
    payload = diff.to_dict()
    assert payload["changed"]["lr"] == {"left": 0.1, "right": 0.2}
    assert payload["left"] == 1
