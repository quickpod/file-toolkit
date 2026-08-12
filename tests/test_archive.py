"""Tests for filekit.archive -- ZIP and 7z round-trips (with/without password)."""

import os

import pytest

from filekit import FileKitError
from filekit.archive import (
    sevenz_create, sevenz_extract, sevenz_list,
    zip_create, zip_extract, zip_list,
)


def _make_tree(root):
    (root / "hello.txt").write_bytes(b"hello world\n")
    d = root / "docs"
    d.mkdir()
    (d / "note.md").write_bytes(b"# note\n" * 50)
    return [str(root / "hello.txt"), str(d)]


def test_zip_roundtrip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    paths = _make_tree(src)
    archive = tmp_path / "out.zip"
    zip_create(paths, str(archive))
    assert archive.exists()
    assert set(zip_list(str(archive))) == {"hello.txt", "docs/note.md"}

    dest = tmp_path / "unzipped"
    names = zip_extract(str(archive), str(dest))
    assert "hello.txt" in names
    assert (dest / "hello.txt").read_bytes() == b"hello world\n"
    assert (dest / "docs" / "note.md").read_bytes() == b"# note\n" * 50


def test_7z_roundtrip_no_password(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    paths = _make_tree(src)
    archive = tmp_path / "out.7z"
    sevenz_create(paths, str(archive))
    assert archive.exists()
    assert set(sevenz_list(str(archive))) == {"hello.txt", "docs/note.md"}

    dest = tmp_path / "un7z"
    sevenz_extract(str(archive), str(dest))
    assert (dest / "hello.txt").read_bytes() == b"hello world\n"
    assert (dest / "docs" / "note.md").read_bytes() == b"# note\n" * 50


def test_7z_roundtrip_with_password(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_bytes(b"top secret data" * 100)
    archive = tmp_path / "enc.7z"
    sevenz_create([str(f)], str(archive), password="hunter2")

    dest = tmp_path / "out"
    sevenz_extract(str(archive), str(dest), password="hunter2")
    assert (dest / "secret.txt").read_bytes() == b"top secret data" * 100


def test_7z_wrong_password_raises(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_bytes(b"classified" * 100)
    archive = tmp_path / "enc.7z"
    sevenz_create([str(f)], str(archive), password="correct")
    dest = tmp_path / "out"
    with pytest.raises(FileKitError):
        sevenz_extract(str(archive), str(dest), password="wrong")


def test_zip_missing_input_raises(tmp_path):
    with pytest.raises(FileKitError):
        zip_create([str(tmp_path / "nope.txt")], str(tmp_path / "x.zip"))
