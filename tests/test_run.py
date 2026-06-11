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


def test_log_artifact_bytes_and_read_back(tracker):
    run = tracker.start_run("r")
    record = run.log_artifact(b"hello world", name="notes.txt")
    assert record.name == "notes.txt"
    assert record.size_bytes == 11
    assert record.media_type == "text/plain"
    assert run.artifact_bytes("notes.txt") == b"hello world"
    assert run.artifacts()[0].digest == record.digest


def test_log_artifact_file_dedups_on_disk(tracker, tmp_path):
    source = tmp_path / "model.bin"
    source.write_bytes(b"weights" * 100)
    run_a = tracker.start_run("a")
    run_b = tracker.start_run("b")
    ref_a = run_a.log_artifact(source)
    ref_b = run_b.log_artifact(source)
    assert ref_a.digest == ref_b.digest
    assert ref_a.name == "model.bin"
    assert len(tracker.store.list_objects()) == 1
    assert run_b.artifact_bytes("model.bin") == source.read_bytes()


def test_log_artifact_overwrites_same_name(tracker):
    run = tracker.start_run("r")
    run.log_artifact(b"first", name="x.txt")
    run.log_artifact(b"second", name="x.txt")
    artifacts = run.artifacts()
    assert len(artifacts) == 1
    assert run.artifact_bytes("x.txt") == b"second"


def test_missing_artifact_name_raises(tracker):
    run = tracker.start_run("r")
    with pytest.raises(RunNotFoundError):
        run.artifact_bytes("nope")


def test_tags_are_idempotent(tracker):
    run = tracker.start_run("r")
    assert run.add_tag("nightly") is True
    assert run.add_tag("nightly") is False
    assert run.tags() == ["nightly"]
    assert run.remove_tag("nightly") is True
    assert run.remove_tag("nightly") is False
    assert run.tags() == []


def test_add_tag_rejects_blank(tracker):
    run = tracker.start_run("r")
    with pytest.raises(ValueError, match="tag"):
        run.add_tag("  ")


def test_finish_sets_terminal_status(tracker):
    run = tracker.start_run("r")
    record = run.finish("finished")
    assert record.status == "finished"
    assert record.finished_at is not None
    assert run.status == "finished"
    assert run.duration_seconds is not None


def test_finish_rejects_unknown_status(tracker):
    run = tracker.start_run("r")
    with pytest.raises(ValueError, match="finish"):
        run.finish("done")


def test_double_finish_raises(tracker):
    run = tracker.start_run("r")
    run.finish()
    with pytest.raises(RunStateError, match="already finished"):
        run.finish()


def test_fail_appends_reason_to_notes(tracker):
    run = tracker.start_run("r")
    run.fail("diverged at step 10")
    assert run.status == "failed"
    assert "diverged at step 10" in (run.notes or "")


def test_fail_appends_to_existing_notes(tracker):
    run = tracker.start_run("r", notes="first")
    run.fail("second")
    assert run.notes == "first\nsecond"


def test_reopen_clears_finished_at_and_counts(tracker):
    run = tracker.start_run("r")
    run.log_metric("loss", 0.5)
    run.finish()
    record = run.reopen()
    assert record.status == "running"
    assert record.finished_at is None
    assert record.resumed_count == 1
    assert run.log_metric("loss", 0.4) == 1


def test_reopen_running_run_raises(tracker):
    run = tracker.start_run("r")
    with pytest.raises(RunStateError, match="already running"):
        run.reopen()


def test_reopen_respects_config(tmp_path):
    from tracker.config import TrackerConfig
    from tracker.db import Database
    from tracker.schema import ensure_schema

    config = TrackerConfig.from_mapping({"runs": {"allow_reopen": False, "default_notes": ""}})
    tracker = Tracker(config=config, db_path=tmp_path / "t.db", artifact_dir=tmp_path / "art")
    run = tracker.start_run("r")
    run.finish()
    with pytest.raises(RunStateError, match="allow_reopen"):
        run.reopen()


def test_resume_run_reopens_finished(tracker):
    run = tracker.start_run("r")
    run.finish()
    resumed = tracker.resume_run(run.id)
    assert resumed.status == "running"
    assert resumed.refresh().resumed_count == 1


def test_resume_run_running_is_noop(tracker):
    run = tracker.start_run("r")
    resumed = tracker.resume_run(run.id)
    assert resumed.id == run.id
    assert resumed.refresh().resumed_count == 0


def test_context_manager_finishes_on_success(tracker):
    with tracker.run("ok") as run:
        run.log_metric("loss", 0.1)
        run_id = run.id
    assert tracker.get_run(run_id).status == "finished"


def test_context_manager_marks_failed_on_exception(tracker):
    with pytest.raises(ZeroDivisionError):
        with tracker.run("bad") as run:
            run_id = run.id
            1 / 0
    record = tracker.get_run(run_id).refresh()
    assert record.status == "failed"
    assert "ZeroDivisionError" in (record.notes or "")


def test_context_manager_does_not_double_finish(tracker):
    with tracker.run("early") as run:
        run.finish("killed")
    assert tracker.get_run(run.id).status == "killed"


def test_get_run_by_name_and_missing(tracker):
    tracker.start_run("named")
    assert tracker.get_run("named").name == "named"
    with pytest.raises(RunNotFoundError, match="no run named"):
        tracker.get_run("ghost")
    with pytest.raises(RunNotFoundError, match="does not exist"):
        tracker.get_run(9999)


def test_get_run_rejects_bool(tracker):
    with pytest.raises(TypeError):
        tracker.get_run(True)


def test_set_notes(tracker):
    run = tracker.start_run("r")
    run.set_notes("updated")
    assert run.notes == "updated"
    assert tracker.get_run(run.id).notes == "updated"


def test_summary_and_to_dict(tracker):
    run = tracker.start_run("r", params={"lr": 0.1})
    run.log_metric("loss", 0.5, step=0)
    run.log_metric("loss", 0.4, step=1)
    run.log_artifact(b"x", name="x.bin")
    summary = run.summary()
    assert summary.latest_metrics == {"loss": 0.4}
    assert summary.metric_counts == {"loss": 2}
    assert summary.artifact_count == 1
    payload = run.to_dict()
    assert len(payload["metrics"]) == 2
    assert payload["artifacts"][0]["name"] == "x.bin"


def test_delete_run_cascades(tracker):
    run = tracker.start_run("r", params={"lr": 0.1}, tags=["t"])
    run.log_metric("loss", 0.5)
    assert tracker.delete_run(run.id) is True
    assert tracker.delete_run(run.id) is False
    counts = tracker.counts()
    assert counts["runs"] == 0
    assert counts["params"] == 0 and counts["metrics"] == 0 and counts["tags"] == 0


def test_gc_artifacts_after_delete(tracker):
    run = tracker.start_run("r")
    record = run.log_artifact(b"orphan me")
    assert tracker.store.exists(record.digest) is True
    tracker.delete_run(run.id)
    result = tracker.gc_artifacts()
    assert result["removed"] == [record.digest]
    assert tracker.store.exists(record.digest) is False


def test_gc_artifacts_keeps_live_blobs(tracker):
    run = tracker.start_run("r")
    record = run.log_artifact(b"keep me")
    result = tracker.gc_artifacts()
    assert result["removed_count"] == 0
    assert tracker.store.exists(record.digest) is True


def test_find_runs_and_limits(tracker):
    tracker.start_run("a")
    tracker.start_run("b")
    tracker.start_run("a")
    assert [run.name for run in tracker.find_runs(name="a")] == ["a", "a"]
    assert len(tracker.find_runs()) == 3
    assert len(tracker.find_runs(limit=1)) == 1


def test_finish_run_by_reference(tracker):
    run = tracker.start_run("r")
    record = tracker.finish_run("r", "killed")
    assert record.status == "killed"
    assert run.refresh().status == "killed"


def test_tracker_context_manager(tracker):
    with Tracker(db_path=tracker.db.path, artifact_dir=tracker.store.root) as inner:
        inner.start_run("nested")
    assert tracker.counts()["runs"] == 1


def test_run_repr(tracker):
    run = tracker.start_run("repr-run")
    assert "repr-run" in repr(run)
    assert "running" in repr(run)
