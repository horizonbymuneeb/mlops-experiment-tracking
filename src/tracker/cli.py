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
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (separate so tests can introspect it)."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", help="path to the SQLite database (default: config.yaml)")
    common.add_argument("--config", help="path to config.yaml")

    parser = argparse.ArgumentParser(
        prog="tracker",
        description="Minimal SQLite experiment tracker",
    )
    parser.add_argument("--db", dest="global_db", help="path to the SQLite database")
    parser.add_argument("--config", dest="global_config", help="path to config.yaml")
    parser.add_argument("--json", dest="global_json", action="store_true", help="machine readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common], help="create the database and a default config")
    init.add_argument("--force", action="store_true", help="overwrite an existing config file")
    init.add_argument("--no-config", action="store_true", help="do not write config.yaml")
    init.set_defaults(func=cmd_init)

    listing = sub.add_parser("list", parents=[common], help="list runs")
    listing.add_argument("--status", action="append", help="filter by status (repeatable)")
    listing.add_argument("--tag", action="append", help="require a tag (repeatable)")
    listing.add_argument("--name", help="substring of the run name")
    listing.add_argument("--limit", type=int, default=None)
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--order", default="id", help="id|started_at|finished_at|name|status")
    listing.add_argument("--descending", action="store_true")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", parents=[common], help="show one run")
    show.add_argument("run", help="run id or name")
    show.add_argument("--metrics", action="store_true", help="include every metric point")
    show.set_defaults(func=cmd_show)

    compare = sub.add_parser("compare", parents=[common], help="compare two or more runs")
    compare.add_argument("runs", nargs="+", type=int, help="run ids")
    compare.add_argument("--metric", action="append", dest="metrics", help="limit to these metric keys")
    compare.add_argument("--direction", default="max", choices=("max", "min"))
    compare.set_defaults(func=cmd_compare)

    export = sub.add_parser("export", parents=[common], help="export runs")
    export.add_argument("--out", required=True, help="output path")
    export.add_argument(
        "--format",
        default="json",
        choices=("json", "metrics-csv", "params-csv", "summary-csv", "manifest"),
    )
    export.add_argument("--run", action="append", dest="run_ids", type=int)
    export.set_defaults(func=cmd_export)

    search = sub.add_parser("search", parents=[common], help="search run names and notes")
    search.add_argument("text")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)

    schema = sub.add_parser("schema", parents=[common], help="show the schema version and tables")
    schema.set_defaults(func=cmd_schema)

    gc = sub.add_parser("gc", parents=[common], help="delete unreferenced artifact blobs")
    gc.add_argument("--dry-run", action="store_true")
    gc.set_defaults(func=cmd_gc)

    return parser


def resolve_config(args: argparse.Namespace, *, allow_missing: bool = False) -> TrackerConfig:
    """Load config from ``--config`` or the default file, then apply ``--db``.

    ``allow_missing`` lets ``tracker init`` point at a config file that does not
    exist yet: the defaults are used with that file's directory as the base so
    the database and artifact paths land next to the config being created.
    """
    config_path = getattr(args, "config", None) or getattr(args, "global_config", None)
    candidate = Path(config_path) if config_path else Path("config.yaml")
    if config_path is not None and not candidate.is_file():
        if not allow_missing:
            raise ConfigError(f"config file not found: {candidate}")
        config = TrackerConfig.from_mapping({}, base_dir=candidate.resolve().parent)
    elif config_path is not None or candidate.is_file():
        config = load_config(candidate)
    else:
        config = TrackerConfig()
    db_override = getattr(args, "db", None) or getattr(args, "global_db", None)
    if db_override:
        from dataclasses import replace

        config = replace(
            config,
            database=replace(config.database, path=str(Path(db_override).expanduser())),
        )
    return config


def open_tracker(args: argparse.Namespace) -> Tracker:
    """Construct a ``Tracker`` for the parsed arguments."""
    return Tracker(config=resolve_config(args))


def format_table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    """Render a simple left-aligned text table with a header rule."""
    text_rows = [["" if cell is None else str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in text_rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * width for width in widths))
    for row in text_rows:
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip())
    return "\n".join(lines)
