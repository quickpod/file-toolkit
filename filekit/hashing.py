"""File checksums: hash a file, write a SHA256SUMS manifest, verify one.

The manifest format is the classic ``coreutils`` layout -- one line per file::

    <hexdigest>  <relative/path>

so files produced here can be checked with ``sha256sum -c`` and vice-versa.
"""

from __future__ import annotations

import hashlib
import os

from .common import ensure_parent_dir, iter_files, require_dir, require_file
from .errors import FileKitError

_CHUNK = 1024 * 1024


def hash_file(path, algo="sha256"):
    """Return the hex digest of *path* using *algo* (any :mod:`hashlib` name)."""
    require_file(path)
    try:
        h = hashlib.new(algo)
    except (ValueError, TypeError) as exc:
        raise FileKitError(f"unknown hash algorithm {algo!r}") from exc
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                h.update(chunk)
    except OSError as exc:
        raise FileKitError(f"could not read {path!r}: {exc}") from exc
    return h.hexdigest()


def write_sha256sums(root, out, algo="sha256"):
    """Hash every file under *root* and write a sums manifest to *out*.

    Paths in the manifest are relative to *root* (POSIX separators).  The output
    file itself is skipped if it happens to live inside *root*.  Returns the
    number of files recorded.
    """
    require_dir(root)
    root = os.path.abspath(root)
    out = os.path.abspath(out)
    ensure_parent_dir(out)
    lines = []
    count = 0
    for path in iter_files(root):
        if os.path.abspath(path) == out:
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        lines.append(f"{hash_file(path, algo)}  {rel}\n")
        count += 1
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    except OSError as exc:
        raise FileKitError(f"could not write {out!r}: {exc}") from exc
    return count


def _parse_line(line):
    """Return ``(digest, relpath)`` for one manifest line, or ``None`` to skip."""
    line = line.rstrip("\n")
    if not line.strip():
        return None
    # coreutils uses "<hash>  <name>" (text) or "<hash> *<name>" (binary).
    parts = line.split(None, 1)
    if len(parts) != 2:
        raise FileKitError(f"malformed sums line: {line!r}")
    digest, name = parts
    if name.startswith("*"):
        name = name[1:]
    return digest.lower(), name


def verify_sums(sumsfile, algo="sha256"):
    """Verify a sums manifest. Returns a list of per-file result dicts.

    Each result is ``{"path", "status", "expected", "actual"}`` where status is
    one of ``"ok"``, ``"failed"`` (hash mismatch) or ``"missing"`` (no such
    file).  Paths are resolved relative to the manifest's directory.
    """
    require_file(sumsfile)
    base = os.path.dirname(os.path.abspath(sumsfile))
    try:
        with open(sumsfile, "r", encoding="utf-8") as fh:
            raw = fh.readlines()
    except OSError as exc:
        raise FileKitError(f"could not read {sumsfile!r}: {exc}") from exc

    results = []
    for line in raw:
        parsed = _parse_line(line)
        if parsed is None:
            continue
        expected, name = parsed
        path = os.path.normpath(os.path.join(base, name))
        if not os.path.isfile(path):
            results.append({"path": path, "status": "missing",
                            "expected": expected, "actual": None})
            continue
        actual = hash_file(path, algo)
        status = "ok" if actual.lower() == expected else "failed"
        results.append({"path": path, "status": status,
                        "expected": expected, "actual": actual})
    return results


__all__ = ["hash_file", "write_sha256sums", "verify_sums"]
