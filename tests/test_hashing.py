"""Tests for filekit.hashing -- known vectors and SUMS round-trips."""

import pytest

from filekit import FileKitError
from filekit.hashing import hash_file, verify_sums, write_sha256sums

# SHA-256 of the empty string and of b"abc" (well-known vectors).
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_hash_known_vectors(tmp_path):
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    assert hash_file(str(empty)) == EMPTY_SHA256

    abc = tmp_path / "abc"
    abc.write_bytes(b"abc")
    assert hash_file(str(abc)) == ABC_SHA256


def test_hash_unknown_algo_raises(tmp_path):
    f = tmp_path / "f"
    f.write_bytes(b"x")
    with pytest.raises(FileKitError):
        hash_file(str(f), "not-a-real-algo")


def test_write_and_verify_roundtrip(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"alpha")
    (tmp_path / "b.txt").write_bytes(b"beta")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.txt").write_bytes(b"gamma")

    sums = tmp_path / "SHA256SUMS"
    count = write_sha256sums(str(tmp_path), str(sums))
    assert count == 3

    results = verify_sums(str(sums))
    assert len(results) == 3
    assert all(r["status"] == "ok" for r in results)


def test_verify_detects_tampering(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"original")
    sums = tmp_path / "SHA256SUMS"
    write_sha256sums(str(tmp_path), str(sums))

    f.write_bytes(b"tampered!")  # change content after the manifest was written
    results = verify_sums(str(sums))
    statuses = {r["path"]: r["status"] for r in results}
    assert statuses[str(f)] == "failed"


def test_verify_detects_missing(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"here")
    sums = tmp_path / "SHA256SUMS"
    write_sha256sums(str(tmp_path), str(sums))
    f.unlink()
    results = verify_sums(str(sums))
    assert results[0]["status"] == "missing"
