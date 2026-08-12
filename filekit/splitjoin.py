"""Split a large file into fixed-size parts and join them back exactly.

:func:`split_file` writes numbered parts (``name.001``, ``name.002`` ...) plus a
small JSON manifest recording the original name, total size and a SHA-256 of the
whole file.  :func:`join_files` concatenates parts in order and -- when a
manifest is available -- verifies the rebuilt size (and hash) so a truncated or
missing part is caught rather than silently producing a corrupt file.
"""

from __future__ import annotations

import glob as _glob
import json
import os

from .common import ensure_dir, parse_size, require_file
from .errors import FileKitError
from .hashing import hash_file

_CHUNK = 1024 * 1024
MANIFEST_EXT = ".fkmanifest.json"


def split_file(path, part_size_bytes, out_dir):
    """Split *path* into <= *part_size_bytes* parts inside *out_dir*.

    Returns the list of part paths (the manifest path is not included).  Part
    names are ``<basename>.NNN`` with a zero-padded, 1-based counter.
    """
    require_file(path)
    part_size_bytes = parse_size(part_size_bytes)
    if part_size_bytes <= 0:
        raise FileKitError("part size must be positive")
    ensure_dir(out_dir)
    base = os.path.basename(path)
    total = os.path.getsize(path)
    # width of the counter: at least 3 digits, more for very many parts.
    n_parts = max(1, (total + part_size_bytes - 1) // part_size_bytes)
    width = max(3, len(str(n_parts)))

    parts = []
    try:
        with open(path, "rb") as src:
            index = 1
            while True:
                chunk = src.read(part_size_bytes)
                if not chunk:
                    break
                part_name = f"{base}.{str(index).zfill(width)}"
                part_path = os.path.join(out_dir, part_name)
                with open(part_path, "wb") as pf:
                    pf.write(chunk)
                parts.append(part_path)
                index += 1
    except OSError as exc:
        raise FileKitError(f"could not split {path!r}: {exc}") from exc

    if not parts:  # empty source file: still emit one empty part
        part_path = os.path.join(out_dir, f"{base}.{'1'.zfill(width)}")
        with open(part_path, "wb"):
            pass
        parts.append(part_path)

    manifest = {
        "name": base,
        "size": total,
        "sha256": hash_file(path, "sha256"),
        "part_size": part_size_bytes,
        "count": len(parts),
        "parts": [{"name": os.path.basename(p),
                   "size": os.path.getsize(p)} for p in parts],
    }
    manifest_path = os.path.join(out_dir, base + MANIFEST_EXT)
    try:
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
    except OSError as exc:
        raise FileKitError(f"could not write manifest: {exc}") from exc
    return parts


def _resolve_parts(parts_glob_or_list):
    if isinstance(parts_glob_or_list, (str, bytes)):
        matches = sorted(_glob.glob(parts_glob_or_list))
        if not matches:
            raise FileKitError(
                f"no parts matched {parts_glob_or_list!r}")
        parts = matches
    else:
        parts = list(parts_glob_or_list)
    parts = [p for p in parts if not p.endswith(MANIFEST_EXT)]
    if not parts:
        raise FileKitError("no parts to join")
    for p in parts:
        require_file(p)
    return parts


def _find_manifest(parts):
    """Best-effort locate a manifest next to the parts. Returns dict or None."""
    seen = set()
    for p in parts:
        d = os.path.dirname(os.path.abspath(p))
        if d in seen:
            continue
        seen.add(d)
        for cand in sorted(_glob.glob(os.path.join(d, "*" + MANIFEST_EXT))):
            try:
                with open(cand, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                continue
    return None


def join_files(parts_glob_or_list, out):
    """Concatenate parts into *out*. Verifies size (and hash) against a manifest.

    *parts_glob_or_list* may be a glob string (e.g. ``"backup.iso.*"``) or an
    explicit ordered list.  Returns *out*.  Raises :class:`FileKitError` if a
    manifest is present and the rebuilt file does not match it.
    """
    parts = _resolve_parts(parts_glob_or_list)
    out = os.path.abspath(out)
    parent = os.path.dirname(out)
    if parent:
        ensure_dir(parent)
    written = 0
    try:
        with open(out, "wb") as dst:
            for p in parts:
                with open(p, "rb") as pf:
                    for chunk in iter(lambda: pf.read(_CHUNK), b""):
                        dst.write(chunk)
                        written += len(chunk)
    except OSError as exc:
        raise FileKitError(f"could not join into {out!r}: {exc}") from exc

    manifest = _find_manifest(parts)
    if manifest:
        expected = manifest.get("size")
        if expected is not None and written != expected:
            raise FileKitError(
                f"joined size {written} != manifest size {expected}; "
                "a part is missing or truncated")
        want_hash = manifest.get("sha256")
        if want_hash:
            got = hash_file(out, "sha256")
            if got != want_hash:
                raise FileKitError(
                    "joined file hash does not match the manifest; "
                    "parts are corrupt or out of order")
    return out


__all__ = ["split_file", "join_files", "MANIFEST_EXT"]
