"""Folder-level convenience wrappers over the single-purpose modules.

These gather files from a folder and run rename / hash / archive-conversion in
one call, so the CLI and GUI don't each re-implement the "walk a folder" glue.
Everything defers to the tested core functions.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from .archive import (
    sevenz_create, sevenz_extract, zip_create, zip_extract,
)
from .common import iter_files, require_dir
from .errors import FileKitError
from .hashing import write_sha256sums
from .rename import apply_rename, plan_rename


def gather_files(folder, recursive=False, include_hidden=True):
    """Return a sorted list of files in *folder* (top-level unless recursive)."""
    return list(iter_files(folder, recursive=recursive,
                           include_hidden=include_hidden))


def batch_rename(folder, rule, apply=False, recursive=False):
    """Plan (and optionally apply) a rename across every file in *folder*.

    Returns ``(plan, applied)`` where *plan* is the ``[(old, new), ...]``
    preview and *applied* is the subset actually renamed (empty unless
    *apply*).  Safe by default: nothing is renamed unless ``apply=True``.
    """
    files = gather_files(folder, recursive=recursive)
    plan = plan_rename(files, rule)
    applied = apply_rename(plan) if apply else []
    return plan, applied


def batch_hash(folder, out=None, algo="sha256"):
    """Write a sums manifest for *folder*. Returns ``(out_path, count)``."""
    require_dir(folder)
    if not out:
        out = os.path.join(folder, "SHA256SUMS")
    count = write_sha256sums(folder, out, algo=algo)
    return out, count


def _extract_any(archive, dest, password=None):
    if str(archive).lower().endswith(".7z"):
        return sevenz_extract(archive, dest, password=password)
    return zip_extract(archive, dest)


def _create_any(src_dir, out, password=None):
    paths = [os.path.join(src_dir, n) for n in sorted(os.listdir(src_dir))]
    if str(out).lower().endswith(".7z"):
        return sevenz_create(paths, out, password=password)
    return zip_create(paths, out)


def convert_archive(archive, out, password=None, dest_password=None):
    """Convert a ZIP<->7z archive by extracting to a temp dir and repacking.

    Format is chosen from the *out* extension.  Returns *out*.
    """
    if not os.path.isfile(archive):
        raise FileKitError(f"archive not found: {archive}")
    tmp = tempfile.mkdtemp(prefix="fk_convert_")
    try:
        _extract_any(archive, tmp, password=password)
        return _create_any(tmp, out, password=dest_password)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def batch_convert_archives(folder, out_dir, to="7z", recursive=False,
                           password=None, dest_password=None):
    """Convert every ``.zip``/``.7z`` in *folder* to *to* inside *out_dir*.

    Returns the list of output paths.
    """
    require_dir(folder)
    to = to.lower().lstrip(".")
    if to not in ("zip", "7z"):
        raise FileKitError("target format must be 'zip' or '7z'")
    os.makedirs(out_dir, exist_ok=True)
    outputs = []
    for path in gather_files(folder, recursive=recursive):
        low = path.lower()
        if not (low.endswith(".zip") or low.endswith(".7z")):
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(out_dir, f"{stem}.{to}")
        outputs.append(convert_archive(path, out, password=password,
                                       dest_password=dest_password))
    return outputs


__all__ = [
    "gather_files",
    "batch_rename",
    "batch_hash",
    "convert_archive",
    "batch_convert_archives",
]
