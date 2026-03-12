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


def test_compare_runs_best_per_metric(db, seeded):
    comparison = compare_runs(db, [seeded[0].id, seeded[1].id], direction="min")
    assert comparison.metric_keys == ("loss",)
    assert comparison.best["loss"] == seeded[1].id
    assert comparison.latest[seeded[0].id]["loss"] == 0.6
    assert comparison.best_run_id("loss") == seeded[1].id
    assert comparison.best_run_id("nope") is None


def test_compare_runs_direction_max(db, seeded):
    comparison = compare_runs(db, [seeded[0].id, seeded[1].id], direction="max")
    assert comparison.best["loss"] == seeded[0].id


def test_compare_runs_param_diff_only_for_two(db, seeded):
    two = compare_runs(db, [seeded[0].id, seeded[1].id])
    assert two.param_diff is not None
    assert two.param_diff.added == {"width": 64}
    assert two.param_diff.changed == {"lr": (0.1, 0.01)}
    three = compare_runs(db, [seeded[0].id, seeded[1].id, seeded[2].id])
    assert three.param_diff is None


def test_compare_runs_aligned_curve(db, seeded):
    comparison = compare_runs(db, [seeded[0].id, seeded[1].id])
    rows = comparison.aligned("loss")
    assert len(rows) == 3
    assert rows[0][seeded[0].id] == 0.9
    assert rows[2][seeded[1].id] == 0.4


def test_compare_runs_to_dict(db, seeded):
    payload = compare_runs(db, [seeded[0].id, seeded[1].id]).to_dict()
    assert payload["run_ids"] == [seeded[0].id, seeded[1].id]
    assert payload["direction"] == "max"
    assert payload["metric_keys"] == ["loss"]
    assert str(seeded[0].id) in payload["latest"]


def test_compare_runs_metric_key_filter(db, seeded):
    comparison = compare_runs(db, [seeded[0].id, seeded[1].id], metric_keys=["loss"])
    assert comparison.metric_keys == ("loss",)


def test_compare_runs_validation(db, seeded):
    with pytest.raises(ComparisonError, match="at least one"):
        compare_runs(db, [])
    with pytest.raises(ComparisonError, match="integer ids"):
        compare_runs(db, ["baseline"])
    with pytest.raises(ComparisonError, match="unique"):
        compare_runs(db, [seeded[0].id, seeded[0].id])
    with pytest.raises(ComparisonError, match="does not exist"):
        compare_runs(db, [9999])


def test_metric_table(db, seeded):
    comparison = compare_runs(db, [seeded[0].id, seeded[1].id], direction="min")
    table = metric_table(comparison)
    assert table[0] == ["metric", f"run {seeded[0].id}", f"run {seeded[1].id}", "best"]
    assert table[1][0] == "loss"
    assert table[1][-1] == str(seeded[1].id)


def test_format_comparison_mentions_params_and_metrics(db, seeded):
    text = format_comparison(compare_runs(db, [seeded[0].id, seeded[1].id]))
    assert "params (run" in text
    assert "~ lr" in text
    assert "loss" in text
    assert "metrics (latest value)" in text


def test_format_comparison_identical_params(db, tracker):
    left = tracker.start_run("l", params={"lr": 0.1})
    right = tracker.start_run("r", params={"lr": 0.1})
    text = format_comparison(compare_runs(db, [left.id, right.id]))
    assert "identical" in text


def test_aggregate_metric(db, seeded):
    ids = [seeded[0].id, seeded[1].id]
    assert aggregate_metric(db, ids, "loss", "mean") == pytest.approx(0.5)
    assert aggregate_metric(db, ids, "loss", "min") == pytest.approx(0.4)
    assert aggregate_metric(db, ids, "loss", "max") == pytest.approx(0.6)
    assert aggregate_metric(db, ids, "loss", "median") == pytest.approx(0.5)
    assert aggregate_metric(db, ids, "missing", "mean") is None
    with pytest.raises(ComparisonError, match="reducer"):
        aggregate_metric(db, ids, "loss", "sum")


def test_aggregate_metric_median_even_and_odd(db, tracker):
    for value in (1.0, 2.0, 9.0):
        run = tracker.start_run(f"m{value}")
        run.log_metric("score", value, step=0)
        run.finish()
    ids = [1, 2, 3]
    assert aggregate_metric(db, ids, "score", "median") == 2.0
    fourth = tracker.start_run("m4")
    fourth.log_metric("score", 4.0, step=0)
    assert aggregate_metric(db, [1, 2, 3, 4], "score", "median") == pytest.approx(3.0)
