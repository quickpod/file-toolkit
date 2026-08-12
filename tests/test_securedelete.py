"""Tests for filekit.securedelete -- overwrite/remove and Recycle Bin helper."""

import os

import pytest

from filekit import FileKitError
from filekit.securedelete import secure_delete, to_recycle


def test_secure_delete_removes_file(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_bytes(b"sensitive" * 1000)
    returned = secure_delete(str(f))
    assert returned == str(f)
    assert not f.exists()


def test_secure_delete_multiple_passes(tmp_path):
    f = tmp_path / "s.bin"
    f.write_bytes(os.urandom(4096))
    secure_delete(str(f), passes=3)
    assert not f.exists()


def test_secure_delete_missing_raises(tmp_path):
    with pytest.raises(FileKitError):
        secure_delete(str(tmp_path / "nope.txt"))


def test_secure_delete_rejects_bad_passes(tmp_path):
    f = tmp_path / "s.bin"
    f.write_bytes(b"x")
    with pytest.raises(FileKitError):
        secure_delete(str(f), passes=0)


def _send2trash_works(tmp_path):
    """Probe whether send2trash actually functions in this environment."""
    try:
        from send2trash import send2trash
    except Exception:
        return False
    probe = tmp_path / ".probe"
    probe.write_bytes(b"x")
    try:
        send2trash(str(probe))
        return True
    except Exception:
        return False


def test_to_recycle(tmp_path):
    if not _send2trash_works(tmp_path):
        pytest.skip("send2trash not functional in this headless environment")
    f = tmp_path / "trash-me.txt"
    f.write_bytes(b"bye")
    to_recycle(str(f))
    assert not f.exists()


def test_to_recycle_missing_raises(tmp_path):
    with pytest.raises(FileKitError):
        to_recycle(str(tmp_path / "nope.txt"))
