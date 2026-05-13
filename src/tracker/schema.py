"""SQLite schema definition and forward-only migrations.

The tracker owns five tables. ``runs`` is the unit of work, ``params`` holds
one typed JSON row per key, ``metrics`` is a long table with an explicit step
so curves survive out-of-order writes, ``artifacts`` references blobs by
content digest, and ``tags`` is a small many-to-many used by the query layer.

Migrations are ordered and forward-only: the applied version is stored in
SQLite's ``user_version`` pragma, each step is a list of statements executed in
one transaction, and a database newer than this code refuses to open rather
than being silently downgraded.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

SCHEMA_VERSION = 3

TABLE_NAMES = ("runs", "params", "metrics", "artifacts", "tags")

MIGRATION_1: tuple[str, ...] = (
    """
    CREATE TABLE runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'running'
            CHECK (status IN ('running', 'finished', 'failed', 'killed')),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        host TEXT,
        notes TEXT,
        resumed_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX idx_runs_name ON runs(name)",
    "CREATE INDEX idx_runs_started ON runs(started_at)",
    """
    CREATE TABLE params (
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        value_type TEXT NOT NULL,
        PRIMARY KEY (run_id, key)
    )
    """,
    """
    CREATE TABLE metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        step INTEGER NOT NULL,
        value REAL NOT NULL,
        recorded_at TEXT NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX idx_metrics_run_key_step ON metrics(run_id, key, step)",
    "CREATE INDEX idx_metrics_key ON metrics(key)",
)

MIGRATION_2: tuple[str, ...] = (
    """
    CREATE TABLE artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        digest TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        media_type TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_artifacts_digest ON artifacts(digest)",
    "CREATE UNIQUE INDEX idx_artifacts_run_name ON artifacts(run_id, name)",
)

MIGRATION_3: tuple[str, ...] = (
    """
    CREATE TABLE tags (
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        tag TEXT NOT NULL,
        PRIMARY KEY (run_id, tag)
    )
    """,
    "CREATE INDEX idx_tags_tag ON tags(tag)",
    "CREATE INDEX idx_runs_status ON runs(status)",
)

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: MIGRATION_1,
    2: MIGRATION_2,
    3: MIGRATION_3,
}


class MigrationError(RuntimeError):
    """Raised when a database cannot be brought to ``SCHEMA_VERSION``."""


def current_version(conn: sqlite3.Connection) -> int:
    """Return the schema version recorded in ``PRAGMA user_version``."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def set_version(conn: sqlite3.Connection, version: int) -> None:
    """Write ``version`` into ``PRAGMA user_version``.

    The pragma does not accept bound parameters, so the value is interpolated
    after an integer check.
    """
    if not isinstance(version, int) or version < 0:
        raise MigrationError(f"invalid schema version {version!r}")
    conn.execute(f"PRAGMA user_version = {version:d}")
