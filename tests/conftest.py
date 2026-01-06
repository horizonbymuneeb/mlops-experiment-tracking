"""Shared fixtures for the tracker test suite."""

from __future__ import annotations

import pytest

from tracker import Tracker
from tracker.artifacts import ArtifactStore
from tracker.db import init_database
