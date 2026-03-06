"""JSON and CSV export, plus the matching importer.

The JSON payload is a self-describing document (``format``/``version``/``runs``)
rather than a bare list, so an old export can be recognised and either imported
or rejected instead of being parsed into nonsense. Import allocates new run ids
and keeps params, tags, metric points and artifact *metadata*; blobs themselves
are not embedded — an export is a description of runs, not a backup of the
artifact store.
"""
