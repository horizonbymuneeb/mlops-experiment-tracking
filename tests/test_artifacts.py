"""Content-addressed artifact store: hashing, dedup and garbage collection."""

from __future__ import annotations

import hashlib
import io

import pytest

from tracker.artifacts import (
    ArtifactError,
    ArtifactNotFound,
    ArtifactStore,
    atomic_write_bytes,
    hash_bytes,
    hash_file,
    infer_media_type,
    validate_digest,
)

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
