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
DEFAULT_HASH_ALGORITHM = "sha256"
DIGEST_HEX = {"sha256": 64, "sha1": 40, "md5": 32}

_MEDIA_TYPES: dict[str, str] = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".bin": "application/octet-stream",
    ".pt": "application/octet-stream",
    ".pth": "application/octet-stream",
    ".npy": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}


class ArtifactError(RuntimeError):
    """Base class for artifact store failures."""


class ArtifactNotFound(ArtifactError, KeyError):
    """Raised when a digest is not present in the store."""

    def __str__(self) -> str:  # KeyError would add quotes
        return self.args[0] if self.args else "artifact not found"


@dataclass(frozen=True)
class ArtifactRef:
    """The result of storing a blob: what to record in the database."""

    digest: str
    size_bytes: int
    media_type: str | None = None
    deduplicated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "deduplicated": self.deduplicated,
        }
