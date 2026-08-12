"""Tests for filekit.rename -- plan (pure) and apply (side effects)."""

import os

import pytest

from filekit import FileKitError
from filekit.rename import RenameRule, apply_rename, plan_rename


def _touch(path, data=b"x"):
    with open(path, "wb") as fh:
        fh.write(data)


def test_plan_is_pure(tmp_path):
    files = [str(tmp_path / f"f{i}.txt") for i in range(3)]
    for f in files:
        _touch(f)
    plan = plan_rename(files, RenameRule(prefix="a_"))
    # nothing renamed on disk yet
    assert sorted(os.listdir(tmp_path)) == ["f0.txt", "f1.txt", "f2.txt"]
    assert [os.path.basename(n) for _, n in plan] == ["a_f0.txt", "a_f1.txt", "a_f2.txt"]


def test_numbering_padding_and_start(tmp_path):
    files = [str(tmp_path / f"pic{i}.jpg") for i in range(3)]
    for f in files:
        _touch(f)
    rule = RenameRule(prefix="img_", suffix="_{n}", number=True,
                      number_start=5, number_pad=3)
    plan = plan_rename(files, rule)
    news = [os.path.basename(n) for _, n in plan]
    assert news == ["img_pic0_005.jpg", "img_pic1_006.jpg", "img_pic2_007.jpg"]


def test_numbering_appends_without_token(tmp_path):
    f = str(tmp_path / "a.txt")
    _touch(f)
    plan = plan_rename([f], RenameRule(number=True, number_start=1, number_pad=2))
    assert os.path.basename(plan[0][1]) == "a01.txt"


def test_regex_substitution(tmp_path):
    files = [str(tmp_path / n) for n in ("IMG_0001.png", "IMG_0002.png")]
    for f in files:
        _touch(f)
    rule = RenameRule(find=r"IMG_(\d+)", replace=r"photo-\1", regex=True)
    plan = plan_rename(files, rule)
    assert [os.path.basename(n) for _, n in plan] == ["photo-0001.png", "photo-0002.png"]


def test_bad_regex_raises(tmp_path):
    f = str(tmp_path / "a.txt")
    _touch(f)
    with pytest.raises(FileKitError):
        plan_rename([f], RenameRule(find="(", regex=True))


def test_case_and_extension_change(tmp_path):
    f = str(tmp_path / "Hello World.TXT")
    _touch(f)
    plan = plan_rename([f], RenameRule(case="lower", new_ext="md"))
    assert os.path.basename(plan[0][1]) == "hello world.md"


def test_apply_renames_on_disk(tmp_path):
    files = [str(tmp_path / f"f{i}.txt") for i in range(3)]
    for f in files:
        _touch(f)
    plan = plan_rename(files, RenameRule(prefix="r_", number=True, number_pad=2))
    applied = apply_rename(plan)
    assert len(applied) == 3
    assert sorted(os.listdir(tmp_path)) == ["r_f001.txt", "r_f102.txt", "r_f203.txt"]


def test_apply_detects_collision(tmp_path):
    a = str(tmp_path / "a.txt")
    b = str(tmp_path / "b.txt")
    _touch(a)
    _touch(b)
    # a rule mapping both files to the same name
    plan = [(a, str(tmp_path / "same.txt")), (b, str(tmp_path / "same.txt"))]
    with pytest.raises(FileKitError):
        apply_rename(plan)
    # nothing changed
    assert sorted(os.listdir(tmp_path)) == ["a.txt", "b.txt"]


def test_apply_refuses_to_clobber_bystander(tmp_path):
    a = str(tmp_path / "a.txt")
    victim = str(tmp_path / "taken.txt")
    _touch(a)
    _touch(victim, b"important")
    plan = [(a, victim)]
    with pytest.raises(FileKitError):
        apply_rename(plan)
    assert open(victim, "rb").read() == b"important"


def test_apply_handles_swap(tmp_path):
    a = str(tmp_path / "a.txt")
    b = str(tmp_path / "b.txt")
    _touch(a, b"AAA")
    _touch(b, b"BBB")
    plan = [(a, b), (b, a)]
    apply_rename(plan)
    assert open(a, "rb").read() == b"BBB"
    assert open(b, "rb").read() == b"AAA"
