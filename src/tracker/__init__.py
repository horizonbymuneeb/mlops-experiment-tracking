"""A small SQLite-backed experiment tracker.

Public entry points are re-exported here so callers can do::

    from tracker import Tracker, load_config

    cfg = load_config("config.yaml")
    with Tracker(config=cfg) as tracker:
        with tracker.run("baseline", params={"lr": 1e-3}) as run:
            run.log_metric("loss", 0.42, step=0)
"""

from tracker.artifacts import ArtifactRef, ArtifactStore
from tracker.compare import (
    ParamDiff,
    RunComparison,
    align_curves,
    best_run,
    compare_runs,
    diff_params,
    normalize_direction,
)
from tracker.config import (
    ArtifactConfig,
    CliConfig,
    ConfigError,
    DatabaseConfig,
    MetricsConfig,
    RunsConfig,
    TrackerConfig,
    load_config,
    write_default_config,
)
from tracker.db import Database, DatabaseError, connect, init_database, transaction
from tracker.export import export_metrics_csv, export_runs, import_runs
from tracker.models import (
    RUN_STATUSES,
    ArtifactRecord,
    MetricRecord,
    ParamRecord,
    RunRecord,
    RunSummary,
    TagRecord,
    iso_now,
)
from tracker.query import RunFilter, query_runs, run_detail, search_runs
from tracker.run import Run, RunStateError, Tracker
from tracker.schema import SCHEMA_VERSION, ensure_schema

__all__ = [
    "ArtifactConfig",
    "ArtifactRecord",
    "ArtifactRef",
    "ArtifactStore",
    "CliConfig",
    "ConfigError",
    "Database",
    "DatabaseConfig",
    "DatabaseError",
    "MetricRecord",
    "MetricsConfig",
    "ParamDiff",
    "ParamRecord",
    "RUN_STATUSES",
    "Run",
    "RunComparison",
    "RunFilter",
    "RunRecord",
    "RunStateError",
    "RunSummary",
    "RunsConfig",
    "SCHEMA_VERSION",
    "TagRecord",
    "Tracker",
    "TrackerConfig",
    "align_curves",
    "best_run",
    "compare_runs",
    "connect",
    "diff_params",
    "ensure_schema",
    "export_metrics_csv",
    "export_runs",
    "import_runs",
    "init_database",
    "iso_now",
    "load_config",
    "normalize_direction",
    "query_runs",
    "run_detail",
    "search_runs",
    "transaction",
    "write_default_config",
]
