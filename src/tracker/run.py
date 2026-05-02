"""Run lifecycle: creating runs, logging data, finishing and resuming them.

Two objects live here. ``Run`` is the handle a training script talks to, and
``Tracker`` owns the database, the artifact store and the factory methods.
Both are context managers: leaving a ``with tracker.run(...)`` block finishes
the run, and leaving it because of an exception marks the run ``failed`` and
re-raises.

State transitions are checked inside the same transaction as the write they
guard. That matters when two processes share a database: a worker that finds
the run finished while it was computing cannot slip a metric in afterwards.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from tracker.artifacts import ArtifactRef, ArtifactStore, infer_media_type
from tracker.config import TrackerConfig
from tracker.db import Database
from tracker.models import (
    RUN_STATUSES,
    TERMINAL_STATUSES,
    ArtifactRecord,
    MetricRecord,
    RunRecord,
    RunSummary,
    coerce_metric_value,
    coerce_param_value,
    decode_param_value,
    iso_now,
)
from tracker.schema import ensure_schema


class RunStateError(RuntimeError):
    """Raised when a write is not allowed in the run's current state."""


class RunNotFoundError(LookupError):
    """Raised when a run id or name does not resolve."""


def _fetch_run_row(conn, run_id: int):
    return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def _status_in(conn, run_id: int) -> str:
    row = _fetch_run_row(conn, run_id)
    if row is None:
        raise RunNotFoundError(f"run {run_id} does not exist")
    return str(row["status"])


class Run:
    """A handle on one row of ``runs`` plus its params, metrics and artifacts."""

    def __init__(self, tracker: "Tracker", record: RunRecord) -> None:
        self._tracker = tracker
        self._record = record

    def __repr__(self) -> str:
        return f"<Run id={self.id} name={self.name!r} status={self.status}>"

    @property
    def id(self) -> int:
        return self._record.id

    @property
    def name(self) -> str:
        return self._record.name

    @property
    def status(self) -> str:
        return self._record.status

    @property
    def started_at(self) -> str:
        return self._record.started_at

    @property
    def finished_at(self) -> str | None:
        return self._record.finished_at

    @property
    def notes(self) -> str | None:
        return self._record.notes

    @property
    def is_finished(self) -> bool:
        return self._record.status in TERMINAL_STATUSES

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock duration of the run, or ``None`` while it is open."""
        return self._record.duration_seconds

    @property
    def tracker(self) -> "Tracker":
        return self._tracker

    def refresh(self) -> RunRecord:
        """Reload the row from the database and return the fresh record."""
        record = self._tracker._load_record(self.id)
        self._record = record
        return record

    def _guard_open(self, conn, action: str) -> None:
        status = _status_in(conn, self.id)
        if status in TERMINAL_STATUSES:
            raise RunStateError(
                f"cannot {action} on run {self.id}: run is {status} "
                f"(call resume_run() to reopen it)"
            )

    def log_param(self, key: str, value: Any) -> None:
        """Record one hyper-parameter. Re-logging a key overwrites it."""
        if not key:
            raise ValueError("param key must not be empty")
        encoded, type_name = coerce_param_value(value)
        with self._tracker.db.transaction() as conn:
            self._guard_open(conn, "log a param")
            conn.execute(
                """
                INSERT INTO params (run_id, key, value, value_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, key) DO UPDATE SET
                    value = excluded.value,
                    value_type = excluded.value_type
                """,
                (self.id, str(key), encoded, type_name),
            )

    def log_params(self, params: Mapping[str, Any]) -> int:
        """Record several params in one transaction; returns how many were written."""
        if not params:
            return 0
        encoded = [(self.id, str(k), *coerce_param_value(v)) for k, v in params.items()]
        with self._tracker.db.transaction() as conn:
            self._guard_open(conn, "log params")
            conn.executemany(
                """
                INSERT INTO params (run_id, key, value, value_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, key) DO UPDATE SET
                    value = excluded.value,
                    value_type = excluded.value_type
                """,
                encoded,
            )
        return len(encoded)

    def log_metric(self, key: str, value: Any, step: int | None = None) -> int:
        """Record one metric point; returns the step it was stored at.

        ``step=None`` means "next step for this key", computed as
        ``max(step) + 1`` inside the write transaction, so concurrent workers
        appending to the same key cannot produce duplicate steps.
        """
        if not key:
            raise ValueError("metric key must not be empty")
        numeric = coerce_metric_value(value)
        with self._tracker.db.transaction() as conn:
            self._guard_open(conn, "log a metric")
            resolved = self._resolve_step(conn, str(key), step)
            conn.execute(
                """
                INSERT INTO metrics (run_id, key, step, value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, key, step) DO UPDATE SET
                    value = excluded.value,
                    recorded_at = excluded.recorded_at
                """,
                (self.id, str(key), resolved, numeric, iso_now()),
            )
        return resolved

    def log_metrics(self, metrics: Mapping[str, Any], step: int | None = None) -> int:
        """Record a batch of metrics at one step; returns the row count."""
        if not metrics:
            return 0
        limit = self._tracker.config.metrics.max_batch
        if len(metrics) > limit:
            raise ValueError(
                f"batch of {len(metrics)} metrics exceeds metrics.max_batch={limit}"
            )
        prepared = [(str(k), coerce_metric_value(v)) for k, v in metrics.items()]
        now = iso_now()
        with self._tracker.db.transaction() as conn:
            self._guard_open(conn, "log metrics")
            rows = []
            for key, value in prepared:
                resolved = self._resolve_step(conn, key, step)
                rows.append((self.id, key, resolved, value, now))
            conn.executemany(
                """
                INSERT INTO metrics (run_id, key, step, value, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, key, step) DO UPDATE SET
                    value = excluded.value,
                    recorded_at = excluded.recorded_at
                """,
                rows,
            )
        return len(rows)

    def _resolve_step(self, conn, key: str, step: int | None) -> int:
        if step is not None:
            if not isinstance(step, int) or isinstance(step, bool) or step < 0:
                raise ValueError(f"step must be a non-negative int, got {step!r}")
            return step
        if not self._tracker.config.metrics.auto_step:
            raise ValueError("step is required when metrics.auto_step is false")
        row = conn.execute(
            "SELECT MAX(step) FROM metrics WHERE run_id = ? AND key = ?",
            (self.id, key),
        ).fetchone()
        current = row[0] if row and row[0] is not None else -1
        return int(current) + 1

    def log_artifact(
        self,
        source: str | Path | bytes,
        name: str | None = None,
        media_type: str | None = None,
    ) -> ArtifactRecord:
        """Store a blob and link it to this run.

        ``source`` may be bytes or a path. The blob is content-addressed, so
        logging the same bytes under two names stores one file on disk.
        """
        if isinstance(source, bytes):
            ref = self._tracker.store.put_bytes(source, media_type)
            display = name or "artifact.bin"
        else:
            path = Path(source)
            ref = self._tracker.store.put_file(path, media_type)
            display = name or path.name
        resolved_media = media_type or ref.media_type or infer_media_type(display)
        now = iso_now()
        with self._tracker.db.transaction() as conn:
            self._guard_open(conn, "log an artifact")
            conn.execute(
                """
                INSERT INTO artifacts (run_id, name, digest, size_bytes, media_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, name) DO UPDATE SET
                    digest = excluded.digest,
                    size_bytes = excluded.size_bytes,
                    media_type = excluded.media_type,
                    created_at = excluded.created_at
                """,
                (self.id, display, ref.digest, ref.size_bytes, resolved_media, now),
            )
            row = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND name = ?", (self.id, display)
            ).fetchone()
        return ArtifactRecord.from_row(row)

    def add_tag(self, tag: str) -> bool:
        """Attach a tag; returns False when it was already present."""
        text = str(tag).strip()
        if not text:
            raise ValueError("tag must not be empty")
        with self._tracker.db.transaction() as conn:
            self._guard_open(conn, "add a tag")
            cursor = conn.execute(
                "INSERT OR IGNORE INTO tags (run_id, tag) VALUES (?, ?)", (self.id, text)
            )
            return cursor.rowcount > 0

    def remove_tag(self, tag: str) -> bool:
        """Detach a tag; returns False when it was not attached."""
        with self._tracker.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM tags WHERE run_id = ? AND tag = ?", (self.id, str(tag))
            )
            return cursor.rowcount > 0

    def set_notes(self, notes: str) -> None:
        """Replace the run's free-form notes."""
        with self._tracker.db.transaction() as conn:
            conn.execute("UPDATE runs SET notes = ? WHERE id = ?", (str(notes), self.id))
        self.refresh()

    def finish(self, status: str = "finished") -> RunRecord:
        """Close the run with a terminal status."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(
                f"finish() needs one of {sorted(TERMINAL_STATUSES)}, got {status!r}"
            )
        now = iso_now()
        with self._tracker.db.transaction() as conn:
            current = _status_in(conn, self.id)
            if current in TERMINAL_STATUSES:
                raise RunStateError(f"run {self.id} is already {current}")
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                (status, now, self.id),
            )
        return self.refresh()

    def fail(self, reason: str | None = None) -> RunRecord:
        """Close the run as failed, optionally appending the reason to notes."""
        if reason:
            existing = self.notes or ""
            combined = f"{existing}\n{reason}".strip() if existing else str(reason)
            self.set_notes(combined)
        return self.finish("failed")

    def reopen(self) -> RunRecord:
        """Reopen a finished run so more data can be appended."""
        if not self._tracker.config.runs.allow_reopen:
            raise RunStateError("reopening runs is disabled by runs.allow_reopen")
        with self._tracker.db.transaction() as conn:
            current = _status_in(conn, self.id)
            if current not in TERMINAL_STATUSES:
                raise RunStateError(f"run {self.id} is already {current}")
            conn.execute(
                """
                UPDATE runs
                   SET status = 'running',
                       finished_at = NULL,
                       resumed_count = resumed_count + 1
                 WHERE id = ?
                """,
                (self.id,),
            )
        return self.refresh()

    def params(self) -> dict[str, Any]:
        """All params as a plain ``{key: value}`` mapping."""
        rows = self._tracker.db.execute(
            "SELECT key, value, value_type FROM params WHERE run_id = ? ORDER BY key",
            (self.id,),
        )
        return {row["key"]: decode_param_value(row["value"], row["value_type"]) for row in rows}

    def param(self, key: str, default: Any = None) -> Any:
        """One param value, or ``default`` when it is not set."""
        return self.params().get(key, default)

    def metrics(self, key: str | None = None) -> list[MetricRecord]:
        """Metric rows ordered by key then step."""
        if key is None:
            rows = self._tracker.db.execute(
                "SELECT * FROM metrics WHERE run_id = ? ORDER BY key, step", (self.id,)
            )
        else:
            rows = self._tracker.db.execute(
                "SELECT * FROM metrics WHERE run_id = ? AND key = ? ORDER BY step",
                (self.id, str(key)),
            )
        return [MetricRecord.from_row(row) for row in rows]

    def metric_series(self, key: str) -> list[tuple[int, float]]:
        """``[(step, value), ...]`` for one metric key."""
        return [(record.step, record.value) for record in self.metrics(key)]

    def metric_keys(self) -> list[str]:
        """Distinct metric keys logged for this run."""
        rows = self._tracker.db.execute(
            "SELECT DISTINCT key FROM metrics WHERE run_id = ? ORDER BY key", (self.id,)
        )
        return [str(row["key"]) for row in rows]

    def latest_metrics(self) -> dict[str, float]:
        """Last value of every metric key."""
        rows = self._tracker.db.execute(
            """
            SELECT m.key, m.value
              FROM metrics m
              JOIN (SELECT key, MAX(step) AS step
                      FROM metrics WHERE run_id = ? GROUP BY key) last
                ON last.key = m.key AND last.step = m.step
             WHERE m.run_id = ?
             ORDER BY m.key
            """,
            (self.id, self.id),
        )
        return {str(row["key"]): float(row["value"]) for row in rows}

    def artifacts(self) -> list[ArtifactRecord]:
        """Artifacts linked to this run, ordered by name."""
        rows = self._tracker.db.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY name", (self.id,)
        )
        return [ArtifactRecord.from_row(row) for row in rows]

    def artifact_bytes(self, name: str) -> bytes:
        """Read a stored artifact back by its display name."""
        for record in self.artifacts():
            if record.name == name:
                return self._tracker.store.read_bytes(record.digest)
        raise RunNotFoundError(f"run {self.id} has no artifact named {name!r}")

    def tags(self) -> list[str]:
        """Tags attached to this run, sorted."""
        rows = self._tracker.db.execute(
            "SELECT tag FROM tags WHERE run_id = ? ORDER BY tag", (self.id,)
        )
        return [str(row["tag"]) for row in rows]

    def summary(self) -> RunSummary:
        """Everything about the run in one immutable object."""
        counts = {
            str(row["key"]): int(row["n"])
            for row in self._tracker.db.execute(
                "SELECT key, COUNT(*) AS n FROM metrics WHERE run_id = ? GROUP BY key",
                (self.id,),
            )
        }
        return RunSummary(
            run=self.refresh(),
            params=self.params(),
            latest_metrics=self.latest_metrics(),
            metric_counts=counts,
            tags=tuple(self.tags()),
            artifact_count=len(self.artifacts()),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the run and its data (used by ``tracker show --json``)."""
        payload = self.summary().to_dict()
        payload["metrics"] = [record.to_dict() for record in self.metrics()]
        payload["artifacts"] = [record.to_dict() for record in self.artifacts()]
        return payload

    def __enter__(self) -> "Run":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            if not self.is_finished:
                self.finish("finished")
        else:
            if not self.is_finished:
                try:
                    self.fail(f"{exc_type.__name__}: {exc}")
                except RunStateError:
                    pass


class Tracker:
    """Owns a database and an artifact store; creates and loads runs."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        config: TrackerConfig | None = None,
        artifact_dir: str | Path | None = None,
        init: bool = True,
    ) -> None:
        self.config = config or TrackerConfig()
        resolved_db = Path(db_path) if db_path is not None else self.config.db_path()
        resolved_artifacts = (
            Path(artifact_dir) if artifact_dir is not None else self.config.artifact_dir()
        )
        self.db = Database(
            resolved_db,
            busy_timeout_ms=self.config.database.busy_timeout_ms,
            journal_mode=self.config.database.journal_mode,
            synchronous=self.config.database.synchronous,
        )
        self.store = ArtifactStore(
            resolved_artifacts,
            hash_algorithm=self.config.artifacts.hash_algorithm,
            verify_on_read=self.config.artifacts.verify_on_read,
        )
        if init:
            with self.db.session() as conn:
                ensure_schema(conn)

    def __repr__(self) -> str:
        return f"<Tracker db={self.db.path} artifacts={self.store.root}>"

    def _load_record(self, run_id: int) -> RunRecord:
        row = self.db.execute_one("SELECT * FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise RunNotFoundError(f"run {run_id} does not exist")
        return RunRecord.from_row(row)

    def _resolve(self, ref: int | str) -> int:
        if isinstance(ref, bool):
            raise TypeError("run reference must be an id or a name")
        if isinstance(ref, int):
            return ref
        if not isinstance(ref, str) or not ref.strip():
            raise RunNotFoundError(f"invalid run reference {ref!r}")
        text = ref.strip()
        if text.isdigit():
            return int(text)
        row = self.db.execute_one(
            "SELECT id FROM runs WHERE name = ? ORDER BY id DESC LIMIT 1", (text,)
        )
        if row is None:
            raise RunNotFoundError(f"no run named {text!r}")
        return int(row["id"])

    def start_run(
        self,
        name: str,
        params: Mapping[str, Any] | None = None,
        tags: Iterable[str] | None = None,
        notes: str | None = None,
    ) -> Run:
        """Create a run in ``running`` state, optionally with params and tags."""
        if not name or not str(name).strip():
            raise ValueError("run name must not be empty")
        prepared = [(str(k), *coerce_param_value(v)) for k, v in (params or {}).items()]
        tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
        now = iso_now()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO runs (name, status, started_at, host, notes)
                VALUES (?, 'running', ?, ?, ?)
                """,
                (
                    str(name),
                    now,
                    socket.gethostname(),
                    notes if notes is not None else self.config.runs.default_notes,
                ),
            )
            run_id = int(cursor.lastrowid)
            if prepared:
                conn.executemany(
                    "INSERT INTO params (run_id, key, value, value_type) VALUES (?, ?, ?, ?)",
                    [(run_id, *item) for item in prepared],
                )
            if tag_list:
                conn.executemany(
                    "INSERT OR IGNORE INTO tags (run_id, tag) VALUES (?, ?)",
                    [(run_id, tag) for tag in tag_list],
                )
        return Run(self, self._load_record(run_id))

    def resume_run(self, ref: int | str) -> Run:
        """Return a run handle, reopening it when it is already finished.

        Resuming a run that is still ``running`` (for example from a second
        process that crashed earlier) is a no-op apart from returning the
        handle: the row is already writable.
        """
        run = self.get_run(ref)
        if not run.is_finished:
            return run
        run.reopen()
        return run

    def get_run(self, ref: int | str) -> Run:
        """Load a run by id or by name (the newest run wins on name clashes)."""
        return Run(self, self._load_record(self._resolve(ref)))

    def find_runs(self, name: str | None = None, limit: int | None = None) -> list[Run]:
        """Simple lookup used by the CLI; ``query.py`` is the richer interface."""
        sql = "SELECT * FROM runs"
        params: list[Any] = []
        if name is not None:
            sql += " WHERE name = ?"
            params.append(str(name))
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [Run(self, RunRecord.from_row(row)) for row in self.db.execute(sql, params)]

    @contextmanager
    def run(
        self,
        name: str,
        params: Mapping[str, Any] | None = None,
        tags: Iterable[str] | None = None,
    ) -> Iterator[Run]:
        """Context manager around :meth:`start_run` and ``Run.__exit__``."""
        handle = self.start_run(name, params=params, tags=tags)
        try:
            yield handle
        except BaseException as exc:
            if not handle.is_finished:
                try:
                    handle.fail(f"{type(exc).__name__}: {exc}")
                except RunStateError:
                    pass
            raise
        else:
            if not handle.is_finished:
                handle.finish("finished")

    def finish_run(self, ref: int | str, status: str = "finished") -> RunRecord:
        """Finish a run by reference."""
        return self.get_run(ref).finish(status)

    def delete_run(self, ref: int | str) -> bool:
        """Delete a run and its rows (artifacts blobs are left for gc)."""
        run_id = self._resolve(ref)
        with self.db.transaction() as conn:
            cursor = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            return cursor.rowcount > 0

    def referenced_digests(self) -> set[str]:
        """Every artifact digest still referenced by a run."""
        rows = self.db.execute("SELECT DISTINCT digest FROM artifacts")
        return {str(row["digest"]) for row in rows}

    def gc_artifacts(self, *, dry_run: bool = False) -> dict[str, object]:
        """Delete blobs no run references any more."""
        return self.store.garbage_collect(self.referenced_digests(), dry_run=dry_run)

    def counts(self) -> dict[str, int]:
        """Row counts per table (for ``tracker show`` / tests)."""
        return self.db.table_counts()

    def close(self) -> None:
        """Release resources held by the tracker (none are cached)."""
        self.db.close()

    def __enter__(self) -> "Tracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
