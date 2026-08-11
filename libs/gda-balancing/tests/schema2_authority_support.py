"""Shared authority inputs for tests that do not exercise loading."""

from typing import Any

from gda_balancing.domain.authority.context import packaged_authority_context
from gda_balancing.domain.authority.graph import LanguageBundleIndex


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Return an owned mutable copy of the admitted packaged authorities."""
    return packaged_authority_context().mutable_pair()
