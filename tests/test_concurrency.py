"""Multi-process safety: two writers appending to the same database."""

from __future__ import annotations

import multiprocessing as mp
import os

import pytest

from tracker.run import Tracker
