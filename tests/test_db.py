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


def test_retry_on_locked_eventually_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "done"

    assert retry_on_locked(flaky, attempts=5, delay=0) == "done"
    assert calls["n"] == 3


def test_retry_on_locked_gives_up():
    def always_locked():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        retry_on_locked(always_locked, attempts=3, delay=0)


def test_retry_does_not_swallow_other_errors():
    def broken():
        raise sqlite3.OperationalError("no such table: missing")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        retry_on_locked(broken, attempts=3, delay=0)


def test_execute_with_retry_returns_cursor(conn):
    conn.execute("CREATE TABLE t (v INTEGER)")
    cursor = execute_with_retry(conn, "INSERT INTO t VALUES (?)", (7,))
    assert cursor.rowcount == 1
    assert conn.execute("SELECT v FROM t").fetchone()[0] == 7


def test_database_execute_helpers(tmp_path):
    db = init_database(tmp_path / "helpers.db")
    db.execute_write("INSERT INTO runs (name, status, started_at) VALUES (?, 'running', ?)", ("a", "2026-01-01T00:00:00.000000Z"))
    rows = db.execute("SELECT name FROM runs")
    assert [row["name"] for row in rows] == ["a"]
    assert db.execute_one("SELECT name FROM runs")["name"] == "a"
    assert db.execute_one("SELECT name FROM runs WHERE id = 999") is None
    assert db.scalar("SELECT COUNT(*) FROM runs") == 1
    assert db.scalar("SELECT id FROM runs WHERE id = 999", default=42) == 42


def test_database_executemany(tmp_path):
    db = init_database(tmp_path / "many.db")
    db.execute_write("INSERT INTO runs (name, status, started_at) VALUES ('a', 'running', '2026-01-01T00:00:00.000000Z')")
    rows = [(1, "lr", "0.1", "float"), (1, "epochs", "3", "int")]
    assert db.executemany("INSERT INTO params (run_id, key, value, value_type) VALUES (?, ?, ?, ?)", rows) == 2
    assert db.executemany("INSERT INTO params (run_id, key, value, value_type) VALUES (?, ?, ?, ?)", []) == 0
    assert db.scalar("SELECT COUNT(*) FROM params") == 2


def test_database_write_transaction_is_atomic(tmp_path):
    db = init_database(tmp_path / "atomic.db")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO runs (name, status, started_at) VALUES ('a', 'running', '2026-01-01T00:00:00.000000Z')")
            conn.execute("INSERT INTO runs (name, status, started_at) VALUES ('b', 'nonsense', '2026-01-01T00:00:00.000000Z')")
    assert db.scalar("SELECT COUNT(*) FROM runs") == 0


def test_database_path_and_memory_flags(tmp_path):
    db = Database(tmp_path / "x.db")
    assert db.path == tmp_path / "x.db"
    assert db.is_memory is False
    mem = memory_database()
    assert mem.is_memory is True
    mem.close()


def test_memory_database_is_shared_between_connections():
    mem = memory_database()
    with mem.session() as conn:
        conn.execute("CREATE TABLE shared (v INTEGER)")
        conn.execute("INSERT INTO shared VALUES (5)")
    with mem.session() as conn:
        assert conn.execute("SELECT v FROM shared").fetchone()[0] == 5
    mem.close()


def test_readonly_connect_reads_but_cannot_write(tmp_path):
    db = init_database(tmp_path / "ro.db")
    db.execute_write("INSERT INTO runs (name, status, started_at) VALUES ('a', 'running', '2026-01-01T00:00:00.000000Z')")
    ro = readonly_connect(tmp_path / "ro.db")
    assert ro.execute("SELECT name FROM runs").fetchone()[0] == "a"
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO runs (name, status, started_at) VALUES ('b', 'running', '2026-01-01T00:00:00.000000Z')")
    ro.close()


def test_readonly_connect_missing_file(tmp_path):
    with pytest.raises(DatabaseError, match="does not exist"):
        readonly_connect(tmp_path / "nope.db")


def test_integrity_check_and_counts(tmp_path):
    db = init_database(tmp_path / "integrity.db")
    assert db.integrity_check() == "ok"
    assert db.table_counts()["runs"] == 0
