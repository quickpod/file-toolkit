"""Tests for filekit.splitjoin -- exact byte round-trip and size verification."""

import os

import pytest

from filekit import FileKitError
from filekit.splitjoin import join_files, split_file


def test_split_join_exact_bytes(tmp_path):
    data = os.urandom(10_000)
    src = tmp_path / "big.dat"
    src.write_bytes(data)

    parts_dir = tmp_path / "parts"
    parts = split_file(str(src), 1024, str(parts_dir))
    # 10000 / 1024 -> 10 parts
    assert len(parts) == 10
    # every part except possibly the last is exactly 1024 bytes
    for p in parts[:-1]:
        assert os.path.getsize(p) == 1024

    out = tmp_path / "rejoined.dat"
    join_files(sorted(parts), str(out))
    assert out.read_bytes() == data


def test_join_via_glob(tmp_path):
    data = os.urandom(5000)
    src = tmp_path / "movie.bin"
    src.write_bytes(data)
    parts_dir = tmp_path / "p"
    split_file(str(src), 2000, str(parts_dir))
    out = tmp_path / "out.bin"
    join_files(str(parts_dir / "movie.bin.*"), str(out))
    assert out.read_bytes() == data


def test_join_detects_missing_part(tmp_path):
    data = os.urandom(6000)
    src = tmp_path / "x.dat"
    src.write_bytes(data)
    parts_dir = tmp_path / "parts"
    parts = split_file(str(src), 2000, str(parts_dir))
    # drop the middle part -> size will not match the manifest
    incomplete = sorted(parts)
    incomplete.pop(1)
    out = tmp_path / "bad.dat"
    with pytest.raises(FileKitError):
        join_files(incomplete, str(out))


def test_split_empty_file(tmp_path):
    src = tmp_path / "empty.dat"
    src.write_bytes(b"")
    parts_dir = tmp_path / "parts"
    parts = split_file(str(src), 1024, str(parts_dir))
    assert len(parts) == 1
    out = tmp_path / "out.dat"
    join_files(sorted(parts), str(out))
    assert out.read_bytes() == b""


def test_split_bad_size_raises(tmp_path):
    src = tmp_path / "x.dat"
    src.write_bytes(b"data")
    with pytest.raises(FileKitError):
        split_file(str(src), 0, str(tmp_path / "parts"))
