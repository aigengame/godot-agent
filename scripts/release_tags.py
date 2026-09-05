"""The single authority for the git tags release-please mints in this repo.

Three call sites need to know a package's tag: the Release workflow's root build
job (validating `v<version>`), its gda-balancing build job (validating
`gda-balancing-v<version>`), and the release-PR maintenance gate (requiring every
released component's tag to exist before it runs, #82). Each used to compose the
tag itself, so a supported config change — flipping `include-v-in-tag`, changing
`tag-separator` — would make release-please mint a tag one of them rejects. This
module is the one derivation they all call.

release-please builds a tag from FOUR inherited inputs — `component`,
`include-component-in-tag`, `include-v-in-tag` and `tag-separator` — each
resolved per package with the top-level config value as the default, and
release-please's own default under that. All four are read here; assuming any of
them would reproduce the bug this module exists to remove.

**Supported contract: a component-bearing package declares `component`
explicitly.** release-please can also resolve a component from other package or
strategy metadata (a package name, a strategy's default), and reimplementing
that resolution here would be a second, drifting copy of release-please's
internals. So this module does not infer: a package that puts a component in its
tag without naming one raises `TagDerivationError` rather than guessing. The
repo's config satisfies the contract today, and `tests/repo/test_release_tags.py`
holds a drift alarm that fails if it stops doing so.

Stdlib only, so it runs with **no project environment synced** — a workflow
runner that installed uv but resolved neither project can run it. That is a
claim about dependencies, NOT about the interpreter: this module targets the
repo's pinned Python like everything else here, so its call sites name the
interpreter explicitly (`uv run --no-project --python 3.13 python …`) rather
than inheriting whatever `python3` a runner image happens to ship. A guard
whose interpreter drifts with the base image is a guard nobody controls.
`from __future__ import annotations` stays as hygiene, not as a compatibility
promise to any older interpreter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# release-please's first bump can never produce 0.0.0, so a manifest entry still
# at this version is an unambiguous never-released marker.
PLACEHOLDER = "0.0.0"

# release-please's own defaults, used when neither the package nor the top-level
# config states a value.
INCLUDE_COMPONENT_IN_TAG_DEFAULT = True
INCLUDE_V_IN_TAG_DEFAULT = True
TAG_SEPARATOR_DEFAULT = "-"


class TagDerivationError(Exception):
    """A config this module cannot turn into the tag release-please would mint."""


def _setting(
    config: dict[str, Any], package: dict[str, Any], key: str, fallback: object
) -> Any:
    """Resolve one inherited input: package value, else top-level, else default."""
    if key in package:
        return package[key]
    return config.get(key, fallback)


def derive_tag(config: dict[str, Any], path: str, version: str) -> str:
    """The tag release-please mints for `path` at `version`.

    Raises `TagDerivationError` when the config falls outside the supported
    contract described in the module docstring.
    """
    packages = config.get("packages") or {}
    if path not in packages:
        raise TagDerivationError(
            f"release-please-config.json declares no package {path!r}, "
            "so its tag cannot be derived"
        )
    package = packages[path]

    component = package.get("component")
    in_tag = _setting(
        config, package, "include-component-in-tag", INCLUDE_COMPONENT_IN_TAG_DEFAULT
    )
    include_v = _setting(config, package, "include-v-in-tag", INCLUDE_V_IN_TAG_DEFAULT)
    separator = _setting(config, package, "tag-separator", TAG_SEPARATOR_DEFAULT)

    if in_tag and not component:
        raise TagDerivationError(
            f"package {path!r} sets include-component-in-tag without an explicit "
            "component, so its tag cannot be derived. release-please may infer a "
            "component from other package metadata, but this repo's supported "
            "contract is an explicit `component` key — declare one."
        )

    prefix = f"{component}{separator}" if in_tag else ""
    return f"{prefix}{'v' if include_v else ''}{version}"


def required_tags(
    config: dict[str, Any],
    manifest: dict[str, str],
    placeholder: str = PLACEHOLDER,
) -> list[str]:
    """Every already-released package's tag, in manifest order.

    A package still at `placeholder` has never released and has no tag to
    require. Requiring one anyway would deadlock its train: no tag exists until
    the first release, and without release-PR maintenance no Release PR
    proposing that release is ever created.
    """
    return [
        derive_tag(config, path, version)
        for path, version in manifest.items()
        if version != placeholder
    ]


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="release-please-config.json")
    parser.add_argument("--manifest", default=".release-please-manifest.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--required-tags",
        action="store_true",
        help="print every released package's tag, one per line",
    )
    mode.add_argument(
        "--tag-for",
        metavar="PATH",
        help="print the tag for one manifest package path",
    )
    parser.add_argument("--version", help="the version to compose --tag-for with")
    args = parser.parse_args(argv)
    # The mutually exclusive group is `required`, so exactly one of these holds:
    # `--tag-for` is set, or `--required-tags` was passed.
    tag_for: str | None = args.tag_for
    version: str | None = args.version

    try:
        config = _load(args.config)
        if tag_for is None:
            lines = required_tags(config, _load(args.manifest))
        elif version is None:
            parser.error("--tag-for requires --version")
        else:
            lines = [derive_tag(config, tag_for, version)]
    except (TagDerivationError, OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
