"""Connection handling, transactions and lock retries for SQLite.

Design choice worth knowing about: the tracker never keeps a long-lived write
transaction or a shared connection object. Every mutation is one short
``BEGIN IMMEDIATE`` transaction on a connection that is opened for that
operation and closed afterwards. That is what makes the API safe to call from
several processes (``multiprocessing`` workers, parallel shells) without a lock
manager: SQLite's own writer lock plus a busy timeout does the arbitration, and
the retry wrapper covers the remaining ``database is locked`` races.
"""
