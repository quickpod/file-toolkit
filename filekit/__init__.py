"""filekit -- a permissively-licensed batch file utility library.

Fully offline.  Every public function raises :class:`FileKitError` on failure so
callers have a single exception to catch.  Import what you need::

    from filekit import plan_rename, RenameRule, find_duplicates, hash_file
    plan = plan_rename(["a.txt", "b.txt"], RenameRule(prefix="img_", number=True))

The GUI (``filekit.gui``) and CLI (``python -m filekit``) both build on this
module and never re-implement the file logic.
"""

from __future__ import annotations

from .errors import FileKitError
from .common import human_size, parse_size, iter_files
from .rename import RenameRule, plan_rename, apply_rename, new_name_for
from .dedupe import find_duplicates, remove_duplicates
from .hashing import hash_file, write_sha256sums, verify_sums
from .archive import (
    zip_create, zip_extract, zip_list,
    sevenz_create, sevenz_extract, sevenz_list, list_contents,
)
from .splitjoin import split_file, join_files
from .securedelete import secure_delete, to_recycle
from .batch import (
    gather_files, batch_rename, batch_hash,
    convert_archive, batch_convert_archives,
)

__version__ = "1.0.5"

__all__ = [
    "FileKitError",
    "human_size",
    "parse_size",
    "iter_files",
    "RenameRule",
    "plan_rename",
    "apply_rename",
    "new_name_for",
    "find_duplicates",
    "remove_duplicates",
    "hash_file",
    "write_sha256sums",
    "verify_sums",
    "zip_create",
    "zip_extract",
    "zip_list",
    "sevenz_create",
    "sevenz_extract",
    "sevenz_list",
    "list_contents",
    "split_file",
    "join_files",
    "secure_delete",
    "to_recycle",
    "gather_files",
    "batch_rename",
    "batch_hash",
    "convert_archive",
    "batch_convert_archives",
]
