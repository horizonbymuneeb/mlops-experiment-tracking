"""Connection setup, transactions and lock retries."""

from __future__ import annotations

import sqlite3

import pytest

from tracker.db import (
    Database,
    DatabaseError,
    connect,
    execute_with_retry,
    init_database,
    is_locked_error,
    memory_database,
    readonly_connect,
    retry_on_locked,
    transaction,
)


@pytest.fixture()
def conn(tmp_path):
    connection = connect(tmp_path / "db.sqlite")
    yield connection
    connection.close()


def test_connect_configures_the_connection(conn):
    assert conn.row_factory is sqlite3.Row
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_connect_creates_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "c.db"
    connection = connect(path)
    connection.close()
    assert path.exists()
