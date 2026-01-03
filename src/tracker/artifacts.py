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


def new_hasher(algorithm: str = DEFAULT_HASH_ALGORITHM):
    """Return a fresh hashlib object, rejecting unknown algorithms."""
    if algorithm not in DIGEST_HEX:
        raise ArtifactError(f"unsupported hash algorithm {algorithm!r}")
    return hashlib.new(algorithm)


def hash_bytes(data: bytes, algorithm: str = DEFAULT_HASH_ALGORITHM) -> str:
    """Hex digest of ``data``."""
    hasher = new_hasher(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def hash_file(
    path: str | Path, algorithm: str = DEFAULT_HASH_ALGORITHM, chunk_size: int = CHUNK_SIZE
) -> tuple[str, int]:
    """Hash a file without loading it into memory; returns ``(digest, size)``."""
    hasher = new_hasher(algorithm)
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), size
