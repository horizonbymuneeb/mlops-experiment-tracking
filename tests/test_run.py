"""Run lifecycle: logging, finishing, resuming and context managers."""

from __future__ import annotations

import pytest

from tracker.models import TERMINAL_STATUSES
from tracker.run import RunNotFoundError, RunStateError, Tracker


def test_start_run_defaults(tracker):
    run = tracker.start_run("baseline")
    assert run.id == 1
    assert run.name == "baseline"
    assert run.status == "running"
    assert run.finished_at is None
    assert run.started_at.endswith("Z")
    assert tracker.counts()["runs"] == 1


def test_start_run_rejects_empty_name(tracker):
    with pytest.raises(ValueError, match="name must not be empty"):
        tracker.start_run("   ")


def test_start_run_with_params_tags_and_notes(tracker):
    run = tracker.start_run(
        "configured", params={"lr": 0.1, "epochs": 3, "amp": True}, tags=["a", "b"], notes="hello"
    )
    assert run.params() == {"lr": 0.1, "epochs": 3, "amp": True}
    assert run.tags() == ["a", "b"]
    assert run.notes == "hello"


def test_log_param_overwrites(tracker):
    run = tracker.start_run("r")
    run.log_param("lr", 0.1)
    run.log_param("lr", 0.2)
    assert run.params() == {"lr": 0.2}


def test_log_param_rejects_empty_key(tracker):
    run = tracker.start_run("r")
    with pytest.raises(ValueError, match="param key"):
        run.log_param("", 1)


def test_log_params_returns_count_and_is_atomic(tracker):
    run = tracker.start_run("r")
    assert run.log_params({"a": 1, "b": "x"}) == 2
    assert run.log_params({}) == 0
    assert run.params() == {"a": 1, "b": "x"}


def test_log_param_after_finish_raises(tracker):
    run = tracker.start_run("r")
    run.finish()
    with pytest.raises(RunStateError, match="cannot log a param"):
        run.log_param("lr", 0.1)


def test_log_metric_auto_step(tracker):
    run = tracker.start_run("r")
    assert run.log_metric("loss", 0.9) == 0
    assert run.log_metric("loss", 0.8) == 1
    assert run.log_metric("loss", 0.7) == 2
    assert run.metric_series("loss") == [(0, 0.9), (1, 0.8), (2, 0.7)]


def test_auto_step_is_per_key(tracker):
    run = tracker.start_run("r")
    run.log_metric("loss", 0.5)
    run.log_metric("loss", 0.4)
    assert run.log_metric("acc", 0.9) == 0


def test_log_metric_explicit_step_and_overwrite(tracker):
    run = tracker.start_run("r")
    assert run.log_metric("loss", 1.0, step=5) == 5
    run.log_metric("loss", 0.1, step=5)
    assert run.metric_series("loss") == [(5, 0.1)]
    assert run.log_metric("loss", 0.05) == 6


def test_log_metric_rejects_bad_step(tracker):
    run = tracker.start_run("r")
    with pytest.raises(ValueError, match="non-negative int"):
        run.log_metric("loss", 1.0, step=-1)
    with pytest.raises(ValueError, match="non-negative int"):
        run.log_metric("loss", 1.0, step=True)


def test_log_metric_rejects_bad_values(tracker):
    run = tracker.start_run("r")
    with pytest.raises(TypeError):
        run.log_metric("loss", "high")
    with pytest.raises(ValueError, match="finite"):
        run.log_metric("loss", float("nan"))
    with pytest.raises(ValueError, match="metric key"):
        run.log_metric("", 1.0)


def test_log_metrics_batch(tracker):
    run = tracker.start_run("r")
    assert run.log_metrics({"loss": 0.5, "acc": 0.9}, step=3) == 2
    assert run.latest_metrics() == {"acc": 0.9, "loss": 0.5}
    assert run.log_metrics({}) == 0


def test_log_metrics_batch_limit(tracker):
    run = tracker.start_run("r")
    too_many = {f"m{i}": float(i) for i in range(501)}
    with pytest.raises(ValueError, match="max_batch"):
        run.log_metrics(too_many)


def test_log_metrics_auto_step_advances(tracker):
    run = tracker.start_run("r")
    run.log_metrics({"loss": 0.5})
    run.log_metrics({"loss": 0.4})
    assert run.metric_series("loss") == [(0, 0.5), (1, 0.4)]
