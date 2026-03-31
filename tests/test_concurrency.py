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
