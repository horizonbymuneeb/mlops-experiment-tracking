"""Shared fixtures for the tracker test suite."""

from __future__ import annotations

import pytest

from tracker import Tracker
from tracker.artifacts import ArtifactStore
from tracker.db import init_database


@pytest.fixture()
def tracker(tmp_path):
    """A tracker backed by a throwaway SQLite file and artifact directory."""
    instance = Tracker(
        db_path=tmp_path / "tracker.db", artifact_dir=tmp_path / "artifacts"
    )
    yield instance
    instance.close()


@pytest.fixture()
def db(tracker):
    """The tracker's database wrapper."""
    return tracker.db


@pytest.fixture()
def store(tmp_path) -> ArtifactStore:
    """A standalone artifact store rooted in a temporary directory."""
    return ArtifactStore(tmp_path / "store")


@pytest.fixture()
def seeded(tracker):
    """Three runs with different params, metrics and tags."""
    specs = [
        ("baseline", {"lr": 0.1, "epochs": 2}, ["nightly"], {"loss": [0.9, 0.7, 0.6]}),
        ("wider", {"lr": 0.01, "epochs": 2, "width": 64}, ["nightly", "wide"], {"loss": [0.8, 0.5, 0.4]}),
        ("failed-run", {"lr": 0.1, "epochs": 5}, [], {"loss": [1.2, 1.1]}),
    ]
    runs = []
    for name, params, tags, metrics in specs:
        run = tracker.start_run(name, params=params, tags=tags)
        for key, values in metrics.items():
            for step, value in enumerate(values):
                run.log_metric(key, value, step=step)
        runs.append(run)
    runs[2].finish("failed")
    for run in runs[:2]:
        run.finish("finished")
    return runs


@pytest.fixture()
def memory_db():
    """An in-memory database initialised with the tracker schema."""
    instance = init_database(":memory:")
    yield instance
    instance.close()
