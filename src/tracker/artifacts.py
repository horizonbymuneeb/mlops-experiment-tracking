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


def infer_media_type(name: str) -> str | None:
    """Guess a media type from a file name suffix."""
    suffix = Path(name).suffix.lower()
    return _MEDIA_TYPES.get(suffix)


def validate_digest(digest: str, algorithm: str = DEFAULT_HASH_ALGORITHM) -> str:
    """Reject digests that could escape the store directory or are malformed."""
    expected = DIGEST_HEX.get(algorithm)
    if expected is None:
        raise ArtifactError(f"unsupported hash algorithm {algorithm!r}")
    if not isinstance(digest, str) or len(digest) != expected:
        raise ArtifactError(f"malformed {algorithm} digest: {digest!r}")
    if any(ch not in "0123456789abcdef" for ch in digest):
        raise ArtifactError(f"malformed {algorithm} digest: {digest!r}")
    return digest


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    """Write ``data`` to ``path`` atomically (temp file + ``os.replace``)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, target)
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise
    return target


class ArtifactStore:
    """Filesystem blob store addressed by content hash."""

    def __init__(
        self,
        root: str | Path,
        *,
        hash_algorithm: str = DEFAULT_HASH_ALGORITHM,
        verify_on_read: bool = False,
    ) -> None:
        if hash_algorithm not in DIGEST_HEX:
            raise ArtifactError(f"unsupported hash algorithm {hash_algorithm!r}")
        self.root = Path(root).expanduser()
        self.hash_algorithm = hash_algorithm
        self.verify_on_read = verify_on_read
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def objects_dir(self) -> Path:
        return self.root / "objects"

    def object_path(self, digest: str) -> Path:
        """Filesystem path for ``digest`` (does not check existence)."""
        validate_digest(digest, self.hash_algorithm)
        return self.objects_dir / digest[:2] / digest[2:]

    def exists(self, digest: str) -> bool:
        """True when the blob is present on disk."""
        return self.object_path(digest).is_file()

    def put_bytes(self, data: bytes, media_type: str | None = None) -> ArtifactRef:
        """Store ``data``; returns a ref flagged ``deduplicated`` when it existed."""
        digest = hash_bytes(data, self.hash_algorithm)
        target = self.object_path(digest)
        if target.is_file():
            return ArtifactRef(digest, len(data), media_type, deduplicated=True)
        atomic_write_bytes(target, data)
        return ArtifactRef(digest, len(data), media_type, deduplicated=False)

    def put_file(
        self, path: str | Path, media_type: str | None = None
    ) -> ArtifactRef:
        """Store the contents of ``path`` under its content hash."""
        source = Path(path)
        if not source.is_file():
            raise ArtifactError(f"not a file: {source}")
        digest, size = hash_file(source, self.hash_algorithm)
        target = self.object_path(digest)
        if target.is_file():
            return ArtifactRef(
                digest, size, media_type or infer_media_type(source.name), deduplicated=True
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as out, open(source, "rb") as src:
                while True:
                    chunk = src.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_name, target)
        except BaseException:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
        return ArtifactRef(
            digest, size, media_type or infer_media_type(source.name), deduplicated=False
        )

    def put_stream(self, stream: BinaryIO, media_type: str | None = None) -> ArtifactRef:
        """Store an already-open binary stream without buffering it all."""
        hasher = new_hasher(self.hash_algorithm)
        size = 0
        staging = self.root / "tmp"
        staging.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=str(staging), prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as out:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    hasher.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            digest = hasher.hexdigest()
            target = self.object_path(digest)
            if target.is_file():
                os.unlink(temp_name)
                return ArtifactRef(digest, size, media_type, deduplicated=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_name, target)
            return ArtifactRef(digest, size, media_type, deduplicated=False)
        except BaseException:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise

    def read_bytes(self, digest: str) -> bytes:
        """Return the blob contents, verifying the hash when configured."""
        path = self.object_path(digest)
        if not path.is_file():
            raise ArtifactNotFound(f"artifact {digest} is not in {self.root}")
        data = path.read_bytes()
        if self.verify_on_read and hash_bytes(data, self.hash_algorithm) != digest:
            raise ArtifactError(f"artifact {digest} failed its hash check")
        return data

    def open(self, digest: str) -> BinaryIO:
        """Open the blob for binary reading."""
        path = self.object_path(digest)
        if not path.is_file():
            raise ArtifactNotFound(f"artifact {digest} is not in {self.root}")
        return open(path, "rb")

    def size(self, digest: str) -> int:
        """Size of a stored blob in bytes."""
        path = self.object_path(digest)
        if not path.is_file():
            raise ArtifactNotFound(f"artifact {digest} is not in {self.root}")
        return path.stat().st_size

    def verify(self, digest: str) -> bool:
        """True when the blob exists and its bytes still hash to ``digest``."""
        path = self.object_path(digest)
        if not path.is_file():
            return False
        actual, _ = hash_file(path, self.hash_algorithm)
        return actual == digest

    def list_objects(self) -> list[str]:
        """Every digest currently stored, sorted."""
        found: list[str] = []
        if not self.objects_dir.is_dir():
            return found
        for shard in sorted(self.objects_dir.iterdir()):
            if not shard.is_dir():
                continue
            for blob in sorted(shard.iterdir()):
                if blob.is_file() and not blob.name.startswith("."):
                    found.append(shard.name + blob.name)
        return found

    def total_bytes(self) -> int:
        """Bytes used by stored blobs (temp files excluded)."""
        return sum(self.object_path(digest).stat().st_size for digest in self.list_objects())

    def garbage_collect(
        self, referenced: Iterable[str], *, dry_run: bool = False
    ) -> dict[str, object]:
        """Delete blobs whose digest is not in ``referenced``.

        Returns a summary dict with the removed digests, their count and the
        bytes reclaimed. ``dry_run`` reports without deleting.
        """
        keep = {validate_digest(d, self.hash_algorithm) for d in referenced}
        removed: list[str] = []
        freed = 0
        for digest in self.list_objects():
            if digest in keep:
                continue
            path = self.object_path(digest)
            freed += path.stat().st_size
            removed.append(digest)
            if not dry_run:
                path.unlink()
        if not dry_run:
            for shard in self.objects_dir.iterdir() if self.objects_dir.is_dir() else []:
                if shard.is_dir() and not any(shard.iterdir()):
                    shard.rmdir()
        return {
            "removed": removed,
            "removed_count": len(removed),
            "bytes_freed": freed,
            "kept_count": len(keep),
            "dry_run": dry_run,
        }

    def stats(self) -> dict[str, object]:
        """Object count and total size for the CLI."""
        objects = self.list_objects()
        return {
            "root": str(self.root),
            "object_count": len(objects),
            "total_bytes": self.total_bytes(),
            "hash_algorithm": self.hash_algorithm,
        }
