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


def apply_migration(conn: sqlite3.Connection, version: int) -> None:
    """Execute one migration step inside a transaction and bump the version.

    The caller is responsible for the surrounding transaction when several
    steps are applied together; this function only guarantees that a failing
    statement leaves the version untouched.
    """
    statements = MIGRATIONS.get(version)
    if statements is None:
        raise MigrationError(f"no migration defined for version {version}")
    for statement in statements:
        conn.execute(statement)
    set_version(conn, version)


def ensure_schema(conn: sqlite3.Connection) -> int:
    """Create or upgrade the schema; return the version now in place.

    Raises ``MigrationError`` if the file was written by a newer version of the
    code, or if an intermediate version is missing from ``MIGRATIONS``.
    """
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise MigrationError(
            f"database schema v{version} is newer than this code (v{SCHEMA_VERSION})"
        )
    if version == SCHEMA_VERSION:
        return version
    conn.execute("BEGIN IMMEDIATE")
    try:
        for step in range(version + 1, SCHEMA_VERSION + 1):
            if step not in MIGRATIONS:
                raise MigrationError(f"missing migration for version {step}")
            apply_migration(conn, step)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return SCHEMA_VERSION


def table_names(conn: sqlite3.Connection) -> set[str]:
    """Names of the user tables that currently exist."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def index_names(conn: sqlite3.Connection) -> set[str]:
    """Names of all indexes, including the implicit ones SQLite creates."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row[0] for row in rows}


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    """True when ``name`` is a table in this database."""
    return name in table_names(conn)


def column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    """Column names of ``table`` in declaration order."""
    if table not in TABLE_NAMES:
        raise MigrationError(f"unknown table {table!r}")
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def describe_schema(conn: sqlite3.Connection) -> dict[str, list[dict[str, object]]]:
    """Introspect every tracker table into plain dictionaries.

    Used by ``tracker show --schema`` and by the tests that assert migrations
    produced the expected columns.
    """
    out: dict[str, list[dict[str, object]]] = {}
    for table in TABLE_NAMES:
        if not has_table(conn, table):
            out[table] = []
            continue
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        out[table] = [
            {
                "name": row[1],
                "type": row[2],
                "notnull": bool(row[3]),
                "default": row[4],
                "primary_key": bool(row[5]),
            }
            for row in rows
        ]
    return out
