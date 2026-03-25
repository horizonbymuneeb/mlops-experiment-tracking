"""Record types shared by the storage, query and export layers.

Params are stored as JSON text plus a type tag so that ``lr: 1e-3`` comes back
as a float and ``epochs: 10`` comes back as an int, instead of everything
collapsing to a string the way a naive ``TEXT`` column would. Metrics are
floats only and must be finite; a NaN in a metric curve breaks comparisons and
JSON export, so it is rejected at the boundary.
"""
