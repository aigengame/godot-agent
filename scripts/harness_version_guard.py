"""Fail when bundled harness bytes change without a numeric version increase.

The unit-tier hash pin catches accidental edits inside one checkout. This guard
compares the merge base and head, which is the information a current-snapshot
test cannot recover: when ``gda_harness.gd`` changes in the reviewed range, the
head's HARNESS_VERSION must be numerically greater. CI supplies the PR base/head
or the before/after commits of a push.

Stdlib only, so the workflow can run it without another project dependency.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

HARNESS_PATH = "src/gda/harness/gda_harness.gd"
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
    base_harness: bytes,
    base_install: bytes,
    head_harness: bytes,
    head_install: bytes,
) -> None:
    """Require a numeric version increase exactly when harness bytes changed."""
    if base_harness == head_harness:
        return
    base_version = _version(base_install, "base")
    head_version = _version(head_install, "head")
    if head_version == base_version:
        raise HarnessVersionGuardError(
            "bundled harness bytes changed but HARNESS_VERSION remained "
            f"{head_version}; increase it and update the current hash pin"
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
        base_harness = _git_blob(merge_base, HARNESS_PATH)
        head_harness = _git_blob(args.head, HARNESS_PATH)
        check_change(
            base_harness,
            _git_blob(merge_base, INSTALL_PATH),
            head_harness,
            _git_blob(args.head, INSTALL_PATH),
        )
    except HarnessVersionGuardError as error:
        print(error, file=sys.stderr)
        return 1

    print("harness version transition is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
