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


def connect(
    path: str | Path,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    journal_mode: str = DEFAULT_JOURNAL_MODE,
    synchronous: str = DEFAULT_SYNCHRONOUS,
    uri: bool | None = None,
) -> sqlite3.Connection:
    """Open a configured connection.

    ``path`` may be a filesystem path, ``:memory:`` or a ``file:`` URI. URIs
    are used for the shared-cache in-memory database returned by
    :func:`memory_database`.
    """
    text = str(path)
    is_uri = text.startswith("file:") if uri is None else uri
    if not is_uri and text != ":memory:":
        Path(text).expanduser().parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None puts the driver in autocommit mode: the tracker
    # issues BEGIN/COMMIT itself so a write is never left half-applied.
    conn = sqlite3.connect(
        text, uri=is_uri, timeout=busy_timeout_ms / 1000.0, isolation_level=None
    )
    return configure_connection(
        conn,
        busy_timeout_ms=busy_timeout_ms,
        journal_mode=journal_mode,
        synchronous=synchronous,
    )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside ``BEGIN IMMEDIATE`` ... ``COMMIT``.

    ``IMMEDIATE`` takes the write lock up front, which avoids the deadlock
    class where two connections both hold a read lock and then try to upgrade.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def retry_on_locked(
    func: Callable[..., T],
    *args: Any,
    attempts: int = RETRY_ATTEMPTS,
    delay: float = RETRY_BASE_DELAY,
    backoff: float = RETRY_BACKOFF,
    **kwargs: Any,
) -> T:
    """Call ``func`` retrying with exponential backoff while the DB is locked."""
    wait = delay
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if not is_locked_error(exc) or attempt == attempts:
                raise
            last = exc
            time.sleep(wait)
            wait *= backoff
    raise DatabaseError(f"exhausted retries: {last}")  # pragma: no cover
