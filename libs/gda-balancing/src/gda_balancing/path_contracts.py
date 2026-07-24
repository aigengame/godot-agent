"""Shared filesystem-path usage contracts."""

import os
from os import PathLike

from gda_balancing.envelope import UsageError


def reject_input_aliasing(
    out: str | PathLike[str], input_path: str | PathLike[str] | None
) -> None:
    """Reject an output path that directly or indirectly names an input.

    A positional value counts as an input path only when it names an existing
    filesystem entry. This keeps enum-like positionals outside the path rule,
    while ``realpath`` closes direct and symlink aliases for file consumers.
    """
    if input_path is None or not os.path.exists(input_path):
        return
    if os.path.realpath(out) == os.path.realpath(input_path):
        raise UsageError(
            "argument_conflict", "--out must not resolve to the input path"
        )
