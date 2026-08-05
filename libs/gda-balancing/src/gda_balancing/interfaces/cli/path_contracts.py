"""Shared filesystem-path usage contracts."""

import os
from os import PathLike

from gda_balancing.interfaces.cli.errors import UsageError


def reject_input_aliasing(
    out: str | PathLike[str],
    input_path: str | PathLike[str] | None,
    *,
    input_is_known_path: bool = False,
) -> None:
    """Reject an output path that directly or indirectly names an input.

    A generic positional counts as an input path only while it names an
    existing filesystem entry. A consumer that already admitted the input as a
    path sets ``input_is_known_path`` so the alias rule survives a later rename
    or removal. ``realpath`` closes direct and symlink aliases in both modes.
    """
    if input_path is None:
        return
    if not input_is_known_path and not os.path.exists(input_path):
        return
    if os.path.realpath(out) == os.path.realpath(input_path):
        raise UsageError(
            "argument_conflict", "--out must not resolve to the input path"
        )
