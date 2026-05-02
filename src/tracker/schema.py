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
