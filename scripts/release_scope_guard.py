"""Guard: a releasing-typed PR must not straddle the member boundary.

release-please drops a commit from the root `gda` package only when EVERY
changed file is excluded, and `exclude-paths` matches directory prefixes only
(ADR-0038). So a releasing-typed PR that touches `libs/gda-balancing` AND
anything outside it proposes two Release PRs — the mistake ADR-0037 describes.
This module decides that at PR time.

Both of its inputs are DERIVED from `release-please-config.json`, never
restated:

- **The releasing types** come from `changelog-sections`: every non-hidden
  section is release-producing, because release-please's default versioning
  strategy patch-bumps such a commit. Hard-coding `{feat, fix}` missed `deps`
  and `revert`, which this repo's config exposes as visible sections.
  `changelog-sections` is resolved **per package** by key presence — a
  package's own value when it declares the key, else the top-level one —
  because release-please lets a package override it and reading only the top
  level would then describe a package's release train incorrectly. There is
  no third fallback: a package with sections at neither level fails loudly,
  since release-please's built-in defaults vary by `release-type` (see
  `releasing_types`).
- **The member directory** comes from the root package's `exclude-paths`, the
  single authority for "which paths do not count for the root package".

The verdict combines the per-package sets **conservatively**: a title is
releasing if it release-produces for ANY package the PR touches, not only when
it does so for all of them. A type that releases only the root still reproduces
the harm this guard exists to stop — a member-scoped change bumping `gda` — and
a guard may fail a harmless PR but must never pass a harmful one.

A hand-maintained copy of either would drift out of agreement with the very
mechanism this guard exists to protect.

Stdlib only, so it needs no synced project environment — see `release_tags.py`
for the interpreter contract that claim does and does not include.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# `type: `, `type!: `, `type(scope): `, `type(scope)!: `. Deliberately lenient
# about what follows the colon: being STRICTER than release-please's parser
# would let a releasing title slip past the guard, while being looser only ever
# fails a harmless PR — so the safe direction is loose.
_HEADER = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\([^)]*\))?(?P<bang>!)?:")


class ScopeGuardConfigError(Exception):
    """A config this guard cannot derive its inputs from."""


_MISSING = object()


def releasing_types(config: dict[str, Any], path: str) -> set[str]:
    """The releasing conventional-commit types for ONE package.

    `changelog-sections` is an inherited input like the four in
    `release_tags.py`, and is resolved the same way: **by key presence** —
    the package's own value when it declares the key at all, else the
    top-level value. Nullish precedence is release-please's own rule, and it
    is why presence rather than truthiness decides: a package declaring an
    explicit empty list overrides the top-level list with "no visible
    sections", whereas a truthiness test would silently inherit the top level
    and over-report that package's releasing types.

    **A package with no explicit sections at either level raises**, rather
    than falling back to a default set. release-please's built-in defaults are
    per-`release-type`: this repo declares `"release-type": "python"`, whose
    strategy installs its own sections list that additionally makes `deps` and
    `docs` visible — so the generic `DEFAULT_CHANGELOG_SECTIONS`
    (`feat, fix, perf, revert`) this guard used to fall back to would report a
    `deps:` or `docs:` title as non-releasing. That is a FALSE PASS, the one
    direction a guard must never fail in. Reimplementing upstream's
    per-strategy default tables would instead make this module a second
    authority on release-please's internals — the duplication the derived
    inputs above exist to avoid — so the guard requires the config to say what
    it means.
    """
    packages = config.get("packages") or {}
    package = packages.get(path) or {}
    sections = package.get("changelog-sections", _MISSING)
    if sections is _MISSING:
        sections = config.get("changelog-sections", _MISSING)
    if sections is _MISSING:
        raise ScopeGuardConfigError(
            f"release-please-config.json declares no changelog-sections for "
            f"package {path!r} (neither its own nor a top-level default), so "
            "this guard cannot derive its releasing commit types. Declare them "
            "explicitly: release-please's built-in defaults vary by "
            "`release-type` — the python strategy this repo uses makes `deps` "
            "and `docs` visible on top of the generic defaults — and guessing "
            "which set applies would let a releasing title pass unguarded."
        )
    return {section["type"] for section in sections if not section.get("hidden", False)}


def is_releasing_title(title: str, releasing: set[str]) -> bool:
    """Whether a PR title would make release-please propose a release.

    A breaking `!` marker makes ANY type releasing, including one that has no
    changelog section at all. A title that does not parse as a conventional
    commit header is NOT releasing: release-please cannot read a version bump
    out of a header it cannot parse, so such a title bumps nothing.

    Title-only, by construction — a `BREAKING CHANGE:` footer in the commit body
    also bumps, but a PR title guard cannot see the body. Squash-merge titles
    are the surface this repo releases from, so that is the surface guarded.
    """
    header = _HEADER.match(title)
    if header is None:
        return False
    return header.group("bang") is not None or header.group("type").lower() in releasing


def member_dirs(config: dict[str, Any]) -> list[str]:
    """The directories excluded from the root package.

    DERIVED from `release-please-config.json`'s root `exclude-paths`, never
    restated: that list is the single authority for "which paths do not count
    for the root package", and a second hand-maintained copy here would drift
    out of agreement with the very mechanism this guard exists to protect.
    """
    excluded = (config.get("packages") or {}).get(".", {}).get("exclude-paths") or []
    if not excluded:
        raise ScopeGuardConfigError(
            "release-please-config.json declares no exclude-paths for the root "
            "package, so this guard cannot derive a member directory."
        )
    return list(excluded)


def _under(path: str, directory: str) -> bool:
    # release-please's own matcher semantics: a directory prefix
    # (`file.indexOf(path + "/") === 0`), never a file and never a glob. So
    # `libs/gda-balancing-extra/x` is NOT inside `libs/gda-balancing`.
    return path.startswith(directory.rstrip("/") + "/")


@dataclass(frozen=True)
class Verdict:
    """What the workflow needs to decide, and to explain, a scope failure."""

    title: str
    releasing: bool
    member_dirs: list[str]
    inside: list[str]
    outside: list[str]

    @property
    def touches_member(self) -> bool:
        return bool(self.inside)

    @property
    def touches_outside(self) -> bool:
        return bool(self.outside)

    @property
    def ok(self) -> bool:
        """A releasing PR that straddles the member boundary is the failure.

        Everything else passes: a non-releasing PR bumps nothing wherever it
        reaches, and a releasing PR confined to one side proposes exactly one
        release train.
        """
        return not (self.releasing and self.touches_member and self.touches_outside)

    def message(self) -> str:
        if not self.releasing:
            return (
                f"PR title {self.title!r} declares no releasing type; guard is a no-op."
            )
        if not self.touches_member:
            return (
                f"PR touches no file under {self.member_dirs}; "
                "not a member PR, guard is a no-op."
            )
        if not self.touches_outside:
            return (
                f"Releasing-typed member PR is confined to {self.member_dirs}; "
                "only the member's release train can be proposed."
            )

        listing = "\n".join(f"  {path}" for path in self.outside)
        return (
            f"PR title {self.title!r} declares a releasing conventional-commit type "
            f"and the PR touches {self.member_dirs}, but these changed files fall "
            f"outside it:\n{listing}\n\n"
            "release-please excludes a commit from the root `gda` package only "
            "when EVERY changed file is excluded, so merging this would propose "
            "BOTH a gda release and a gda-balancing release (ADR-0037/0038).\n"
            "Fix by splitting the PR: keep the releasing-typed change confined "
            "to the member directory, and move the files above into a separate "
            "PR (a non-releasing type, or its own gda-releasing one)."
        )


def touched_packages(config: dict[str, Any], changed_files: list[str]) -> list[str]:
    """The declared packages whose release train this PR's files can reach.

    The root `"."` is ALWAYS in scope: it is the package every unexcluded path
    belongs to, so any PR that can fail this guard touches it by definition, and
    keeping it in scope for an empty file listing stops a missing listing from
    silently disarming the guard.
    """
    packages = config.get("packages") or {}
    members = [
        path
        for path in packages
        if path != "." and any(_under(f, path) for f in changed_files)
    ]
    return [".", *members]


def verdict(title: str, changed_files: list[str], config: dict[str, Any]) -> Verdict:
    directories = member_dirs(config)
    inside = [f for f in changed_files if any(_under(f, d) for d in directories)]
    inside_set = set(inside)

    # CONSERVATIVE union, not intersection: the title is releasing if it
    # release-produces for ANY package the PR touches. The finding phrased the
    # harm as "releases both", but a type that releases only the root still
    # reproduces the original damage — a member-scoped change bumping `gda` —
    # and a guard must never have a false pass. Under today's config no package
    # overrides `changelog-sections`, so every package resolves to the same set
    # and the two predicates coincide; they diverge only once an override lands.
    releasing = {
        commit_type
        for path in touched_packages(config, changed_files)
        for commit_type in releasing_types(config, path)
    }

    return Verdict(
        title=title,
        releasing=is_releasing_title(title, releasing),
        member_dirs=directories,
        inside=inside,
        outside=[f for f in changed_files if f not in inside_set],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="release-please-config.json")
    parser.add_argument(
        "--title",
        default=os.environ.get("PR_TITLE"),
        help="the PR title (defaults to $PR_TITLE)",
    )
    parser.add_argument(
        "--changed-files",
        required=True,
        metavar="PATH",
        help="a file listing the PR's changed paths, one per line ('-' for stdin)",
    )
    args = parser.parse_args(argv)

    if args.title is None:
        parser.error("--title is required when $PR_TITLE is unset")

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if args.changed_files == "-":
            listing = sys.stdin.read()
        else:
            listing = Path(args.changed_files).read_text(encoding="utf-8")
        result = verdict(args.title, [f for f in listing.splitlines() if f], config)
    except (ScopeGuardConfigError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    if result.ok:
        print(result.message())
        return 0
    print(result.message(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
