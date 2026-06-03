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
