"""The Kernel's canonical JSON/identity profile at its host boundary."""

from typing import Any, cast

import pytest

from gda_balancing.schema2.canonical import canonical_bytes, content_identity


def test_profile_preserves_unicode_and_sorts_by_utf8_key_order():
    assert canonical_bytes({"é": "é", "a": 1}) == '{"a":1,"é":"é"}\n'.encode()
    assert content_identity("probe", "é") != content_identity("probe", "e\u0301")


@pytest.mark.parametrize("outside_profile", [1.5, 2**63, "\ud800"])
def test_profile_rejects_host_numeric_and_unicode_extensions(outside_profile: Any):
    with pytest.raises((TypeError, ValueError)):
        canonical_bytes(cast(Any, outside_profile))
