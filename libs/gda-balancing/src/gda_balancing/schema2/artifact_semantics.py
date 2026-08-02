"""Authority-driven semantic projections for identified artifacts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from gda_balancing.schema2.canonical import JsonValue


def artifact_semantic_projection(
    artifact: dict[str, Any], projection: dict[str, Any]
) -> dict[str, JsonValue]:
    """Project an artifact according to its sealed semantic-identity contract."""
    excluded_root_members = projection.get("excluded_root_members")
    collection_member_exclusions = projection.get("collection_member_exclusions")
    if (
        not isinstance(excluded_root_members, list)
        or not all(
            isinstance(member, str) and member for member in excluded_root_members
        )
        or len(excluded_root_members) != len(set(excluded_root_members))
        or not isinstance(collection_member_exclusions, list)
    ):
        raise ValueError("artifact semantic projection authority is malformed")

    result = deepcopy(
        {
            key: value
            for key, value in artifact.items()
            if key not in set(excluded_root_members)
        }
    )
    seen_collections: set[str] = set()
    for row in collection_member_exclusions:
        if not isinstance(row, dict) or set(row) != {
            "collection_member",
            "excluded_members",
        }:
            raise ValueError("artifact semantic collection projection is malformed")
        collection_member = row.get("collection_member")
        excluded_members = row.get("excluded_members")
        if (
            not isinstance(collection_member, str)
            or not collection_member
            or collection_member in seen_collections
            or not isinstance(excluded_members, list)
            or not all(
                isinstance(member, str) and member for member in excluded_members
            )
            or len(excluded_members) != len(set(excluded_members))
        ):
            raise ValueError("artifact semantic collection projection is malformed")
        collection = result.get(collection_member)
        if not isinstance(collection, list) or not all(
            isinstance(item, dict) for item in collection
        ):
            raise ValueError("artifact semantic projection collection is unavailable")
        excluded = set(excluded_members)
        result[collection_member] = cast(
            JsonValue,
            [
                {key: value for key, value in item.items() if key not in excluded}
                for item in cast(list[dict[str, JsonValue]], collection)
            ],
        )
        seen_collections.add(collection_member)
    return cast(dict[str, JsonValue], result)
