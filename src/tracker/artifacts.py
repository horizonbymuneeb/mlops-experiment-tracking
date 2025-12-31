"""Content-addressed artifact storage.

Blobs are stored once, keyed by the hash of their bytes, under
``<root>/objects/<ab>/<rest-of-digest>``. The database only ever stores the
digest and the display name, so two runs that log byte-identical checkpoints
share one file on disk. Writes go to a temporary file in the same directory and
are moved into place with ``os.replace``, which is atomic on POSIX: a reader
never sees a partially written blob, and a crash leaves at worst a stray temp
file that the garbage collector removes.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

CHUNK_SIZE = 1 << 20
