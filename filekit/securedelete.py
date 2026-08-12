"""Overwrite-then-remove a file, plus a safe "send to Recycle Bin" helper.

.. warning::
   :func:`secure_delete` overwrites the file's *current* bytes and then unlinks
   it.  On modern storage this does **not** guarantee the old data is
   irrecoverable: SSDs and flash use wear-levelling so writes land on different
   physical cells; copy-on-write/journaling/log-structured filesystems (Btrfs,
   ZFS, APFS, NTFS journaling) and snapshots may keep older copies; and any
   backup or cloud sync will still hold the data.  Treat it as "best effort on a
   plain magnetic disk", not a compliance-grade wipe.  When in doubt, use
   full-disk encryption from the start.
"""

from __future__ import annotations

import os

from .common import require_file
from .errors import FileKitError

_CHUNK = 1024 * 1024


def secure_delete(path, passes=1):
    """Overwrite *path* *passes* times with random data, then delete it.

    Returns the (now-removed) path.  See the module docstring for why this is
    only best-effort on modern hardware.  Raises :class:`FileKitError` if the
    target is missing or not a regular file.
    """
    require_file(path)
    if passes < 1:
        raise FileKitError("passes must be at least 1")
    try:
        size = os.path.getsize(path)
        with open(path, "r+b", buffering=0) as fh:
            for _ in range(passes):
                fh.seek(0)
                remaining = size
                while remaining > 0:
                    n = min(_CHUNK, remaining)
                    fh.write(os.urandom(n))
                    remaining -= n
                fh.flush()
                os.fsync(fh.fileno())
        os.remove(path)
    except OSError as exc:
        raise FileKitError(f"secure delete failed for {path!r}: {exc}") from exc
    return path


def to_recycle(path):
    """Send *path* to the OS Recycle Bin / Trash via ``send2trash``.

    Unlike :func:`secure_delete` this is recoverable by design.  Raises
    :class:`FileKitError` if the path is missing or ``send2trash`` is unavailable
    on the current platform.
    """
    if not os.path.exists(path):
        raise FileKitError(f"path not found: {path}")
    try:
        from send2trash import send2trash
    except Exception as exc:
        raise FileKitError(
            f"send2trash is unavailable on this platform ({exc})") from exc
    try:
        send2trash(path)
    except Exception as exc:
        raise FileKitError(f"could not recycle {path!r}: {exc}") from exc
    return path


__all__ = ["secure_delete", "to_recycle"]
