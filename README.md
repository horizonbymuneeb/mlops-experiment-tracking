# mlops-experiment-tracking

A small experiment tracker that keeps every run, parameter, metric point and
artifact pointer in a single SQLite file. It exists because the usual answer to
"track my experiments" is a server plus a database plus a web UI, and for a
laptop, a CI job or a shared box that is a lot of moving parts. Here a run is
one row, a metric point is one row, and an artifact is a content hash — so
logging is a `BEGIN IMMEDIATE` away, the whole history is one file you can copy,
and comparing two runs is a SQL query rather than a service call.

The library is the product; the CLI (`tracker`) is a thin shell over it. Both
write the same schema, so a script can start a run and `tracker list` can read
it while the script is still training.

## What is in the box

| Module | Job |
|---|---|
| `src/tracker/config.py` | Dataclass config, YAML loading, per-key type validation, path resolution relative to the config file |
| `src/tracker/schema.py` | Table DDL and the forward-only migration chain (`user_version` 1→2→3), schema introspection and verification |
| `src/tracker/db.py` | Connection factory with the pragmas this schema needs, `BEGIN IMMEDIATE` transactions, `database is locked` retries, shared-cache in-memory DB |
| `src/tracker/models.py` | `RunRecord`/`ParamRecord`/`MetricRecord`/`ArtifactRecord`/`TagRecord`/`RunSummary`, typed param encoding, metric validation, UTC timestamps |
| `src/tracker/artifacts.py` | Content-addressed blob store: streaming hashing, atomic writes, dedup, integrity verify, garbage collection |
| `src/tracker/run.py` | `Run` and `Tracker`: start/log/finish/reopen, state guards, context managers, artifact linking, cascade delete |
| `src/tracker/query.py` | `RunFilter` → SQL, ordering/pagination, search, and the read helpers the CLI and exports use |
| `src/tracker/compare.py` | Param diffs, metric curves aligned on the union of steps, best-run selection with direction and tie-break |
| `src/tracker/export.py` | Versioned JSON export, three CSV layouts, artifact manifest, and the importer that rebuilds runs |
| `src/tracker/cli.py` | `init`, `list`, `show`, `compare`, `export`, `search`, `schema`, `gc` |

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -e .

tracker init                      # creates tracker.db + config.yaml
```

Log a run from Python:

```python
from tracker import Tracker, load_config

config = load_config("config.yaml")
tracker = Tracker(config=config)

with tracker.run("baseline", params={"lr": 1e-3, "epochs": 3}, tags=["nightly"]) as run:
    for step in range(3):
        run.log_metrics({"loss": 0.9 ** (step + 1), "acc": 0.5 + 0.1 * step})
    run.log_artifact("checkpoints/baseline.pt")
```

Or without a context manager, if the run has to outlive the process:

```python
run = tracker.start_run("long-job", params={"shards": 8})
run.log_metric("loss", 0.42, step=0)
run.finish()
# later, from another process:
tracker.resume_run("long-job").log_metric("loss", 0.31, step=1)
```

Read it back:

```bash
tracker list --status finished
tracker show baseline --metrics
tracker compare 1 2 --direction min
tracker export --out runs.json
tracker export --out metrics.csv --format metrics-csv
tracker gc --dry-run
```

## Design notes

**SQLite with WAL, not a JSON log or a server.** An append-only file is easy to
write and painful to query: filtering by param or finding the best run means
parsing everything. SQLite gives indexes, transactions and SQL for one file and
zero processes. WAL mode is what makes the "read while training writes" case
work — readers keep their snapshot and never block the writer. The cost is that
the file must live on a filesystem with working POSIX locks (so: not on NFS),
and write throughput is one writer at a time.

**Concurrency without a lock manager.** The rule is that no connection is kept
open between calls and no write transaction spans application work: each
mutation is a short `BEGIN IMMEDIATE` … `COMMIT` on a fresh connection, with
`busy_timeout` plus exponential-backoff retries for the remaining races. That is
why `log_metric(step=None)` computes `max(step)+1` *inside* the write
transaction — two workers appending to the same key cannot both pick the same
step. `tests/test_concurrency.py` forks three workers writing 20 points each into
one run and asserts all 60 rows landed with unique steps.

**Resumable runs are a state machine, not a special mode.** `runs.status` is
`running | finished | failed | killed` and `finished_at`/`resumed_count` carry the
history. `resume_run()` is a no-op on a running run and reopens a finished one,
which is what makes "crashed job, continue where it stopped" the same code path
as "add a few more points tomorrow". Every write re-reads the status inside its
own transaction, so a worker that finishes a step after another process closed
the run gets a `RunStateError` instead of silently appending to a closed run.

**Artifacts are addressed by content, not by name.** The blob path is derived
from its SHA-256 (`objects/ab/cdef…`) and the database stores only digest, name
and size. Logging the same checkpoint from ten runs stores one file. Writes go to
a temp file in the same directory and are `os.replace`d into place, so a crash
never leaves a half-written blob; `gc` deletes digests no row references.

**Params are typed JSON, and comparison is type-strict.** `epochs: 10` and
`epochs: 10.0` are different rows, and `RunFilter(params={"epochs": 10})` will not
match the float one. Silent coercion is how two runs that differ get reported as
identical.

## Tests

```bash
make test
# or
python -m pytest -q
```

**255 tests** across 12 files, running in about 3.3 s on CPU with no network
access and no GPU:

- `test_config.py` — defaults, YAML loading, override merging, path resolution,
  every validation error (unknown section/key, wrong type, bool-as-int, bad
  journal mode, refusing to clobber an existing config).
- `test_schema.py` — fresh creation, idempotent `ensure_schema`, migrating a v1
  and a v2 database, refusing a newer schema, cascade deletes, the status CHECK
  constraint, and the exact column list per table.
- `test_db.py` — pragmas, commit/rollback, retry-on-locked (succeeds after two
  failures, gives up after N, never swallows other errors), shared in-memory
  database, read-only connections.
- `test_models.py` — param type round-trips (`int`/`float`/`bool`/`None`/`str`/
  `json`), rejection of NaN/inf and unsupported types, timestamp round-trips,
  duration maths, record conversion.
- `test_artifacts.py` — known SHA-256 vectors, chunk-size-independent hashing,
  dedup flags, sharded paths, corruption detection, garbage collection with and
  without `dry_run`.
- `test_run.py` — logging and overwriting, auto vs explicit steps, batch limits,
  state errors after `finish`, reopen/resume counters, context managers
  finishing or failing the run, cascade delete, gc after delete.
- `test_query.py` — every filter (status, name, tags, typed param equality,
  param and metric ranges), ordering, pagination, LIKE escaping, and the read
  helpers.
- `test_compare.py` — param diffs, curve alignment on the union of steps,
  latest-value-by-step, best run with both directions and tie-breaks, table and
  text rendering, aggregation reducers.
- `test_export.py` — payload shape, JSON/CSV files with real row counts, the
  artifact manifest, import creating new ids with identical params/metrics, and
  rejection of wrong format/version/malformed documents.
- `test_cli.py` — every subcommand through `main()` against a temporary config,
  including `--json` output and the error exit codes.
- `test_concurrency.py` — three forked processes logging into one run, parallel
  run creation, and a finished run rejecting writes from a worker.

## Limitations

- Single machine, single file: no remote server, no multi-writer cluster, and the
  database must not sit on NFS/SMB where POSIX locks are unreliable.
- One writer at a time (SQLite). Fine for a handful of workers, not for a fleet.
- No authentication or access control; anyone with the file has the data.
- The artifact store is local-filesystem only — no S3/GCS backend — and `export`
  carries artifact *metadata*, not blob contents.
- Metric curves are stored point-for-point with no downsampling; a run with
  millions of points will make the SQLite file large and `show` slow.
- No retention policy: deleting runs frees rows but blobs stay until `tracker gc`.
- `compare` reports the final value of each metric, not the best-ever value, so
  it will not pick a run that peaked early and then overfit.
