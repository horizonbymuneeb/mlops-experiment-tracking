"""Connection handling, transactions and lock retries for SQLite.

Design choice worth knowing about: the tracker never keeps a long-lived write
transaction or a shared connection object. Every mutation is one short
``BEGIN IMMEDIATE`` transaction on a connection that is opened for that
operation and closed afterwards. That is what makes the API safe to call from
several processes (``multiprocessing`` workers, parallel shells) without a lock
manager: SQLite's own writer lock plus a busy timeout does the arbitration, and
the retry wrapper covers the remaining ``database is locked`` races.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, TypeVar

T = TypeVar("T")

DEFAULT_BUSY_TIMEOUT_MS = 5000
DEFAULT_JOURNAL_MODE = "WAL"
DEFAULT_SYNCHRONOUS = "NORMAL"
RETRY_ATTEMPTS = 6
RETRY_BASE_DELAY = 0.02
RETRY_BACKOFF = 2.0
MEMORY_PREFIX = "file:tracker-mem-"


class DatabaseError(RuntimeError):
    """Raised for database level failures that are not plain SQLite errors."""


def is_locked_error(exc: BaseException) -> bool:
    """True for the SQLite errors that mean 'another writer holds the lock'."""
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def configure_connection(
    conn: sqlite3.Connection,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    journal_mode: str = DEFAULT_JOURNAL_MODE,
    synchronous: str = DEFAULT_SYNCHRONOUS,
) -> sqlite3.Connection:
    """Apply the pragmas the tracker relies on and return the connection."""
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms):d}")
    conn.execute("PRAGMA foreign_keys = ON")
    mode = journal_mode.upper()
    if mode != "MEMORY":  # an in-memory database cannot switch journal mode
        conn.execute(f"PRAGMA journal_mode = {mode}")
    conn.execute(f"PRAGMA synchronous = {synchronous.upper()}")
    return conn
