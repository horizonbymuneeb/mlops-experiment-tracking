"""Multi-process safety: two writers appending to the same database."""

from __future__ import annotations

import multiprocessing as mp
import os

import pytest

from tracker.run import Tracker

WORKERS = 3
POINTS_PER_WORKER = 20


def _log_metrics(db_path: str, artifact_dir: str, run_id: int, worker: int) -> int:
    tracker = Tracker(db_path=db_path, artifact_dir=artifact_dir)
    run = tracker.get_run(run_id)
    for index in range(POINTS_PER_WORKER):
        run.log_metric("loss", 1.0 - index / 100.0, step=worker * 1000 + index)
    return run_id


def _create_run(db_path: str, artifact_dir: str, name: str) -> int:
    tracker = Tracker(db_path=db_path, artifact_dir=artifact_dir)
    run = tracker.start_run(name, params={"worker": os.getpid()})
    run.log_metric("score", 0.5, step=0)
    return run.id


@pytest.fixture()
def paths(tmp_path):
    return str(tmp_path / "shared.db"), str(tmp_path / "artifacts")


def test_parallel_metric_writes_all_land(paths):
    db_path, artifact_dir = paths
    tracker = Tracker(db_path=db_path, artifact_dir=artifact_dir)
    run = tracker.start_run("shared")
    ctx = mp.get_context("fork")
    with ctx.Pool(WORKERS) as pool:
        pool.starmap(
            _log_metrics,
            [(db_path, artifact_dir, run.id, worker) for worker in range(WORKERS)],
        )
    count = tracker.db.scalar("SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run.id,))
    assert count == WORKERS * POINTS_PER_WORKER
    steps = [step for step, _ in run.metric_series("loss")]
    assert len(steps) == len(set(steps)), "steps must stay unique across processes"


def test_parallel_run_creation(paths):
    db_path, artifact_dir = paths
    Tracker(db_path=db_path, artifact_dir=artifact_dir)
    ctx = mp.get_context("fork")
    with ctx.Pool(WORKERS) as pool:
        ids = pool.starmap(
            _create_run,
            [(db_path, artifact_dir, f"w{worker}") for worker in range(WORKERS)],
        )
    tracker = Tracker(db_path=db_path, artifact_dir=artifact_dir)
    assert len(set(ids)) == WORKERS
    assert tracker.counts()["runs"] == WORKERS
    assert tracker.counts()["params"] == WORKERS


def test_worker_cannot_write_to_a_finished_run(paths):
    db_path, artifact_dir = paths
    tracker = Tracker(db_path=db_path, artifact_dir=artifact_dir)
    run = tracker.start_run("closing")
    ctx = mp.get_context("fork")
    with ctx.Pool(1) as pool:
        pool.apply_async(_log_metrics, (db_path, artifact_dir, run.id, 0))
    run.finish()
    from tracker.run import RunStateError

    with pytest.raises(RunStateError):
        run.log_metric("loss", 0.1)
