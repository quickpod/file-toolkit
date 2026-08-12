"""Find and remove duplicate files by content.

:func:`find_duplicates` groups byte-identical files.  It is fast because it
pre-filters by size (files of different size can never be identical, so they are
never hashed) and only hashes the survivors.  :func:`remove_duplicates` keeps
one file per group and sends the rest to the Recycle Bin (``send2trash``) by
default, or deletes them permanently when asked.
"""

from __future__ import annotations

import os

from .common import iter_files, require_dir
from .errors import FileKitError
from .hashing import hash_file


def find_duplicates(root, by="sha256", min_size=1):
    """Return groups of identical files under *root* (each group has >= 2 files).

    *by* is the hash algorithm used to confirm identity.  *min_size* skips tiny
    files (default 1 -- empty files are ignored).  Within each group and across
    groups the order is deterministic (sorted by path).
    """
    require_dir(root)

    by_size = {}
    for path in iter_files(root):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size < min_size:
            continue
        by_size.setdefault(size, []).append(path)

    groups = []
    for size in sorted(by_size):
        candidates = by_size[size]
        if len(candidates) < 2:
            continue  # unique size -> unique content; never hashed
        by_hash = {}
        for path in candidates:
            digest = hash_file(path, by)
            by_hash.setdefault(digest, []).append(path)
        for digest in sorted(by_hash):
            members = sorted(by_hash[digest])
            if len(members) >= 2:
                groups.append(members)
    return groups


def _delete(path, to_trash):
    if to_trash:
        try:
            from send2trash import send2trash
        except Exception as exc:  # platform bits missing / not installed
            raise FileKitError(
                f"send2trash is unavailable ({exc}); pass to_trash=False to "
                "delete permanently") from exc
        try:
            send2trash(path)
        except Exception as exc:
            raise FileKitError(f"could not recycle {path!r}: {exc}") from exc
    else:
        try:
            os.remove(path)
        except OSError as exc:
            raise FileKitError(f"could not delete {path!r}: {exc}") from exc


def remove_duplicates(groups, keep="first", to_trash=True):
    """Remove all but one file from each group. Returns the removed paths.

    *keep* is ``"first"`` or ``"last"`` (by the sorted order within a group).
    With *to_trash* true, removed files go to the Recycle Bin via ``send2trash``;
    otherwise they are unlinked permanently.
    """
    if keep not in ("first", "last"):
        raise FileKitError("keep must be 'first' or 'last'")
    removed = []
    for group in groups:
        if len(group) < 2:
            continue
        members = list(group)
        victims = members[1:] if keep == "first" else members[:-1]
        for path in victims:
            _delete(path, to_trash)
            removed.append(path)
    return removed


__all__ = ["find_duplicates", "remove_duplicates"]
