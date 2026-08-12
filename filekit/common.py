"""Shared low-level helpers used across filekit modules."""

from __future__ import annotations

import os

from .errors import FileKitError


def ensure_dir(path):
    """Make sure directory *path* exists (created on demand)."""
    if path:
        os.makedirs(path, exist_ok=True)


def ensure_parent_dir(path):
    """Make sure the parent directory of *path* exists."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def require_file(path):
    """Return *path* if it is an existing regular file, else raise."""
    if not os.path.exists(path):
        raise FileKitError(f"file not found: {path}")
    if not os.path.isfile(path):
        raise FileKitError(f"not a regular file: {path}")
    return path


def require_dir(path):
    """Return *path* if it is an existing directory, else raise."""
    if not os.path.exists(path):
        raise FileKitError(f"folder not found: {path}")
    if not os.path.isdir(path):
        raise FileKitError(f"not a folder: {path}")
    return path


def iter_files(root, recursive=True, include_hidden=True):
    """Yield absolute paths of the regular files under *root*.

    Sorted for deterministic ordering.  Directories are skipped; symlinks to
    files are followed only in that their target is read when hashed/copied.
    """
    require_dir(root)
    root = os.path.abspath(root)
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in sorted(filenames):
                if not include_hidden and name.startswith("."):
                    continue
                p = os.path.join(dirpath, name)
                if os.path.isfile(p):
                    yield p
    else:
        for name in sorted(os.listdir(root)):
            if not include_hidden and name.startswith("."):
                continue
            p = os.path.join(root, name)
            if os.path.isfile(p):
                yield p


def human_size(num_bytes):
    """Human-readable byte size, e.g. ``1.1MB``."""
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"


def parse_size(text):
    """Parse a human size like ``10``, ``10K``, ``5MB``, ``1.5G`` into bytes.

    Plain integers are bytes.  Suffixes K/M/G/T (optionally followed by ``B``)
    use binary multiples (1024).  Raises :class:`FileKitError` on garbage.
    """
    if isinstance(text, int):
        return text
    s = str(text).strip().upper().replace("IB", "").replace("B", "")
    if not s:
        raise FileKitError("empty size")
    mult = 1
    units = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    if s[-1] in units:
        mult = units[s[-1]]
        s = s[:-1]
    try:
        value = float(s)
    except ValueError as exc:
        raise FileKitError(f"could not parse size {text!r}") from exc
    n = int(value * mult)
    if n <= 0:
        raise FileKitError(f"size must be positive: {text!r}")
    return n


__all__ = [
    "ensure_dir",
    "ensure_parent_dir",
    "require_file",
    "require_dir",
    "iter_files",
    "human_size",
    "parse_size",
]
