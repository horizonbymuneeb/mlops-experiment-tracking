"""Command line interface: init, list, show, compare, export, search, gc.

The CLI is a thin layer over ``Tracker``, ``query``, ``compare`` and ``export``
— everything it does is also reachable from Python, which is the point: the
tool should not be the only way to get data out of the database.
"""
