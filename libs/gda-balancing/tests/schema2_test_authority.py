"""Fast, isolated authority candidates for tests that do not exercise loading."""

from typing import Any

from gda_balancing.schema2.authority import packaged_authority_context
from gda_balancing.schema2.authority_graph import LanguageBundleIndex


def mutable_authorities() -> tuple[dict[str, Any], LanguageBundleIndex]:
    """Copy the one admitted process baseline without repeating admission."""
    return packaged_authority_context().mutable_pair()
