"""Command line interface: init, list, show, compare, export, search, gc.

The CLI is a thin layer over ``Tracker``, ``query``, ``compare`` and ``export``
— everything it does is also reachable from Python, which is the point: the
tool should not be the only way to get data out of the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from tracker.compare import ComparisonError, compare_runs, format_comparison
from tracker.config import ConfigError, TrackerConfig, load_config, write_default_config
from tracker.db import DatabaseError
from tracker.export import (
    ExportError,
    export_json_file,
    export_metrics_csv,
    export_params_csv,
    export_summary_csv,
    write_json,
    export_manifest,
)
from tracker.query import (
    QueryError,
    RunFilter,
    count_runs,
    fetch_params,
    query_runs,
    run_detail,
    search_runs,
)
from tracker.run import RunNotFoundError, RunStateError, Tracker
from tracker.schema import SCHEMA_VERSION, describe_schema, verify_schema

DEFAULT_DB = "tracker.db"
