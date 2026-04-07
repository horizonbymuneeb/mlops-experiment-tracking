"""Filtering and read helpers over the tracker tables.

``RunFilter`` is deliberately declarative: it turns into one SQL statement with
bound parameters, so a filter object can be built by the CLI, by tests or by a
notebook and still produce the same rows. Two conventions are worth knowing:

* ``params`` compares the *encoded* value and its type, so ``epochs=10`` does
  not match a run that logged ``epochs=10.0``. Silent float/int coercion is how
  experiment queries end up wrong.
* ``metric_ranges`` matches when *any* point of that metric falls inside the
  range, which is what people mean by "runs that reached loss < 0.3".
"""
