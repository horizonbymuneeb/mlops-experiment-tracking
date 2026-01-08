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
