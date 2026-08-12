"""Bulk file renaming with a safe preview/apply split.

The workflow is deliberately two-phase:

* :func:`plan_rename` is **pure** -- given a list of paths and a
  :class:`RenameRule` it returns ``[(old, new), ...]`` and touches nothing on
  disk.  A GUI/CLI shows this as a live preview.
* :func:`apply_rename` takes that plan, checks for collisions, and performs the
  renames through unique temporaries so chains and swaps (``a->b``, ``b->a``)
  are safe.

A rule can combine find/replace (plain or regex), a ``{n}`` sequence counter
with padding/start, a case transform, a prefix/suffix and an extension change.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .errors import FileKitError

CASES = ("upper", "lower", "title", "capitalize")


@dataclass
class RenameRule:
    """A declarative description of one bulk-rename transform.

    Attributes are applied to each file's **stem** (name without extension) in a
    fixed order: find/replace -> case -> prefix/suffix -> numbering, then the
    (optionally changed) extension is re-attached.
    """

    find: str = ""
    replace: str = ""
    regex: bool = False
    case: str | None = None
    prefix: str = ""
    suffix: str = ""
    number: bool = False
    number_start: int = 1
    number_step: int = 1
    number_pad: int = 3
    number_token: str = "{n}"
    new_ext: str | None = None


def _as_rule(rule):
    if isinstance(rule, RenameRule):
        return rule
    if isinstance(rule, dict):
        try:
            return RenameRule(**rule)
        except TypeError as exc:
            raise FileKitError(f"invalid rename rule: {exc}") from exc
    raise FileKitError("rule must be a RenameRule or a dict")


def _apply_case(text, case):
    if not case:
        return text
    if case == "upper":
        return text.upper()
    if case == "lower":
        return text.lower()
    if case == "title":
        return text.title()
    if case == "capitalize":
        return text.capitalize()
    raise FileKitError(f"unknown case {case!r}; choose from {CASES}")


def _norm_ext(ext):
    if ext is None:
        return None
    ext = ext.strip()
    if not ext:
        return ""
    if not ext.startswith("."):
        ext = "." + ext
    return ext


def new_name_for(old, rule, index):
    """Compute the new *basename* for one file (no disk access).

    *index* is the 0-based position used for the numbering counter.
    """
    rule = _as_rule(rule)
    base = os.path.basename(old)
    stem, ext = os.path.splitext(base)
    if rule.new_ext is not None:
        ext = _norm_ext(rule.new_ext)

    work = stem
    if rule.find:
        if rule.regex:
            try:
                work = re.sub(rule.find, rule.replace, work)
            except re.error as exc:
                raise FileKitError(f"invalid regex {rule.find!r}: {exc}") from exc
        else:
            work = work.replace(rule.find, rule.replace)

    work = _apply_case(work, rule.case)
    work = f"{rule.prefix}{work}{rule.suffix}"

    if rule.number:
        num = rule.number_start + index * rule.number_step
        token = str(num).zfill(max(0, rule.number_pad))
        if rule.number_token and rule.number_token in work:
            work = work.replace(rule.number_token, token)
        else:
            work = f"{work}{token}"

    return work + (ext or "")


def plan_rename(files, rule):
    """Return ``[(old, new), ...]`` for *files* under *rule*. Pure preview.

    ``new`` is a full path in the same directory as ``old``.  Entries whose
    name is unchanged are kept in the plan (callers can grey them out); they are
    simply skipped by :func:`apply_rename`.
    """
    rule = _as_rule(rule)
    plan = []
    for i, old in enumerate(files):
        old = os.path.abspath(old)
        new_base = new_name_for(old, rule, i)
        if not new_base or new_base in (".", ".."):
            raise FileKitError(f"rule produced an invalid name for {old!r}")
        if os.sep in new_base or (os.altsep and os.altsep in new_base):
            raise FileKitError(
                f"rule produced a path separator in the name: {new_base!r}")
        new = os.path.join(os.path.dirname(old), new_base)
        plan.append((old, new))
    return plan


def _check_collisions(plan):
    """Raise :class:`FileKitError` if *plan* cannot be applied safely."""
    olds = {old for old, _ in plan}
    seen = {}
    for old, new in plan:
        if old == new:
            continue
        key = os.path.normcase(new)
        if key in seen:
            raise FileKitError(
                f"two files would be renamed to the same name: {new!r}")
        seen[key] = old
        # A destination that already exists AND isn't itself being renamed away
        # would silently clobber a bystander file -- refuse.
        if os.path.exists(new) and new not in olds:
            raise FileKitError(f"destination already exists: {new!r}")


def apply_rename(plan):
    """Apply a :func:`plan_rename` result on disk. Returns the applied pairs.

    Collisions are detected up front (nothing is renamed if any is found).  The
    rename runs in two passes through unique temporaries so swaps and chains do
    not clobber each other.
    """
    plan = [(os.path.abspath(o), os.path.abspath(n)) for o, n in plan]
    for old, _ in plan:
        if not os.path.exists(old):
            raise FileKitError(f"source no longer exists: {old!r}")
    _check_collisions(plan)

    active = [(o, n) for o, n in plan if o != n]
    temps = []
    try:
        for old, new in active:
            tmp = new + ".fk_tmp_rename"
            n = 0
            while os.path.exists(tmp):
                n += 1
                tmp = f"{new}.fk_tmp_rename{n}"
            os.rename(old, tmp)
            temps.append((tmp, new))
        for tmp, new in temps:
            os.rename(tmp, new)
    except OSError as exc:
        raise FileKitError(f"rename failed: {exc}") from exc
    return active


__all__ = [
    "RenameRule",
    "CASES",
    "new_name_for",
    "plan_rename",
    "apply_rename",
]
