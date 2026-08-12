"""Create and extract ZIP and 7z archives.

ZIP uses the standard library :mod:`zipfile` (deflate).  7z uses ``py7zr`` and
supports an optional password (which encrypts both file data and, where
possible, the header).  Directories passed to a ``*_create`` are added
recursively; a single file is stored under its basename.
"""

from __future__ import annotations

import os
import zipfile

from .common import ensure_parent_dir, require_dir, require_file
from .errors import FileKitError


def _iter_members(paths):
    """Yield ``(abs_path, arcname)`` pairs for files/dirs in *paths*.

    A file is stored under its basename; a directory is walked and each file
    stored under ``<dirbasename>/<relpath>``.
    """
    if isinstance(paths, (str, bytes)):
        paths = [paths]
    if not paths:
        raise FileKitError("no input paths given")
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            top = os.path.basename(p.rstrip(os.sep)) or "dir"
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames.sort()
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, p)
                    yield full, os.path.join(top, rel).replace(os.sep, "/")
        elif os.path.isfile(p):
            yield p, os.path.basename(p)
        else:
            raise FileKitError(f"input not found: {p}")


def zip_create(paths, out, compression=zipfile.ZIP_DEFLATED):
    """Create a ZIP archive *out* from *paths*. Returns *out*."""
    out = os.path.abspath(out)
    ensure_parent_dir(out)
    members = list(_iter_members(paths))
    try:
        with zipfile.ZipFile(out, "w", compression=compression) as zf:
            for full, arcname in members:
                zf.write(full, arcname)
    except (OSError, zipfile.BadZipFile) as exc:
        raise FileKitError(f"could not create zip {out!r}: {exc}") from exc
    return out


def zip_extract(archive, dest):
    """Extract ZIP *archive* into *dest*. Returns the list of extracted names."""
    require_file(archive)
    dest = os.path.abspath(dest)
    os.makedirs(dest, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            zf.extractall(dest)
    except (OSError, zipfile.BadZipFile) as exc:
        raise FileKitError(f"could not extract zip {archive!r}: {exc}") from exc
    return names


def zip_list(archive):
    """Return the member names inside ZIP *archive*."""
    require_file(archive)
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            return zf.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise FileKitError(f"could not read zip {archive!r}: {exc}") from exc


def _py7zr():
    try:
        import py7zr
    except Exception as exc:  # pragma: no cover - dependency guaranteed by reqs
        raise FileKitError(f"py7zr is required for 7z archives ({exc})") from exc
    return py7zr


def sevenz_create(paths, out, password=None):
    """Create a 7z archive *out* from *paths*, optionally encrypted. Returns *out*."""
    py7zr = _py7zr()
    out = os.path.abspath(out)
    ensure_parent_dir(out)
    members = list(_iter_members(paths))
    kwargs = {}
    if password:
        kwargs["password"] = password
        kwargs["header_encryption"] = True
    try:
        with py7zr.SevenZipFile(out, "w", **kwargs) as zf:
            for full, arcname in members:
                zf.write(full, arcname)
    except Exception as exc:
        raise FileKitError(f"could not create 7z {out!r}: {exc}") from exc
    return out


def sevenz_extract(archive, dest, password=None):
    """Extract 7z *archive* into *dest*. Returns the list of extracted names."""
    py7zr = _py7zr()
    require_file(archive)
    dest = os.path.abspath(dest)
    os.makedirs(dest, exist_ok=True)
    try:
        with py7zr.SevenZipFile(archive, "r", password=password) as zf:
            names = zf.getnames()
            zf.extractall(path=dest)
    except Exception as exc:
        raise FileKitError(
            f"could not extract 7z {archive!r} (wrong password?): {exc}") from exc
    return names


def sevenz_list(archive, password=None):
    """Return the member names inside 7z *archive*."""
    py7zr = _py7zr()
    require_file(archive)
    try:
        with py7zr.SevenZipFile(archive, "r", password=password) as zf:
            return zf.getnames()
    except Exception as exc:
        raise FileKitError(f"could not read 7z {archive!r}: {exc}") from exc


def list_contents(archive, password=None):
    """List members of a ZIP or 7z archive, chosen by extension."""
    if str(archive).lower().endswith(".7z"):
        return sevenz_list(archive, password=password)
    return zip_list(archive)


__all__ = [
    "zip_create", "zip_extract", "zip_list",
    "sevenz_create", "sevenz_extract", "sevenz_list",
    "list_contents",
]
