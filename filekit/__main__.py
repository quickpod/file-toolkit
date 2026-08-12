"""Command-line interface: ``python -m filekit <command> ...``.

Destructive commands are safe by default: ``rename`` previews unless
``--apply``, ``dedupe`` is a dry-run unless ``--apply``, and ``secure-delete``
refuses to run without ``--yes``.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import (
    FileKitError,
    apply_rename,
    find_duplicates,
    hash_file,
    join_files,
    plan_rename,
    remove_duplicates,
    secure_delete,
    sevenz_create,
    sevenz_extract,
    split_file,
    to_recycle,
    verify_sums,
    write_sha256sums,
    zip_create,
    zip_extract,
)
from .common import human_size, parse_size
from .rename import RenameRule


# --- command handlers -------------------------------------------------------


def _rule_from_args(a):
    return RenameRule(
        find=a.find or "",
        replace=a.replace or "",
        regex=a.regex,
        case=a.case,
        prefix=a.prefix or "",
        suffix=a.suffix or "",
        number=a.number,
        number_start=a.number_start,
        number_step=a.number_step,
        number_pad=a.number_pad,
        new_ext=a.ext,
    )


def cmd_rename(a):
    rule = _rule_from_args(a)
    plan = plan_rename(a.files, rule)
    changed = [(o, n) for o, n in plan if o != n]
    if not a.apply:
        print(f"Preview ({len(changed)} of {len(plan)} file(s) would change):")
        for old, new in plan:
            mark = " " if old == new else "*"
            print(f" {mark} {os.path.basename(old)}  ->  {os.path.basename(new)}")
        if changed:
            print("Re-run with --apply to perform the rename.")
        return
    applied = apply_rename(plan)
    print(f"Renamed {len(applied)} file(s).")


def cmd_dedupe(a):
    groups = find_duplicates(a.root, by=a.algo)
    total_dupes = sum(len(g) - 1 for g in groups)
    print(f"Found {len(groups)} duplicate group(s), {total_dupes} redundant file(s).")
    for i, group in enumerate(groups, 1):
        print(f"  group {i} ({human_size(os.path.getsize(group[0]))} each):")
        for p in group:
            print(f"     {p}")
    if not a.apply:
        if groups:
            print("Dry run — re-run with --apply to remove the redundant copies.")
        return
    removed = remove_duplicates(groups, keep=a.keep, to_trash=not a.permanent)
    where = "deleted permanently" if a.permanent else "sent to the Recycle Bin"
    print(f"Removed {len(removed)} file(s) ({where}).")


def cmd_hash(a):
    if os.path.isdir(a.path):
        out = a.output or os.path.join(a.path, "SHA256SUMS")
        count = write_sha256sums(a.path, out, algo=a.algo)
        print(f"Wrote {count} {a.algo} checksum(s) -> {out}")
    else:
        print(f"{hash_file(a.path, a.algo)}  {os.path.basename(a.path)}")


def cmd_verify(a):
    results = verify_sums(a.sumsfile, algo=a.algo)
    ok = sum(1 for r in results if r["status"] == "ok")
    bad = [r for r in results if r["status"] != "ok"]
    for r in results:
        if r["status"] != "ok" or a.verbose:
            print(f"  {r['status'].upper():7} {r['path']}")
    print(f"{ok}/{len(results)} OK", end="")
    if bad:
        n_fail = sum(1 for r in bad if r["status"] == "failed")
        n_miss = sum(1 for r in bad if r["status"] == "missing")
        print(f"  ({n_fail} failed, {n_miss} missing)")
        raise FileKitError("verification failed")
    print()


def cmd_zip(a):
    out = zip_create(a.paths, a.output)
    print(f"Created {out} ({human_size(os.path.getsize(out))})")


def cmd_unzip(a):
    names = zip_extract(a.archive, a.dest)
    print(f"Extracted {len(names)} item(s) -> {a.dest}")


def cmd_7z(a):
    out = sevenz_create(a.paths, a.output, password=a.password)
    lock = " (encrypted)" if a.password else ""
    print(f"Created {out}{lock} ({human_size(os.path.getsize(out))})")


def cmd_un7z(a):
    names = sevenz_extract(a.archive, a.dest, password=a.password)
    print(f"Extracted {len(names)} item(s) -> {a.dest}")


def cmd_split(a):
    parts = split_file(a.path, parse_size(a.size), a.out_dir)
    print(f"Split into {len(parts)} part(s) of up to {a.size} -> {a.out_dir}")


def cmd_join(a):
    target = a.parts[0] if len(a.parts) == 1 else a.parts
    out = join_files(target, a.output)
    print(f"Joined -> {out} ({human_size(os.path.getsize(out))})")


def cmd_secure_delete(a):
    if not a.yes:
        raise FileKitError(
            "refusing to wipe without confirmation; pass --yes to proceed")
    secure_delete(a.path, passes=a.passes)
    print(f"Securely deleted {a.path} ({a.passes} pass(es)).")


def cmd_trash(a):
    to_recycle(a.path)
    print(f"Sent to the Recycle Bin: {a.path}")


# --- parser -----------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="filekit",
        description="Offline batch file utilities: rename, dedupe, checksum, "
        "archive, split/join and secure delete. Destructive commands preview or "
        "dry-run by default.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, help, handler):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(func=handler)
        return sp

    s = add("rename", "Bulk rename files (previews unless --apply)", cmd_rename)
    s.add_argument("files", nargs="+")
    s.add_argument("--find", help="text (or regex with --regex) to replace")
    s.add_argument("--replace", default="", help="replacement text")
    s.add_argument("--regex", action="store_true", help="treat --find as a regex")
    s.add_argument("--case", choices=["upper", "lower", "title", "capitalize"])
    s.add_argument("--prefix", default="")
    s.add_argument("--suffix", default="")
    s.add_argument("--number", action="store_true",
                   help="substitute {n} (or append) a sequence number")
    s.add_argument("--number-start", type=int, default=1)
    s.add_argument("--number-step", type=int, default=1)
    s.add_argument("--number-pad", type=int, default=3)
    s.add_argument("--ext", help="change the extension (e.g. .txt)")
    s.add_argument("--preview", action="store_true",
                   help="show the plan without renaming (the default)")
    s.add_argument("--apply", action="store_true", help="actually rename")

    s = add("dedupe", "Find duplicate files (dry-run unless --apply)", cmd_dedupe)
    s.add_argument("root")
    s.add_argument("--algo", default="sha256", help="hash algorithm (sha256)")
    s.add_argument("--keep", choices=["first", "last"], default="first")
    s.add_argument("--apply", action="store_true", help="remove redundant copies")
    s.add_argument("--permanent", action="store_true",
                   help="delete permanently instead of using the Recycle Bin")
    s.add_argument("--dry-run", action="store_true",
                   help="explicitly only report (the default)")

    s = add("hash", "Hash a file, or write SHA256SUMS for a folder", cmd_hash)
    s.add_argument("path")
    s.add_argument("--algo", default="sha256")
    s.add_argument("-o", "--output", help="sums file (folder mode)")

    s = add("verify", "Verify a sums manifest", cmd_verify)
    s.add_argument("sumsfile")
    s.add_argument("--algo", default="sha256")
    s.add_argument("-v", "--verbose", action="store_true", help="show OK lines too")

    s = add("zip", "Create a ZIP archive", cmd_zip)
    s.add_argument("paths", nargs="+")
    s.add_argument("-o", "--output", required=True)

    s = add("unzip", "Extract a ZIP archive", cmd_unzip)
    s.add_argument("archive")
    s.add_argument("-d", "--dest", required=True)

    s = add("7z", "Create a 7z archive (optional --password)", cmd_7z)
    s.add_argument("paths", nargs="+")
    s.add_argument("-o", "--output", required=True)
    s.add_argument("--password", default=None)

    s = add("un7z", "Extract a 7z archive (optional --password)", cmd_un7z)
    s.add_argument("archive")
    s.add_argument("-d", "--dest", required=True)
    s.add_argument("--password", default=None)

    s = add("split", "Split a file into fixed-size parts", cmd_split)
    s.add_argument("path")
    s.add_argument("--size", required=True, help="part size, e.g. 10M, 700M, 1G")
    s.add_argument("-d", "--out-dir", required=True)

    s = add("join", "Join parts back into one file", cmd_join)
    s.add_argument("parts", nargs="+", help="a glob string or an ordered list")
    s.add_argument("-o", "--output", required=True)

    s = add("secure-delete", "Overwrite then delete a file (needs --yes)",
            cmd_secure_delete)
    s.add_argument("path")
    s.add_argument("--passes", type=int, default=1)
    s.add_argument("--yes", action="store_true", help="confirm the wipe")

    s = add("trash", "Send a file/folder to the Recycle Bin", cmd_trash)
    s.add_argument("path")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except FileKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
