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


def test_align_curves_uses_union_of_steps():
    rows = align_curves({"a": [(0, 1.0), (2, 3.0)], "b": [(1, 2.0), (2, 4.0)]})
    assert [row["step"] for row in rows] == [0, 1, 2]
    assert rows[0] == {"step": 0, "a": 1.0, "b": None}
    assert rows[1] == {"step": 1, "a": None, "b": 2.0}
    assert rows[2] == {"step": 2, "a": 3.0, "b": 4.0}


def test_align_curves_empty():
    assert align_curves({}) == []
    assert align_curves({"a": []}) == []


def test_latest_values_uses_highest_step_not_list_order():
    assert latest_values({"a": [(5, 1.0), (1, 9.0)]}) == {"a": 1.0}
    assert latest_values({"a": []}) == {}


@pytest.mark.parametrize(
    "values,direction,expected",
    [
        ({1: 0.5, 2: 0.9, 3: 0.7}, "max", 2),
        ({1: 0.5, 2: 0.9, 3: 0.7}, "min", 1),
        ({2: 0.9, 1: 0.9}, "max", 1),
        ({}, "max", None),
        ({7: -1.0, 8: -2.0}, "min", 8),
    ],
)
def test_best_run(values, direction, expected):
    assert best_run(values, direction) == expected


def test_best_run_ties_pick_lowest_id():
    assert best_run({9: 1.0, 3: 1.0, 7: 1.0}, "min") == 3


def test_normalize_direction():
    assert normalize_direction("MAX") == "max"
    assert normalize_direction(" min ") == "min"
    with pytest.raises(ComparisonError, match="direction"):
        normalize_direction("up")
    with pytest.raises(ComparisonError):
        normalize_direction(1)
