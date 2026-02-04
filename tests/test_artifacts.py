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


def test_put_file_streams_and_dedups(store, tmp_path):
    source = tmp_path / "checkpoint.bin"
    source.write_bytes(b"\x00\x01\x02" * 1000)
    first = store.put_file(source)
    second = store.put_file(source)
    assert first.size_bytes == 3000
    assert first.media_type == "application/octet-stream"
    assert second.deduplicated is True
    assert store.read_bytes(first.digest) == source.read_bytes()


def test_put_file_missing(store, tmp_path):
    with pytest.raises(ArtifactError, match="not a file"):
        store.put_file(tmp_path / "nope.bin")


def test_put_stream(store):
    ref = store.put_stream(io.BytesIO(b"streamed payload"))
    assert store.read_bytes(ref.digest) == b"streamed payload"
    again = store.put_stream(io.BytesIO(b"streamed payload"))
    assert again.deduplicated is True
    assert store.list_objects() == [ref.digest]


def test_read_missing_raises_not_found(store):
    missing = "0" * 64
    with pytest.raises(ArtifactNotFound):
        store.read_bytes(missing)
    with pytest.raises(ArtifactNotFound):
        store.open(missing)
    with pytest.raises(ArtifactNotFound):
        store.size(missing)


def test_read_bytes_returns_exact_content(store):
    payload = bytes(range(256))
    ref = store.put_bytes(payload)
    assert store.read_bytes(ref.digest) == payload
    with store.open(ref.digest) as handle:
        assert handle.read() == payload
    assert store.size(ref.digest) == 256


def test_verify_detects_corruption(store):
    ref = store.put_bytes(b"trust me")
    assert store.verify(ref.digest) is True
    store.object_path(ref.digest).write_bytes(b"tampered")
    assert store.verify(ref.digest) is False
    with pytest.raises(ArtifactError, match="hash check"):
        ArtifactStore(store.root, verify_on_read=True).read_bytes(ref.digest)


def test_verify_missing_is_false(store):
    assert store.verify("1" * 64) is False


def test_list_objects_and_total_bytes(store):
    a = store.put_bytes(b"a")
    b = store.put_bytes(b"bb")
    assert store.list_objects() == sorted([a.digest, b.digest])
    assert store.total_bytes() == 3


def test_garbage_collect_keeps_referenced(store):
    keep = store.put_bytes(b"keep me")
    drop = store.put_bytes(b"drop me")
    result = store.garbage_collect([keep.digest])
    assert result["removed"] == [drop.digest]
    assert result["removed_count"] == 1
    assert result["bytes_freed"] == len(b"drop me")
    assert store.exists(keep.digest) is True
    assert store.exists(drop.digest) is False
    assert store.list_objects() == [keep.digest]
