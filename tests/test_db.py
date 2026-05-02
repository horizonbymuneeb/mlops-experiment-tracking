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


def test_transaction_commits(conn):
    conn.execute("CREATE TABLE t (v INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_transaction_rolls_back_on_error(conn):
    conn.execute("CREATE TABLE t (v INTEGER)")
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_is_locked_error():
    assert is_locked_error(sqlite3.OperationalError("database is locked"))
    assert is_locked_error(sqlite3.OperationalError("database table is locked"))
    assert not is_locked_error(sqlite3.OperationalError("no such table: x"))
    assert not is_locked_error(ValueError("locked"))
