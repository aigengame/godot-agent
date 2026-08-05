"""Shared authority inputs for tests that do not exercise loading."""

from typing import Any

from gda_balancing.schema2.authority import packaged_authority_context
from gda_balancing.schema2.authority_graph import LanguageBundleIndex


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Return an owned mutable copy of the admitted packaged authorities."""
    return packaged_authority_context().mutable_pair()
