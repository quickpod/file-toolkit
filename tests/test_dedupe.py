"""Tests for filekit.dedupe -- finding and removing content duplicates."""

import os

from filekit.dedupe import find_duplicates, remove_duplicates


def _write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def test_finds_identical_files(tmp_path):
    _write(tmp_path / "a.bin", b"hello" * 500)
    _write(tmp_path / "b.bin", b"hello" * 500)      # identical to a
    _write(tmp_path / "c.bin", b"different" * 500)  # unique
    sub = tmp_path / "sub"
    sub.mkdir()
    _write(sub / "d.bin", b"hello" * 500)           # identical to a/b

    groups = find_duplicates(str(tmp_path))
    assert len(groups) == 1
    assert len(groups[0]) == 3
    names = sorted(os.path.basename(p) for p in groups[0])
    assert names == ["a.bin", "b.bin", "d.bin"]


def test_size_prefilter_skips_unique_sizes(tmp_path):
    _write(tmp_path / "one.bin", b"a" * 10)
    _write(tmp_path / "two.bin", b"b" * 20)
    assert find_duplicates(str(tmp_path)) == []


def test_remove_keeps_one_first(tmp_path):
    _write(tmp_path / "a.bin", b"dup" * 400)
    _write(tmp_path / "b.bin", b"dup" * 400)
    _write(tmp_path / "c.bin", b"dup" * 400)
    groups = find_duplicates(str(tmp_path))
    removed = remove_duplicates(groups, keep="first", to_trash=False)
    assert len(removed) == 2
    survivors = sorted(os.listdir(tmp_path))
    assert len(survivors) == 1
    # the kept file is the first of the sorted group
    assert survivors[0] == "a.bin"


def test_remove_keeps_last(tmp_path):
    _write(tmp_path / "a.bin", b"z" * 400)
    _write(tmp_path / "b.bin", b"z" * 400)
    groups = find_duplicates(str(tmp_path))
    remove_duplicates(groups, keep="last", to_trash=False)
    assert sorted(os.listdir(tmp_path)) == ["b.bin"]
