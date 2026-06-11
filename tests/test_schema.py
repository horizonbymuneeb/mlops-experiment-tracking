"""Schema creation and forward-only migrations."""

from __future__ import annotations

import sqlite3

import pytest

from tracker.db import connect, init_database
from tracker.schema import (
    MIGRATION_1,
    MIGRATIONS,
    SCHEMA_VERSION,
    TABLE_NAMES,
    MigrationError,
    apply_migration,
    column_names,
    current_version,
    describe_schema,
    drop_all,
    ensure_schema,
    has_table,
    index_names,
    set_version,
    statements_for,
    table_counts,
    table_names,
    verify_schema,
)


@pytest.fixture()
def conn(tmp_path):
    connection = connect(tmp_path / "schema.db")
    yield connection
    connection.close()


def test_fresh_database_gets_all_tables(conn):
    version = ensure_schema(conn)
    assert version == SCHEMA_VERSION == 3
    assert table_names(conn) >= set(TABLE_NAMES)
    assert current_version(conn) == 3


def test_ensure_schema_is_idempotent(conn):
    ensure_schema(conn)
    ensure_schema(conn)
    assert current_version(conn) == SCHEMA_VERSION
    assert len(verify_schema(conn)) == 0


def test_columns_match_the_documented_shape(conn):
    ensure_schema(conn)
    assert column_names(conn, "runs") == [
        "id", "name", "status", "started_at", "finished_at", "host", "notes", "resumed_count"
    ]
    assert "value_type" in column_names(conn, "params")
    assert "step" in column_names(conn, "metrics")
    assert "digest" in column_names(conn, "artifacts")


def test_indexes_are_created(conn):
    ensure_schema(conn)
    indexes = index_names(conn)
    assert "idx_metrics_run_key_step" in indexes
    assert "idx_artifacts_digest" in indexes
    assert "idx_tags_tag" in indexes


def test_migrates_a_v1_database(tmp_path):
    connection = connect(tmp_path / "v1.db")
    for statement in MIGRATION_1:
        connection.execute(statement)
    set_version(connection, 1)
    assert not has_table(connection, "artifacts")
    ensure_schema(connection)
    assert current_version(connection) == 3
    assert has_table(connection, "artifacts") and has_table(connection, "tags")
    connection.close()


def test_migrates_a_v2_database(tmp_path):
    connection = connect(tmp_path / "v2.db")
    for version in (1, 2):
        for statement in MIGRATIONS[version]:
            connection.execute(statement)
    set_version(connection, 2)
    ensure_schema(connection)
    assert current_version(connection) == 3
    assert has_table(connection, "tags")
    connection.close()


def test_refuses_a_newer_database(tmp_path):
    connection = connect(tmp_path / "future.db")
    ensure_schema(connection)
    set_version(connection, SCHEMA_VERSION + 1)
    with pytest.raises(MigrationError, match="newer than this code"):
        ensure_schema(connection)
    connection.close()


def test_apply_migration_unknown_version(conn):
    with pytest.raises(MigrationError, match="no migration defined"):
        apply_migration(conn, 99)


def test_set_version_rejects_bad_values(conn):
    with pytest.raises(MigrationError):
        set_version(conn, -1)
    with pytest.raises(MigrationError):
        set_version(conn, "three")


def test_verify_schema_reports_missing_table(conn):
    ensure_schema(conn)
    conn.execute("DROP TABLE tags")
    problems = verify_schema(conn)
    assert any("missing table tags" in problem for problem in problems)


def test_verify_schema_reports_version_mismatch(conn):
    ensure_schema(conn)
    set_version(conn, 1)
    problems = verify_schema(conn)
    assert any("schema version" in problem for problem in problems)


def test_describe_schema_lists_columns(conn):
    ensure_schema(conn)
    described = describe_schema(conn)
    assert set(described) == set(TABLE_NAMES)
    runs_columns = {column["name"]: column for column in described["runs"]}
    assert runs_columns["id"]["primary_key"] is True
    assert runs_columns["name"]["notnull"] is True


def test_table_counts_start_at_zero_and_track_rows(conn):
    ensure_schema(conn)
    assert table_counts(conn) == {name: 0 for name in TABLE_NAMES}
    conn.execute(
        "INSERT INTO runs (name, status, started_at) VALUES ('a', 'running', '2026-01-01T00:00:00.000000Z')"
    )
    assert table_counts(conn)["runs"] == 1


def test_drop_all_resets_the_database(conn):
    ensure_schema(conn)
    drop_all(conn)
    assert current_version(conn) == 0
    assert not (table_names(conn) & set(TABLE_NAMES))
