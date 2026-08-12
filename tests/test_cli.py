"""Tests for the filekit CLI (``python -m filekit`` via filekit.__main__)."""

import os

from filekit.__main__ import main


def test_rename_preview_is_safe(tmp_path, capsys):
    for i in range(2):
        (tmp_path / f"f{i}.txt").write_bytes(b"x")
    files = [str(tmp_path / f"f{i}.txt") for i in range(2)]
    rc = main(["rename", *files, "--prefix", "a_"])
    assert rc == 0
    # preview must not touch disk
    assert sorted(os.listdir(tmp_path)) == ["f0.txt", "f1.txt"]
    out = capsys.readouterr().out
    assert "Preview" in out


def test_rename_apply(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    rc = main(["rename", str(tmp_path / "a.txt"), "--prefix", "z_", "--apply"])
    assert rc == 0
    assert os.path.exists(tmp_path / "z_a.txt")


def test_dedupe_dry_run_default(tmp_path, capsys):
    (tmp_path / "a.bin").write_bytes(b"dup" * 300)
    (tmp_path / "b.bin").write_bytes(b"dup" * 300)
    rc = main(["dedupe", str(tmp_path)])
    assert rc == 0
    # dry run: both files remain
    assert sorted(os.listdir(tmp_path)) == ["a.bin", "b.bin"]
    assert "Dry run" in capsys.readouterr().out


def test_dedupe_apply_permanent(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"dup" * 300)
    (tmp_path / "b.bin").write_bytes(b"dup" * 300)
    rc = main(["dedupe", str(tmp_path), "--apply", "--permanent"])
    assert rc == 0
    assert len(os.listdir(tmp_path)) == 1


def test_hash_and_verify(tmp_path, capsys):
    (tmp_path / "a.txt").write_bytes(b"content")
    sums = tmp_path / "SHA256SUMS"
    assert main(["hash", str(tmp_path), "-o", str(sums)]) == 0
    assert sums.exists()
    assert main(["verify", str(sums)]) == 0


def test_verify_fails_nonzero(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"content")
    sums = tmp_path / "SHA256SUMS"
    main(["hash", str(tmp_path), "-o", str(sums)])
    f.write_bytes(b"changed")
    assert main(["verify", str(sums)]) == 1


def test_zip_roundtrip_cli(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_bytes(b"hi")
    archive = tmp_path / "a.zip"
    assert main(["zip", str(f), "-o", str(archive)]) == 0
    dest = tmp_path / "out"
    assert main(["unzip", str(archive), "-d", str(dest)]) == 0
    assert (dest / "hello.txt").read_bytes() == b"hi"


def test_split_join_cli(tmp_path):
    data = os.urandom(3000)
    src = tmp_path / "big.dat"
    src.write_bytes(data)
    pdir = tmp_path / "parts"
    assert main(["split", str(src), "--size", "1000", "-d", str(pdir)]) == 0
    out = tmp_path / "out.dat"
    assert main(["join", str(pdir / "big.dat.*"), "-o", str(out)]) == 0
    assert out.read_bytes() == data


def test_secure_delete_needs_yes(tmp_path):
    f = tmp_path / "s.txt"
    f.write_bytes(b"x")
    # without --yes it must refuse and leave the file
    assert main(["secure-delete", str(f)]) == 1
    assert f.exists()
    assert main(["secure-delete", str(f), "--yes"]) == 0
    assert not f.exists()
