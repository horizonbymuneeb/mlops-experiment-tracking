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


def test_hash_file_matches_hash_bytes(tmp_path):
    path = tmp_path / "blob.bin"
    payload = b"x" * 5000
    path.write_bytes(payload)
    digest, size = hash_file(path, chunk_size=1024)
    assert digest == hash_bytes(payload)
    assert size == 5000


def test_hash_file_chunk_size_does_not_change_digest(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abcdef" * 1000)
    assert hash_file(path, chunk_size=1)[0] == hash_file(path, chunk_size=10_000)[0]


def test_infer_media_type():
    assert infer_media_type("model.pt") == "application/octet-stream"
    assert infer_media_type("metrics.CSV") == "text/csv"
    assert infer_media_type("notes.unknown-ext") is None


def test_validate_digest_rejects_bad_input():
    for bad in ("", "zz", "A" * 64, "../" + "a" * 61, "a" * 63):
        with pytest.raises(ArtifactError):
            validate_digest(bad)


def test_put_bytes_creates_sharded_object(store):
    ref = store.put_bytes(b"hello", media_type="text/plain")
    assert ref.digest == hash_bytes(b"hello")
    assert ref.size_bytes == 5
    assert ref.deduplicated is False
    path = store.object_path(ref.digest)
    assert path.parent.name == ref.digest[:2]
    assert path.name == ref.digest[2:]
    assert path.read_bytes() == b"hello"


def test_put_bytes_twice_is_deduplicated(store):
    first = store.put_bytes(b"same bytes")
    second = store.put_bytes(b"same bytes")
    assert first.digest == second.digest
    assert first.deduplicated is False
    assert second.deduplicated is True
    assert len(store.list_objects()) == 1
