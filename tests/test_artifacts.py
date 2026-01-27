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


def test_hash_bytes_matches_hashlib():
    assert hash_bytes(b"abc") == ABC_SHA256
    assert hash_bytes(b"") == hashlib.sha256(b"").hexdigest()


def test_hash_bytes_algorithm_selection():
    assert hash_bytes(b"abc", "md5") == hashlib.md5(b"abc").hexdigest()


def test_hash_bytes_unknown_algorithm():
    with pytest.raises(ArtifactError, match="unsupported hash algorithm"):
        hash_bytes(b"x", "crc32")
