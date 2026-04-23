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
