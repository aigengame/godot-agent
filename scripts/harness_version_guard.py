"""Fail when bundled harness bytes change without a numeric version increase.

The unit-tier hash pin catches accidental edits inside one checkout. This guard
compares the merge base and head, which is the information a current-snapshot
test cannot recover: when a file the harness install writes (``gda_harness.gd``,
or the shared value module ``lib/value.gd`` it preloads) changes in the reviewed
range, the head's HARNESS_VERSION must be numerically greater. CI supplies the PR
base/head or the before/after commits of a push.

Stdlib only, so the workflow can run it without another project dependency.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Mapping

# The bundled files the harness install copies into a project: the harness and the
# shared value module it preloads (ADR-0043 §7). A change to either one changes the
# installed harness.
HARNESS_PATHS = ("src/gda/harness/gda_harness.gd", "src/gda/ops/lib/value.gd")
INSTALL_PATH = "src/gda/harness/install.py"
_VERSION = re.compile(rb'^HARNESS_VERSION = "([0-9]+)"$', re.MULTILINE)


class HarnessVersionGuardError(Exception):
    """The two revisions cannot prove a valid harness version transition."""


def _version(source: bytes, revision: str) -> int:
    matches = _VERSION.findall(source)
    if len(matches) != 1:
        raise HarnessVersionGuardError(
            f"{revision} must declare exactly one numeric HARNESS_VERSION assignment"
        )
    return int(matches[0])


def check_change(
    base_harness: Mapping[str, bytes | None],
    base_install: bytes,
    head_harness: Mapping[str, bytes | None],
    head_install: bytes,
) -> None:
    """Require a numeric version increase exactly when harness bytes changed.

    ``base_harness`` and ``head_harness`` map each bundled harness file to its
    bytes at that revision, or to None where the revision does not have the file.
    """
    changed = sorted(
        path
        for path in {*base_harness, *head_harness}
        if base_harness.get(path) != head_harness.get(path)
    )
    if not changed:
        return
    base_version = _version(base_install, "base")
    head_version = _version(head_install, "head")
    if head_version == base_version:
        raise HarnessVersionGuardError(
            f"bundled harness bytes changed ({', '.join(changed)}) but "
            f"HARNESS_VERSION remained {head_version}; increase it and update the "
            "current hash pin"
        )
    if head_version < base_version:
        raise HarnessVersionGuardError(
            "HARNESS_VERSION must increase when bundled harness bytes change "
            f"(base {base_version}, head {head_version})"
        )


def _git_blob(revision: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HarnessVersionGuardError(
            f"cannot read {path} at revision {revision}: {detail}"
        )
    return result.stdout


def _git_blob_if_present(revision: str, path: str) -> bytes | None:
    """The file's bytes at ``revision``, or None when that revision has no such file.

    A revision before the shared value module existed has no ``lib/value.gd``; the
    module then counts as changed, which is what it is for the installed harness.
    """
    listed = subprocess.run(
        ["git", "ls-tree", "--name-only", revision, "--", path],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if listed.returncode != 0:
        detail = listed.stderr.decode(errors="replace").strip()
        raise HarnessVersionGuardError(
            f"cannot list {path} at revision {revision}: {detail}"
        )
    if not listed.stdout.strip():
        return None
    return _git_blob(revision, path)


def _git_merge_base(base: str, head: str) -> str:
    result = subprocess.run(
        ["git", "merge-base", base, head],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise HarnessVersionGuardError(
            f"cannot resolve merge base for {base} and {head}: {detail}"
        )
    merge_base = result.stdout.decode().strip()
    if not merge_base:
        raise HarnessVersionGuardError(
            f"git returned no merge base for {base} and {head}"
        )
    return merge_base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="base Git revision")
    parser.add_argument("head", help="head Git revision")
    args = parser.parse_args(argv)

    try:
        merge_base = _git_merge_base(args.base, args.head)
        check_change(
            {path: _git_blob_if_present(merge_base, path) for path in HARNESS_PATHS},
            _git_blob(merge_base, INSTALL_PATH),
            {path: _git_blob_if_present(args.head, path) for path in HARNESS_PATHS},
            _git_blob(args.head, INSTALL_PATH),
        )
    except HarnessVersionGuardError as error:
        print(error, file=sys.stderr)
        return 1

    print("harness version transition is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
